"""The catch-all route that serves every mock. Routes are matched per request, not registered."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request, Response
from mockforge_engine import RawRequest
from mockforge_engine.limits import MAX_REQUEST_BYTES
from starlette.convertors import PathConvertor, register_url_convertor

router = APIRouter()


class _AnyPath(PathConvertor):
    """Starlette's `path` is `.*`, which can't cross a newline. A request for a URL containing %0A
    would miss the mock altogether, and get no log entry and no CORS headers."""

    regex = "(?s:.*)"


register_url_convertor("mockpath", _AnyPath())

_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD", "TRACE"]
_REDACTED_HEADERS = {"authorization", "proxy-authorization", "cookie", "x-api-key"}
_LOGGED_BODY_BYTES = 64 * 1024
_EXPOSED = "x-mockforge-rule, x-mockforge-source, x-mockforge-request-id"


class _RateLimiter:
    """Fixed one-minute window per workspace. Only used on the public demo."""

    def __init__(self) -> None:
        self.windows: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))

    def allow(self, slug: str, limit: int) -> bool:
        minute = int(time.monotonic() // 60)
        window, count = self.windows[slug]
        count = count + 1 if window == minute else 1
        self.windows[slug] = (minute, count)
        return count <= limit


_limiter = _RateLimiter()


def _problem(status: int, title: str, detail: str) -> Response:
    body = {"type": "about:blank", "title": title, "status": status, "detail": detail}
    return Response(json.dumps(body), status, media_type="application/problem+json")


def _cors(request: Request) -> dict[str, str]:
    # Apps under test run on their own origin, and mocks hold nothing worth protecting.
    origin = request.headers.get("origin")
    if not origin:
        return {"access-control-allow-origin": "*", "access-control-expose-headers": _EXPOSED}
    return {
        "access-control-allow-origin": origin,
        "access-control-allow-credentials": "true",
        "access-control-expose-headers": _EXPOSED,
        "vary": "Origin",
    }


async def _read_body(request: Request) -> bytes | None:
    """The body, or None if it is over the limit. Content-Length alone can lie."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_REQUEST_BYTES:
        return None
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_REQUEST_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _log_body(body: bytes, content_type: str) -> str | None:
    if not body:
        return None
    text = body[:_LOGGED_BODY_BYTES].decode("utf-8", "replace")
    if len(body) > _LOGGED_BODY_BYTES:
        return text + f"\n… truncated, {len(body)} bytes in total"
    return text


def _log_headers(headers: dict[str, str]) -> dict[str, str]:
    # Front-ends often send real tokens to a mock by accident; never write those to the database.
    return {k: ("[redacted]" if k in _REDACTED_HEADERS else v) for k, v in headers.items()}


def _entry(
    workspace_id: str,
    raw: RawRequest,
    query_string: str,
    result: Any,
    duration_ms: float,
    overhead_ms: float,
    status: int,
) -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex,
        "workspace_id": workspace_id,
        "ts": datetime.now(UTC),
        "method": raw.method,
        "path": raw.path + (f"?{query_string}" if query_string else ""),
        "status": status,
        "route_key": result.route_key,
        "rule_id": result.rule_id,
        "rule_name": result.rule_name,
        "source": result.source,
        "chaos": result.chaos,
        "duration_ms": round(duration_ms, 2),
        "overhead_ms": round(overhead_ms, 3),
        "request": {
            "headers": _log_headers(raw.headers),
            "query": raw.query,
            "body": _log_body(raw.body, raw.headers.get("content-type", "")),
        },
        "response": {
            "headers": result.headers,
            "body": _log_body(result.body, result.headers.get("content-type", "")),
            "notes": result.notes,
        },
    }


@router.api_route("/mock/{workspace}", methods=_METHODS, include_in_schema=False)
@router.api_route("/mock/{workspace}/{path:mockpath}", methods=_METHODS, include_in_schema=False)
async def serve_mock(request: Request, workspace: str, path: str = "") -> Response:
    started = time.perf_counter()
    state = request.app.state
    cors = _cors(request)

    if (
        state.settings.rate_limit_per_minute > 0
        and not _limiter.allow(workspace, state.settings.rate_limit_per_minute)
    ):
        response = _problem(429, "Too many requests", "This workspace is over its rate limit.")
        response.headers.update(cors)
        return response

    runtime = await state.runtimes.get(workspace)
    if runtime is None:
        response = _problem(404, "No such workspace", f"Workspace '{workspace}' does not exist.")
        response.headers.update(cors)
        return response

    full_path = "/" + path
    is_preflight = (
        request.method == "OPTIONS"
        and "access-control-request-method" in request.headers
    )
    if is_preflight:
        response = Response(status_code=204)
        response.headers.update(cors)
        response.headers["access-control-allow-methods"] = ", ".join(_METHODS)
        requested = request.headers.get("access-control-request-headers")
        if requested:
            response.headers["access-control-allow-headers"] = requested
        response.headers["access-control-max-age"] = "600"
        return response

    body = await _read_body(request)
    if body is None:
        response = _problem(413, "Body too large", "Request bodies are limited to 5 MB.")
        response.headers.update(cors)
        return response

    raw = RawRequest(
        method=request.method,
        path=full_path,
        query=list(request.query_params.multi_items()),
        headers={k.lower(): v for k, v in request.headers.items()},
        cookies=dict(request.cookies),
        body=body,
    )
    result = runtime.engine.handle(raw)
    overhead_ms = (time.perf_counter() - started) * 1000

    if result.delay_ms > 0:
        await asyncio.sleep(result.delay_ms / 1000)

    duration_ms = (time.perf_counter() - started) * 1000
    query_string = request.url.query
    if result.drop_connection:
        state.logs.record(
            _entry(runtime.workspace_id, raw, query_string, result, duration_ms, overhead_ms, 0)
        )
        abort = request.scope.get("mockforge.abort")
        if abort is not None and abort():
            return Response(status_code=503)
        # Not running under a server whose socket we can reach: the closest thing to offline.
        response = _problem(503, "Offline", "Chaos 'offline' is on for this route.")
        response.headers["connection"] = "close"
        response.headers.update(cors)
        return response

    entry = _entry(
        runtime.workspace_id, raw, query_string, result, duration_ms, overhead_ms, result.status
    )
    state.logs.record(entry)

    response = Response(content=b"" if request.method == "HEAD" else result.body, status_code=result.status)
    for name, value in result.headers.items():
        response.headers[name] = value
    response.headers.update(cors)
    response.headers["x-mockforge-request-id"] = entry["id"]
    response.headers["x-mockforge-source"] = result.source
    if result.rule_name:
        # Header values are latin-1 on the wire; a rule name may not be.
        response.headers["x-mockforge-rule"] = result.rule_name.encode("ascii", "replace").decode()
    return response
