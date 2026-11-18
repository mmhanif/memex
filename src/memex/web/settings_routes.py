"""Settings routes (SPEC §3.6, §17.2): the Workspace config, hash-checked, and the app
config (Workspace path, port). Polling and the app config take effect after a relaunch."""

import os
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel, Field

from memex import version
from memex.core.config import load_app_config
from memex.core.settings import checked_app_settings, save_app_settings, save_workspace_settings
from memex.launcher.logs import LOG_FILE
from memex.launcher.net import HOST
from memex.web.api import WS, expected_hash
from memex.web.state import AppState, app_state

router = APIRouter(prefix="/api")
State = Annotated[AppState, Depends(app_state)]


class SettingsChanges(BaseModel):
    workspace: dict[str, Any] = Field(default_factory=dict)
    app: dict[str, Any] = Field(default_factory=dict)


@router.get("/settings")
def read_settings(ws: WS, state: State, response: Response) -> dict:
    config_hash = ws.config_hash()
    response.headers["ETag"] = f'"{config_hash}"'
    config = ws.config
    app = load_app_config(state.home)
    workspace_path = app.workspace or ws.root
    relaunch = [
        key
        for key, pending in (
            ("polling", config.polling != ws.launch_polling),
            ("workspace", not _same_path(workspace_path, ws.root)),
            ("port", app.port != state.launch_app_config.port),
        )
        if pending
    ]
    return {
        "hash": config_hash,
        "workspace": {
            "me": config.me,
            "polling": config.polling,
            "ignore": list(config.ignore),
            "hidden_templates": list(config.hidden_templates),
        },
        "app": {"workspace": str(workspace_path), "port": app.port},
        # What this run uses; `relaunch` names the settings saved since that wait for a relaunch.
        "running": {
            "workspace": str(ws.root),
            "port": state.launch_app_config.port,
            "polling": ws.launch_polling,
        },
        "relaunch": relaunch,
        "config_error": ws.config_error and ws.config_error.message,
        "read_only": ws.read_only or ws.config_error is not None,
        "version": version(),
        "about": {
            "version": version(),
            "format": config.format,
            "address": f"{HOST}:{state.port}",
            "logs": str(state.home / LOG_FILE.parent),
        },
    }


@router.put("/settings")
def save_settings(
    ws: WS,
    state: State,
    body: SettingsChanges,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> dict:
    app = checked_app_settings(body.app)  # check both halves before writing either
    if body.workspace:
        new_hash = save_workspace_settings(ws, expected_hash(if_match), body.workspace)
    else:
        new_hash = ws.config_hash()
    save_app_settings(state.home, app)
    response.headers["ETag"] = f'"{new_hash}"'
    return {"hash": new_hash}


def _same_path(a: Path, b: Path) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))
