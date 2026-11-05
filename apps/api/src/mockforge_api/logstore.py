"""Live request log: a ring buffer per workspace, WebSocket fan-out, batched writes to the database.

Recording never awaits and never touches the database, so a slow disk cannot slow a mock.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from collections import defaultdict, deque
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from .models import RequestLog, Workspace
from .settings import Settings

logger = logging.getLogger("mockforge.logs")
_MAX_PENDING = 50_000
_SUBSCRIBER_QUEUE = 2_000


class LogHub:
    def __init__(self, sessions: sessionmaker[Session], settings: Settings):
        self.sessions = sessions
        self.settings = settings
        self._rings: dict[str, deque[dict[str, Any]]] = {}
        self._hydrated: set[str] = set()
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._pending: list[dict[str, Any]] = []
        self._tasks: list[asyncio.Task] = []

    def _ring(self, workspace_id: str) -> deque[dict[str, Any]]:
        ring = self._rings.get(workspace_id)
        if ring is None:
            ring = self._rings[workspace_id] = deque(maxlen=self.settings.log_ring_size)
        return ring

    def record(self, entry: dict[str, Any]) -> None:
        workspace_id = entry["workspace_id"]
        self._ring(workspace_id).append(entry)
        self._pending.append(entry)
        if len(self._pending) > _MAX_PENDING:
            del self._pending[: len(self._pending) - _MAX_PENDING]
        for queue in self._subscribers.get(workspace_id, ()):
            if queue.full():  # A stalled browser loses its oldest rows, not everyone's latency.
                queue.get_nowait()
            queue.put_nowait(entry)

    def recent(self, workspace_id: str, limit: int) -> list[dict[str, Any]]:
        ring = self._ring(workspace_id)
        if workspace_id not in self._hydrated:
            # After a restart a live request may have created the ring first, so older rows go in
            # front of whatever is already there, without pushing out anything newer.
            self._hydrated.add(workspace_id)
            known = {entry["id"] for entry in list(ring)}
            older = [e for e in self._load_from_db(workspace_id) if e["id"] not in known]
            room = self.settings.log_ring_size - len(ring)
            if room > 0:
                ring.extendleft(reversed(older[-room:]))
        return list(ring)[-limit:]

    def older(self, workspace_id: str, before: dt.datetime, limit: int) -> list[dict[str, Any]]:
        """Rows older than a moment, oldest first. Beyond the ring, only the database has them."""
        if before.tzinfo is None:
            before = before.replace(tzinfo=dt.UTC)
        with self.sessions() as session:
            rows = session.scalars(
                select(RequestLog)
                .where(RequestLog.workspace_id == workspace_id, RequestLog.ts < before.astimezone(dt.UTC))
                .order_by(RequestLog.ts.desc())
                .limit(limit)
            ).all()
        return [_row_to_entry(row) for row in reversed(rows)]

    def _load_from_db(self, workspace_id: str) -> list[dict[str, Any]]:
        with self.sessions() as session:
            rows = session.scalars(
                select(RequestLog)
                .where(RequestLog.workspace_id == workspace_id)
                .order_by(RequestLog.ts.desc())
                .limit(self.settings.log_ring_size)
            ).all()
        return [_row_to_entry(row) for row in reversed(rows)]

    def clear(self, workspace_id: str) -> None:
        self._ring(workspace_id).clear()
        self._pending = [e for e in self._pending if e["workspace_id"] != workspace_id]
        with self.sessions() as session:
            session.execute(delete(RequestLog).where(RequestLog.workspace_id == workspace_id))
            session.commit()

    def forget(self, workspace_id: str) -> None:
        self._rings.pop(workspace_id, None)
        self._hydrated.discard(workspace_id)
        self._pending = [e for e in self._pending if e["workspace_id"] != workspace_id]

    def subscribe(self, workspace_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=_SUBSCRIBER_QUEUE)
        self._subscribers[workspace_id].add(queue)
        return queue

    def unsubscribe(self, workspace_id: str, queue: asyncio.Queue) -> None:
        self._subscribers[workspace_id].discard(queue)
        if not self._subscribers[workspace_id]:
            del self._subscribers[workspace_id]

    def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._flush_loop()),
            asyncio.create_task(self._prune_loop()),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.flush()

    async def flush(self) -> None:
        if not self._pending:
            return
        batch, self._pending = self._pending, []
        try:
            await asyncio.to_thread(self._write, batch)
        except Exception:  # noqa: BLE001 - losing log history must never take the mock down
            logger.exception("Could not write %d log rows", len(batch))

    def _write(self, batch: list[dict[str, Any]]) -> None:
        with self.sessions() as session:
            # A workspace can be deleted while its rows wait here.
            wanted = {e["workspace_id"] for e in batch}
            alive = set(session.scalars(select(Workspace.id).where(Workspace.id.in_(wanted))))
            session.add_all(
                RequestLog(
                    id=e["id"],
                    workspace_id=e["workspace_id"],
                    ts=e["ts"],
                    method=e["method"],
                    path=e["path"][:2048],
                    status=e["status"],
                    route_key=e["route_key"],
                    rule_id=e["rule_id"],
                    rule_name=e["rule_name"],
                    source=e["source"],
                    chaos=e["chaos"],
                    duration_ms=e["duration_ms"],
                    overhead_ms=e["overhead_ms"],
                    request_json=e["request"],
                    response_json=e["response"],
                )
                for e in batch
                if e["workspace_id"] in alive
            )
            session.commit()

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(self.settings.log_flush_seconds)
            await self.flush()

    async def _prune_loop(self) -> None:
        while True:
            await asyncio.sleep(self.settings.log_prune_seconds)
            try:
                await asyncio.to_thread(self.prune)
            except Exception:  # noqa: BLE001
                logger.exception("Could not prune logs")

    def prune(self) -> None:
        cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(
            days=self.settings.log_retention_days
        )
        with self.sessions() as session:
            session.execute(delete(RequestLog).where(RequestLog.ts < cutoff))
            for workspace_id in session.scalars(select(Workspace.id)).all():
                boundary = session.scalar(
                    select(RequestLog.ts)
                    .where(RequestLog.workspace_id == workspace_id)
                    .order_by(RequestLog.ts.desc())
                    .offset(self.settings.log_retention_rows)
                    .limit(1)
                )
                if boundary is not None:
                    session.execute(
                        delete(RequestLog).where(
                            RequestLog.workspace_id == workspace_id, RequestLog.ts <= boundary
                        )
                    )
            session.commit()


def _row_to_entry(row: RequestLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        # SQLite hands datetimes back without a timezone. They are always UTC, and without saying so
        # browsers would read them as local time.
        "ts": row.ts if row.ts.tzinfo else row.ts.replace(tzinfo=dt.UTC),
        "method": row.method,
        "path": row.path,
        "status": row.status,
        "route_key": row.route_key,
        "rule_id": row.rule_id,
        "rule_name": row.rule_name,
        "source": row.source,
        "chaos": row.chaos,
        "duration_ms": row.duration_ms,
        "overhead_ms": row.overhead_ms,
        "request": row.request_json,
        "response": row.response_json,
    }


def public_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in entry.items() if k != "workspace_id"}
