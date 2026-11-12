"""First-run Setup (SPEC §3.4) and Quit (§13.3)."""

import threading
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Request
from pydantic import BaseModel, StringConstraints, model_validator

from memex.core.config import save_app_config
from memex.core.errors import Validation
from memex.core.workspace import NewMe, apply_setup, scan_setup

router = APIRouter(prefix="/api")

DEFAULT_SETUP_PATH = Path("~/Documents/Memex")
_setup_lock = threading.Lock()


class SetupPath(BaseModel):
    path: str


class Me(BaseModel):
    """Exactly one of: `name` for a new Person, or the `id` of an existing one."""

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None = None
    id: Annotated[str, StringConstraints(min_length=1)] | None = None

    @model_validator(mode="after")
    def _one_of(self) -> Me:
        if (self.name is None) == (self.id is None):
            raise ValueError("give either a name or an id")
        return self


class ApplySetup(SetupPath):
    me: Me


@router.get("/setup")
def setup_status(request: Request) -> dict:
    state = request.app.state.memex
    if state.workspace is not None:
        return {"needed": False}
    return {"needed": True, "path": str((state.setup_path or DEFAULT_SETUP_PATH).expanduser())}


@router.post("/setup/scan")
def scan(body: SetupPath, request: Request) -> dict:
    state = request.app.state.memex
    _require_setup_needed(state)
    result = scan_setup(_absolute(body.path), install_dir=state.install_dir)
    return {
        "summary": result.summary,
        "notes": result.notes,
        "persons": [{"id": p.id, "title": p.title} for p in result.persons],
    }


@router.post("/setup/apply")
def apply(body: ApplySetup, request: Request) -> dict:
    state = request.app.state.memex
    with _setup_lock:
        _require_setup_needed(state)
        root = _absolute(body.path)
        me = NewMe(body.me.name) if body.me.name is not None else body.me.id
        assert me is not None
        workspace = apply_setup(root, me, clock=state.clock, install_dir=state.install_dir)
        save_app_config(state.home, workspace=root)
        state.workspace = workspace
    return {"me": workspace.config.me}


@router.post("/quit", status_code=202)
def quit_(request: Request) -> dict:
    request.app.state.memex.on_quit()
    return {}


def _require_setup_needed(state) -> None:
    if state.workspace is not None:
        raise Validation("Setup is already done: change the Workspace in Settings")


def _absolute(path: str) -> Path:
    expanded = Path(path).expanduser()
    if not expanded.is_absolute():
        raise Validation("Give the folder's full path, e.g. ~/Documents/Memex")
    return expanded
