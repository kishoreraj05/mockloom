"""Per-workspace in-memory state. Mock requests read from here and never touch the database.

This assumes one server process: other workers would not see cache invalidations, so run a
single uvicorn worker.
"""

from __future__ import annotations

import asyncio
import threading
from collections import OrderedDict
from dataclasses import dataclass

from mockloom_engine import ChaosConfig, CompiledSpec, MockEngine, Rule, compile_spec
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .models import ChaosRow, RuleRow, SpecVersion, Workspace

_SPEC_CACHE_SIZE = 32


@dataclass
class Runtime:
    workspace_id: str
    slug: str
    engine: MockEngine


class RuntimeManager:
    def __init__(self, sessions: sessionmaker[Session]):
        self.sessions = sessions
        self._runtimes: dict[str, Runtime] = {}
        self._generation: dict[str, int] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._specs: OrderedDict[str, CompiledSpec] = OrderedDict()
        self._spec_lock = threading.Lock()

    async def get(self, slug: str) -> Runtime | None:
        runtime = self._runtimes.get(slug)
        if runtime is not None:
            return runtime
        lock = self._locks.setdefault(slug, asyncio.Lock())
        async with lock:
            runtime = self._runtimes.get(slug)
            if runtime is not None:
                return runtime
            while True:
                generation = self._generation.get(slug, 0)
                runtime = await asyncio.to_thread(self._load, slug)
                # A management write that landed during the load makes this copy stale.
                if generation == self._generation.get(slug, 0):
                    break
            if runtime is not None:
                self._runtimes[slug] = runtime
            else:
                self._locks.pop(slug, None)
            return runtime

    def invalidate(self, slug: str) -> None:
        """Called by management writes, from worker threads, after they commit."""
        self._generation[slug] = self._generation.get(slug, 0) + 1
        self._runtimes.pop(slug, None)

    def compiled(self, content_hash: str, text: str) -> CompiledSpec:
        with self._spec_lock:
            spec = self._specs.get(content_hash)
            if spec is not None:
                self._specs.move_to_end(content_hash)
                return spec
        spec = compile_spec(text)
        with self._spec_lock:
            self._specs[content_hash] = spec
            while len(self._specs) > _SPEC_CACHE_SIZE:
                self._specs.popitem(last=False)
        return spec

    def compiled_for(self, session: Session, workspace: Workspace) -> CompiledSpec | None:
        if workspace.active_version_id is None:
            return None
        version = session.get(SpecVersion, workspace.active_version_id)
        return self.compiled(version.content_hash, version.raw_text) if version else None

    def _load(self, slug: str) -> Runtime | None:
        with self.sessions() as session:
            workspace = session.scalar(select(Workspace).where(Workspace.slug == slug))
            if workspace is None:
                return None
            spec = self.compiled_for(session, workspace)
            rows = session.scalars(
                select(RuleRow)
                .where(RuleRow.workspace_id == workspace.id, RuleRow.orphaned.is_(False))
                .order_by(RuleRow.created_at)
            ).all()
            rules: list[tuple[str, Rule]] = []
            for row in rows:
                try:
                    rules.append((row.id, row_to_rule(row)))
                except ValidationError:
                    continue  # Stored before a stricter schema; it must not stop the workspace.
            chaos = {
                row.route_key: ChaosConfig(
                    latency_min_ms=row.latency_min_ms,
                    latency_max_ms=row.latency_max_ms,
                    error_rate=row.error_rate,
                    forced_status=row.forced_status,
                    offline=row.offline,
                )
                for row in session.scalars(
                    select(ChaosRow).where(ChaosRow.workspace_id == workspace.id)
                )
            }
            engine = MockEngine(
                spec,
                rules,
                chaos,
                seed=workspace.seed,
                validate=workspace.validation_mode == "strict",
            )
            return Runtime(workspace.id, workspace.slug, engine)


def row_to_rule(row: RuleRow) -> Rule:
    return Rule.model_validate(
        {
            "name": row.name,
            "route": row.route_key,
            "priority": row.priority,
            "enabled": row.enabled,
            "when": row.when_json,
            "then": row.then_json,
        }
    )
