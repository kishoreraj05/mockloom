"""The management API used by the React app. Handlers are sync, so FastAPI runs them in threads."""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import re
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from mockforge_engine import CompiledRoute, CompiledSpec, sample_body, validate_text
from mockforge_engine.compiler import ValidationReport
from mockforge_engine.loader import SpecIssue
from mockforge_engine.request import is_json_type
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import schemas as s
from ..logstore import public_entry
from ..models import ChaosRow, RuleRow, SpecVersion, Workspace, new_id

router = APIRouter(prefix="/api")

_STREAM_BATCH = 500


def _json_default(value: Any) -> str:
    if isinstance(value, dt.datetime):
        return value.isoformat()
    return str(value)


def get_session(request: Request):
    with request.app.state.sessions() as session:
        yield session


def _workspace(session: Session, slug: str) -> Workspace:
    workspace = session.scalar(select(Workspace).where(Workspace.slug == slug))
    if workspace is None:
        raise HTTPException(404, f"Workspace '{slug}' does not exist")
    return workspace


def _issue_out(issue: SpecIssue) -> s.SpecIssueOut:
    return s.SpecIssueOut(
        severity=issue.severity, message=issue.message, path=issue.path, line=issue.line
    )


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48].strip("-")
    return slug or "workspace"


def _unique_slug(session: Session, base: str) -> str:
    candidate, suffix = base, 2
    while session.scalar(select(Workspace.id).where(Workspace.slug == candidate)):
        candidate, suffix = f"{base}-{suffix}", suffix + 1
    return candidate


def _reject_invalid(report: ValidationReport) -> None:
    if not report.ok:
        raise HTTPException(
            422,
            {
                "title": "Spec could not be loaded",
                "issues": [_issue_out(i).model_dump() for i in report.issues],
            },
        )


def _store_spec(
    session: Session, workspace: Workspace, text: str, report: ValidationReport
) -> tuple[SpecVersion, bool, list[str], list[str]]:
    """Create a version unless the text is unchanged, and reconcile rules with the new routes."""
    content_hash = hashlib.sha256(text.encode()).hexdigest()
    active = session.get(SpecVersion, workspace.active_version_id) if workspace.active_version_id else None
    changed = active is None or active.content_hash != content_hash
    if changed:
        latest = session.scalar(
            select(func.max(SpecVersion.version)).where(SpecVersion.workspace_id == workspace.id)
        )
        version = SpecVersion(
            id=new_id(),
            workspace_id=workspace.id,
            version=(latest or 0) + 1,
            raw_text=text,
            content_hash=content_hash,
        )
        session.add(version)
        session.flush()
        workspace.active_version_id = version.id
    else:
        version = active

    assert report.spec is not None
    orphaned, restored = [], []
    for rule in session.scalars(select(RuleRow).where(RuleRow.workspace_id == workspace.id)):
        exists = rule.route_key in report.spec.routes
        if rule.orphaned == exists:
            rule.orphaned = not exists
            (restored if exists else orphaned).append(rule.name)
    return version, changed, orphaned, restored


def _workspace_out(session: Session, request: Request, workspace: Workspace) -> s.WorkspaceOut:
    version_number = title = None
    route_count = 0
    if workspace.active_version_id:
        version = session.get(SpecVersion, workspace.active_version_id)
        if version:
            version_number = version.version
            spec = request.app.state.runtimes.compiled(version.content_hash, version.raw_text)
            title, route_count = spec.title, len(spec.routes)
    rule_count = session.scalar(
        select(func.count()).select_from(RuleRow).where(RuleRow.workspace_id == workspace.id)
    )
    return s.WorkspaceOut(
        id=workspace.id,
        slug=workspace.slug,
        name=workspace.name,
        seed=workspace.seed,
        validation_mode=workspace.validation_mode,
        created_at=workspace.created_at,
        active_version=version_number,
        route_count=route_count,
        rule_count=rule_count or 0,
        spec_title=title,
        mock_path=f"/mock/{workspace.slug}",
    )


@router.get("/workspaces", response_model=list[s.WorkspaceOut])
def list_workspaces(request: Request, session: Session = Depends(get_session)):
    rows = session.scalars(select(Workspace).order_by(Workspace.created_at.desc())).all()
    return [_workspace_out(session, request, row) for row in rows]


@router.post("/workspaces", response_model=s.WorkspaceOut, status_code=201)
def create_workspace(
    body: s.WorkspaceCreate, request: Request, session: Session = Depends(get_session)
):
    report = None
    if body.spec_text is not None:
        report = validate_text(body.spec_text)
        _reject_invalid(report)
    # Checked up front, so a bad rule can't leave a half-built workspace behind.
    known_routes = report.spec.routes if report and report.spec else {}
    for rule in body.rules:
        if rule.route not in known_routes:
            raise HTTPException(422, f"Rule '{rule.name}': no route '{rule.route}' in the spec")
    if body.slug and session.scalar(select(Workspace.id).where(Workspace.slug == body.slug)):
        raise HTTPException(409, f"The slug '{body.slug}' is already in use")
    workspace = Workspace(
        id=new_id(),
        slug=body.slug or _unique_slug(session, _slugify(body.name)),
        name=body.name,
    )
    session.add(workspace)
    try:
        session.flush()
        if report is not None:
            _store_spec(session, workspace, body.spec_text, report)
        session.add_all(RuleRow(id=new_id(), workspace_id=workspace.id, **_rule_values(r)) for r in body.rules)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(409, "That slug was just taken; try again") from exc
    request.app.state.runtimes.invalidate(workspace.slug)
    return _workspace_out(session, request, workspace)


@router.get("/workspaces/{slug}", response_model=s.WorkspaceOut)
def get_workspace(slug: str, request: Request, session: Session = Depends(get_session)):
    return _workspace_out(session, request, _workspace(session, slug))


@router.patch("/workspaces/{slug}", response_model=s.WorkspaceOut)
def update_workspace(
    slug: str, body: s.WorkspaceUpdate, request: Request, session: Session = Depends(get_session)
):
    workspace = _workspace(session, slug)
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(workspace, key, value)
    session.commit()
    request.app.state.runtimes.invalidate(slug)
    return _workspace_out(session, request, workspace)


@router.delete("/workspaces/{slug}", status_code=204)
def delete_workspace(slug: str, request: Request, session: Session = Depends(get_session)):
    workspace = _workspace(session, slug)
    workspace_id = workspace.id
    session.delete(workspace)
    session.commit()
    request.app.state.runtimes.invalidate(slug)
    request.app.state.logs.forget(workspace_id)


@router.post("/specs/validate", response_model=s.SpecValidation)
def validate_spec(body: s.SpecText):
    report = validate_text(body.text)
    return s.SpecValidation(
        ok=report.ok,
        issues=[_issue_out(i) for i in report.issues],
        title=report.title,
        openapi_version=report.openapi_version,
        route_count=report.route_count,
    )


@router.get("/workspaces/{slug}/spec", response_model=s.SpecOut | None)
def get_spec(slug: str, session: Session = Depends(get_session)):
    workspace = _workspace(session, slug)
    if not workspace.active_version_id:
        return None
    version = session.get(SpecVersion, workspace.active_version_id)
    return s.SpecOut(version=version.version, text=version.raw_text)


@router.put("/workspaces/{slug}/spec", response_model=s.SpecSaved)
def save_spec(
    slug: str, body: s.SpecText, request: Request, session: Session = Depends(get_session)
):
    workspace = _workspace(session, slug)
    report = validate_text(body.text)
    _reject_invalid(report)
    version, changed, orphaned, restored = _store_spec(session, workspace, body.text, report)
    session.commit()
    request.app.state.runtimes.invalidate(slug)
    return s.SpecSaved(
        version=version.version,
        changed=changed,
        issues=[_issue_out(i) for i in report.issues],
        route_count=report.route_count,
        orphaned_rules=orphaned,
        restored_rules=restored,
    )


@router.get("/workspaces/{slug}/spec/versions", response_model=list[s.SpecVersionOut])
def list_spec_versions(slug: str, session: Session = Depends(get_session)):
    workspace = _workspace(session, slug)
    rows = session.scalars(
        select(SpecVersion)
        .where(SpecVersion.workspace_id == workspace.id)
        .order_by(SpecVersion.version.desc())
    )
    return [
        s.SpecVersionOut(
            version=row.version,
            content_hash=row.content_hash,
            created_at=row.created_at,
            active=row.id == workspace.active_version_id,
        )
        for row in rows
    ]


def _active_spec(session: Session, request: Request, workspace: Workspace) -> CompiledSpec | None:
    return request.app.state.runtimes.compiled_for(session, workspace)


def _summary(route: CompiledRoute, rule_counts: dict[str, int], chaos: set[str]) -> dict[str, Any]:
    return {
        "key": route.key,
        "method": route.method,
        "path": route.template,
        "summary": route.summary,
        "tag": route.tags[0] if route.tags else "default",
        "rule_count": rule_counts.get(route.key, 0),
        "has_chaos": route.key in chaos,
    }


def _route_counts(session: Session, workspace_id: str) -> tuple[dict[str, int], set[str]]:
    counts = dict(
        session.execute(
            select(RuleRow.route_key, func.count())
            .where(RuleRow.workspace_id == workspace_id)
            .group_by(RuleRow.route_key)
        ).all()
    )
    chaos = {
        key
        for key in session.scalars(
            select(ChaosRow.route_key).where(ChaosRow.workspace_id == workspace_id)
        )
        if key
    }
    return counts, chaos


@router.get("/workspaces/{slug}/routes", response_model=list[s.RouteSummary])
def list_routes(slug: str, request: Request, session: Session = Depends(get_session)):
    workspace = _workspace(session, slug)
    spec = _active_spec(session, request, workspace)
    if spec is None:
        return []
    counts, chaos = _route_counts(session, workspace.id)
    return [_summary(route, counts, chaos) for route in spec.routes.values()]


def _route_or_404(spec: CompiledSpec | None, key: str) -> CompiledRoute:
    route = spec.routes.get(key) if spec else None
    if route is None:
        raise HTTPException(404, f"No route '{key}' in the active spec")
    return route


@router.get("/workspaces/{slug}/routes/detail", response_model=s.RouteDetail)
def route_detail(
    slug: str,
    request: Request,
    key: str = Query(description="Route key, such as 'GET /users/{id}'."),
    session: Session = Depends(get_session),
):
    workspace = _workspace(session, slug)
    spec = _active_spec(session, request, workspace)
    route = _route_or_404(spec, key)
    counts, chaos = _route_counts(session, workspace.id)
    sample = None
    for media in route.body_content:
        if media.has_example:
            sample = media.example
            break
        if media.schema is not None and is_json_type(media.content_type):
            sample = sample_body(spec, media.schema, workspace.seed)
            break
    return s.RouteDetail(
        **_summary(route, counts, chaos),
        description=route.description,
        parameters=[
            s.ParameterOut(
                name=p.name,
                location=p.location,
                required=p.required,
                schema=spec.context.resolve(p.schema) if p.schema is not None else None,
            )
            for p in route.params
        ],
        body_required=route.body_required,
        body_content_types=[m.content_type for m in route.body_content],
        sample_body=sample,
        responses=[
            s.ResponseOut(
                status=r.status,
                description=r.description,
                content_types=[m.content_type for m in r.content],
            )
            for r in route.responses.values()
        ],
    )


@router.get("/workspaces/{slug}/routes/sample", response_model=s.ResponseSample)
def response_sample(
    slug: str,
    request: Request,
    key: str,
    status: str | None = None,
    session: Session = Depends(get_session),
):
    workspace = _workspace(session, slug)
    spec = _active_spec(session, request, workspace)
    route = _route_or_404(spec, key)
    code = status if status in route.responses else route.default_status()
    response = route.responses.get(code) if code else None
    media = None
    if response and response.content:
        media = next((m for m in response.content if is_json_type(m.content_type)), response.content[0])
    if media is None:
        return s.ResponseSample(status=code or "200", content_type=None)
    body = media.example if media.has_example else sample_body(spec, media.schema, workspace.seed)
    schema = None
    if isinstance(media.schema, dict):
        schema = {"components": spec.doc.get("components") or {}, "allOf": [media.schema]}
    return s.ResponseSample(status=code, content_type=media.content_type, body=body, schema=schema)


def _rule_out(row: RuleRow) -> s.RuleOut:
    return s.RuleOut(
        id=row.id,
        name=row.name,
        route=row.route_key,
        priority=row.priority,
        enabled=row.enabled,
        orphaned=row.orphaned,
        when=row.when_json,
        then=row.then_json,
    )


def _rule_values(body: s.RuleIn) -> dict[str, Any]:
    return {
        "name": body.name,
        "route_key": body.route,
        "priority": body.priority,
        "enabled": body.enabled,
        "when_json": body.when.model_dump(exclude_none=True),
        # exclude_unset keeps "no body" (generate one) distinct from "body: null".
        "then_json": body.then.model_dump(exclude_unset=True),
    }


def _route_exists(session: Session, request: Request, workspace: Workspace, key: str) -> bool:
    spec = _active_spec(session, request, workspace)
    return spec is not None and key in spec.routes


@router.get("/workspaces/{slug}/rules", response_model=list[s.RuleOut])
def list_rules(
    slug: str, route: str | None = None, session: Session = Depends(get_session)
):
    workspace = _workspace(session, slug)
    query = select(RuleRow).where(RuleRow.workspace_id == workspace.id)
    if route:
        query = query.where(RuleRow.route_key == route)
    return [
        _rule_out(row)
        for row in session.scalars(query.order_by(RuleRow.priority, RuleRow.created_at))
    ]


@router.post("/workspaces/{slug}/rules", response_model=s.RuleOut, status_code=201)
def create_rule(
    slug: str, body: s.RuleIn, request: Request, session: Session = Depends(get_session)
):
    workspace = _workspace(session, slug)
    if not _route_exists(session, request, workspace, body.route):
        raise HTTPException(422, f"No route '{body.route}' in the active spec")
    row = RuleRow(id=new_id(), workspace_id=workspace.id, **_rule_values(body))
    session.add(row)
    session.commit()
    request.app.state.runtimes.invalidate(slug)
    return _rule_out(row)


def _rule_row(session: Session, workspace: Workspace, rule_id: str) -> RuleRow:
    row = session.get(RuleRow, rule_id)
    if row is None or row.workspace_id != workspace.id:
        raise HTTPException(404, "No such rule")
    return row


@router.put("/workspaces/{slug}/rules/{rule_id}", response_model=s.RuleOut)
def update_rule(
    slug: str,
    rule_id: str,
    body: s.RuleIn,
    request: Request,
    session: Session = Depends(get_session),
):
    workspace = _workspace(session, slug)
    row = _rule_row(session, workspace, rule_id)
    exists = _route_exists(session, request, workspace, body.route)
    if not exists and body.route != row.route_key:
        raise HTTPException(422, f"No route '{body.route}' in the active spec")
    for key, value in _rule_values(body).items():
        setattr(row, key, value)
    row.orphaned = not exists
    session.commit()
    request.app.state.runtimes.invalidate(slug)
    return _rule_out(row)


@router.delete("/workspaces/{slug}/rules/{rule_id}", status_code=204)
def delete_rule(
    slug: str, rule_id: str, request: Request, session: Session = Depends(get_session)
):
    workspace = _workspace(session, slug)
    session.delete(_rule_row(session, workspace, rule_id))
    session.commit()
    request.app.state.runtimes.invalidate(slug)


def _chaos_out(row: ChaosRow) -> s.ChaosOut:
    return s.ChaosOut(
        route_key=row.route_key,
        latency_min_ms=row.latency_min_ms,
        latency_max_ms=row.latency_max_ms,
        error_rate=row.error_rate,
        forced_status=row.forced_status,
        offline=row.offline,
    )


def _chaos_row(session: Session, workspace_id: str, route_key: str | None) -> ChaosRow | None:
    query = select(ChaosRow).where(ChaosRow.workspace_id == workspace_id)
    query = (
        query.where(ChaosRow.route_key.is_(None))
        if route_key is None
        else query.where(ChaosRow.route_key == route_key)
    )
    return session.scalar(query)


@router.get("/workspaces/{slug}/chaos", response_model=list[s.ChaosOut])
def list_chaos(slug: str, session: Session = Depends(get_session)):
    workspace = _workspace(session, slug)
    rows = session.scalars(select(ChaosRow).where(ChaosRow.workspace_id == workspace.id))
    return [_chaos_out(row) for row in rows]


@router.put("/workspaces/{slug}/chaos", response_model=s.ChaosOut)
def set_chaos(
    slug: str, body: s.ChaosIn, request: Request, session: Session = Depends(get_session)
):
    workspace = _workspace(session, slug)
    if body.latency_min_ms > body.latency_max_ms > 0:
        raise HTTPException(422, "Minimum latency cannot be above the maximum")
    row = _chaos_row(session, workspace.id, body.route_key)
    if row is None:
        row = ChaosRow(id=new_id(), workspace_id=workspace.id, route_key=body.route_key)
        session.add(row)
    row.latency_min_ms = body.latency_min_ms
    row.latency_max_ms = body.latency_max_ms
    row.error_rate = body.error_rate
    row.forced_status = body.forced_status
    row.offline = body.offline
    session.commit()
    request.app.state.runtimes.invalidate(slug)
    return _chaos_out(row)


@router.delete("/workspaces/{slug}/chaos", status_code=204)
def clear_chaos(
    slug: str,
    request: Request,
    route_key: str | None = None,
    session: Session = Depends(get_session),
):
    workspace = _workspace(session, slug)
    row = _chaos_row(session, workspace.id, route_key)
    if row is not None:
        session.delete(row)
        session.commit()
    request.app.state.runtimes.invalidate(slug)


@router.get("/workspaces/{slug}/logs", response_model=list[s.LogEntry])
def list_logs(
    slug: str,
    request: Request,
    limit: int = Query(default=1000, ge=1, le=1000),
    session: Session = Depends(get_session),
):
    workspace = _workspace(session, slug)
    return [public_entry(e) for e in request.app.state.logs.recent(workspace.id, limit)]


@router.delete("/workspaces/{slug}/logs", status_code=204)
def clear_logs(slug: str, request: Request, session: Session = Depends(get_session)):
    request.app.state.logs.clear(_workspace(session, slug).id)


def _same_origin(websocket: WebSocket) -> bool:
    # Browsers apply no same-origin policy to WebSockets, so without this any web page could read
    # a local server's logs.
    origin = websocket.headers.get("origin")
    if not origin:
        return True
    return urlparse(origin).netloc == websocket.headers.get("host")


@router.websocket("/workspaces/{slug}/logs/stream")
async def stream_logs(websocket: WebSocket, slug: str):
    state = websocket.app.state
    if not _same_origin(websocket):
        await websocket.close(code=4403)
        return
    runtime = await state.runtimes.get(slug)
    if runtime is None:
        await websocket.close(code=4404)
        return
    # Subscribe before accepting. The browser treats "open" as "nothing can be missed from now on",
    # so a request sent right after it must already be on its way into this queue.
    queue = state.logs.subscribe(runtime.workspace_id)
    try:
        await websocket.accept()
    except Exception:
        state.logs.unsubscribe(runtime.workspace_id, queue)
        raise

    async def watch_disconnect() -> None:
        while True:
            await websocket.receive()

    watcher = asyncio.create_task(watch_disconnect())
    try:
        while not watcher.done():
            getter = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait({getter, watcher}, return_when=asyncio.FIRST_COMPLETED)
            if getter not in done:
                getter.cancel()
                break
            # One frame holds everything waiting. Sending rows singly needs several event-loop
            # turns per row, so under load the stream falls behind and the queue overflows.
            batch = [getter.result()]
            while len(batch) < _STREAM_BATCH and not queue.empty():
                batch.append(queue.get_nowait())
            await websocket.send_text(json.dumps([public_entry(entry) for entry in batch], default=_json_default))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        watcher.cancel()
        state.logs.unsubscribe(runtime.workspace_id, queue)
