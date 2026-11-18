"""Settings routes (SPEC §3.6, §17.2): the Workspace config, hash-checked.

The app-config half (Workspace path, port) arrives with the rest of the Settings page.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Header, Response
from pydantic import BaseModel, Field

from memex import version
from memex.core.settings import save_workspace_settings
from memex.web.api import WS, expected_hash

router = APIRouter(prefix="/api")


class SettingsChanges(BaseModel):
    workspace: dict[str, Any] = Field(default_factory=dict)


@router.get("/settings")
def read_settings(ws: WS, response: Response) -> dict:
    config_hash = ws.config_hash()
    response.headers["ETag"] = f'"{config_hash}"'
    config = ws.config
    return {
        "hash": config_hash,
        "workspace": {
            "me": config.me,
            "polling": config.polling,
            "ignore": list(config.ignore),
            "hidden_templates": list(config.hidden_templates),
        },
        "config_error": ws.config_error and ws.config_error.message,
        "read_only": ws.read_only or ws.config_error is not None,
        "version": version(),
    }


@router.put("/settings")
def save_settings(
    ws: WS,
    body: SettingsChanges,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> dict:
    new_hash = save_workspace_settings(ws, expected_hash(if_match), body.workspace)
    response.headers["ETag"] = f'"{new_hash}"'
    return {"hash": new_hash}
