from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from .db import build_engine, run_migrations, session_factory
from .logstore import LogHub
from .routers import management, mock
from .runtime import RuntimeManager
from .settings import Settings

logger = logging.getLogger("mockloom")


class _AbortableConnections:
    """Lets a handler really drop its connection for chaos 'offline'. ASGI has no call for this.

    It must sit outside FastAPI, which wraps `send`. uvicorn's own send is a bound method of the
    object that holds the socket transport. If that is not what we find (another server, or tests)
    abort() returns False and the handler falls back to a 503.
    """

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "http":

            def abort() -> bool:
                transport = getattr(getattr(send, "__self__", None), "transport", None)
                if transport is None or not hasattr(transport, "abort"):
                    return False
                transport.abort()
                return True

            scope["mockloom.abort"] = abort
        await self.app(scope, receive, send)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.logs.start()
        yield
        await app.state.logs.stop()
        engine.dispose()

    run_migrations(settings.database_url)
    engine = build_engine(settings.database_url)
    sessions = session_factory(engine)

    app = FastAPI(
        title="MockLoom",
        version="0.1.0",
        summary="Management API for MockLoom workspaces.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.sessions = sessions
    app.state.runtimes = RuntimeManager(sessions)
    app.state.logs = LogHub(sessions, settings)
    app.include_router(management.router)
    app.include_router(mock.router)
    _serve_frontend(app, settings.web_dist)
    # Not add_middleware: that lands inside Starlette's error handler, which rewraps `send`.
    build_stack = app.build_middleware_stack
    app.build_middleware_stack = lambda: _AbortableConnections(build_stack())
    return app


def _serve_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the built React app, when there is one, with a fallback for client-side routes."""
    root = dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str, request: Request):
        if path.startswith(("api/", "mock/")):
            raise HTTPException(404, "Not found")
        index = root / "index.html"
        if not index.exists():
            return JSONResponse(
                {"detail": "Frontend not built. Run `npm run build` in apps/web, or use the Vite dev server."},
                status_code=404,
            )
        target = (root / path).resolve()
        if path and target.is_file() and target.is_relative_to(root):
            return FileResponse(target)
        return FileResponse(index)
