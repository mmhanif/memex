"""The FastAPI app (SPEC §11.1, §12, §17)."""

import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from memex.core.clock import Clock, SystemClock
from memex.core.config import Location
from memex.core.workspace import Workspace
from memex.web import api, errors, launcher_routes, setup_routes
from memex.web.security import SecurityMiddleware
from memex.web.session import COOKIE, Session

STATIC = Path(str(resources.files("memex").joinpath("static")))


@dataclass
class AppState:
    """Everything one running server holds. The Workspace is None until Setup is done."""

    port: int
    home: Path
    workspace: Workspace | None = None
    setup_path: Path | None = None  # Setup's pre-filled path (§3.3)
    clock: Clock = field(default_factory=SystemClock)
    install_dir: Path | None = None
    session: Session = field(default_factory=Session)
    launcher_key: bytes = field(default_factory=lambda: secrets.token_bytes(32))
    on_quit: Callable[[], None] = lambda: None
    _open_nonces: set[str] = field(default_factory=set)
    _open_nonces_lock: threading.Lock = field(default_factory=threading.Lock)

    def burn_open_nonce(self, nonce: str) -> bool:
        """True the first time a `/launcher/open` nonce is seen (§13.4)."""
        with self._open_nonces_lock:
            if nonce in self._open_nonces:
                return False
            self._open_nonces.add(nonce)
            return True

    @classmethod
    def for_workspace(
        cls,
        root: Path,
        *,
        port: int,
        home: Path,
        clock: Clock | None = None,
        install_dir: Path | None = None,
    ) -> AppState:
        clock = clock or SystemClock()
        return cls(
            port=port,
            home=home,
            workspace=Workspace.open(root, clock),
            clock=clock,
            install_dir=install_dir,
        )

    @classmethod
    def from_location(
        cls,
        location: Location,
        *,
        port: int,
        home: Path,
        clock: Clock | None = None,
        install_dir: Path | None = None,
    ) -> AppState:
        """Open the located Workspace, or wait for Setup pre-filled with its path (§3.3)."""
        if location.ready and location.path is not None:
            return cls.for_workspace(
                location.path, port=port, home=home, clock=clock, install_dir=install_dir
            )
        return cls(
            port=port,
            home=home,
            setup_path=location.path,
            clock=clock or SystemClock(),
            install_dir=install_dir,
        )


def create_app(state: AppState) -> FastAPI:
    app = FastAPI(
        telemetry={"tracing": False, "metrics": False, "logs": False},
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.memex = state
    errors.install(app)
    app.include_router(api.router)
    app.include_router(launcher_routes.router)
    app.include_router(setup_routes.router)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

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
        return FileResponse(STATIC / "relaunch.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    app.add_middleware(SecurityMiddleware, state=state)
    return app
