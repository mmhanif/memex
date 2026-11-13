"""The FastAPI app (SPEC §11.1, §12, §17)."""

import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from os import PathLike
from pathlib import PurePath
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from memex.web import (
    api,
    entities_routes,
    errors,
    events,
    launcher_routes,
    settings_routes,
    setup_routes,
)
from memex.web.security import SecurityMiddleware
from memex.web.session import COOKIE
from memex.web.state import STATIC, AppState

__all__ = ["AppState", "create_app"]

log = logging.getLogger(__name__)


def create_app(state: AppState, *, watch: bool = True) -> FastAPI:
    """`watch=False` leaves the Workspace unwatched, for tests that hint changes themselves."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        stop = threading.Event()
        watcher = threading.Thread(target=_watch, args=(state, stop), name="memex-watch")
        if watch:
            watcher.start()
        try:
            yield
        finally:
            stop.set()
            if watch:
                watcher.join(timeout=10)

    app = FastAPI(
        lifespan=lifespan,
        telemetry={"tracing": False, "metrics": False, "logs": False},
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.memex = state
    errors.install(app)
    app.include_router(api.router)
    app.include_router(entities_routes.router)
    app.include_router(settings_routes.router)
    app.include_router(events.router)
    app.include_router(launcher_routes.router)
    app.include_router(setup_routes.router)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html", media_type="text/html")

    @app.get("/auth", include_in_schema=False)
    def auth(request: Request) -> Response:
        """Exchange the launcher's one-time code for the session cookie (R6)."""
        code = request.query_params.get("code", "")
        if not code or not state.session.redeem(code):
            return errors.error_response("unauthenticated", "That link has been used")
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            COOKIE, state.session.secret, httponly=True, samesite="strict", path="/"
        )
        return response

    @app.get("/relaunch", include_in_schema=False)
    def relaunch() -> FileResponse:
        return FileResponse(STATIC / "relaunch.html", media_type="text/html")

    app.mount("/static", AppStaticFiles(directory=STATIC), name="static")
    app.add_middleware(SecurityMiddleware, state=state)
    return app


# Our own table, not `mimetypes`: on Windows that reads the registry, which can map .js to
# text/plain, and Chrome refuses a module script of that type under nosniff.
STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
}


class AppStaticFiles(StaticFiles):
    def file_response(self, full_path: PathLike[str] | str, *args: Any, **kwargs: Any) -> Response:
        response = super().file_response(full_path, *args, **kwargs)
        if media_type := STATIC_TYPES.get(PurePath(full_path).suffix.lower()):
            response.headers["content-type"] = media_type
        return response


def _watch(state: AppState, stop: threading.Event) -> None:
    """Watch the Workspace, waiting for Setup to open one (§5.6)."""
    while not stop.is_set():
        if state.workspace is None:
            stop.wait(0.5)
            continue
        try:
            state.feed.run(state.workspace, stop)
        except Exception:
            log.exception("The watcher stopped; restarting it")
            stop.wait(1)
