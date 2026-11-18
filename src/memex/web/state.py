"""What one running server holds, and where its static files live."""

import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from fastapi import Request

from memex.core.clock import Clock, SystemClock
from memex.core.config import AppConfig, Location, load_app_config
from memex.core.watch import ChangeFeed
from memex.core.workspace import Workspace
from memex.web.session import Session

STATIC = Path(str(resources.files("memex").joinpath("static")))


@dataclass
class AppState:
    """The Workspace is None until Setup is done. Secrets stay out of `repr` (R7)."""

    port: int
    home: Path
    workspace: Workspace | None = None
    setup_path: Path | None = None  # Setup's pre-filled path (§3.3)
    clock: Clock = field(default_factory=SystemClock)
    install_dir: Path | None = None
    # The app config as this run read it: Settings shows edits since as "relaunch needed".
    launch_app_config: AppConfig = field(default_factory=AppConfig)
    feed: ChangeFeed = field(default_factory=ChangeFeed, repr=False)
    session: Session = field(default_factory=Session, repr=False)
    launcher_key: bytes = field(default_factory=lambda: secrets.token_bytes(32), repr=False)
    on_quit: Callable[[], None] = field(default=lambda: None, repr=False)
    _open_nonces: set[str] = field(default_factory=set, repr=False)
    _open_nonces_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def burn_open_nonce(self, nonce: str) -> bool:
        """True the first time a `/launcher/open` nonce is seen (§13.4)."""
        with self._open_nonces_lock:
            if nonce in self._open_nonces:
                return False
            self._open_nonces.add(nonce)
            return True

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
        clock = clock or SystemClock()
        workspace = None
        if location.ready and location.path is not None:
            workspace = Workspace.open(location.path, clock)
        return cls(
            port=port,
            home=home,
            workspace=workspace,
            setup_path=None if workspace else location.path,
            clock=clock,
            install_dir=install_dir,
            launch_app_config=load_app_config(home),
        )

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
        return cls.from_location(
            Location(path=root, ready=True),
            port=port,
            home=home,
            clock=clock,
            install_dir=install_dir,
        )


def app_state(request: Request) -> AppState:
    """FastAPI dependency: this server's AppState."""
    return request.app.state.memex
