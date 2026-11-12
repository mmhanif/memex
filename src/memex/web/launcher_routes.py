"""The server side of the already-running hand-off (SPEC §13.4).

No cookie: both sides prove they hold the per-launch `key` from `run.json`.
The launcher checks our MAC before it trusts us; we check its MAC before
issuing a one-time code. Each `open` nonce works once.
"""

import hashlib
import hmac
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, StringConstraints

from memex.web.errors import error_response
from memex.web.state import AppState, app_state

router = APIRouter(prefix="/launcher")
State = Annotated[AppState, Depends(app_state)]

Nonce = Annotated[str, StringConstraints(pattern=r"^(?:[0-9a-f]{2}){16,64}$")]  # 16-64 bytes


class Hello(BaseModel):
    nonce: Nonce


class Open(BaseModel):
    nonce: Nonce
    mac: Annotated[str, StringConstraints(max_length=64)]


def mac(key: bytes, label: bytes, nonce: str) -> str:
    """HMAC-SHA256(key, label ‖ nonce bytes), lowercase hex."""
    return hmac.new(key, label + bytes.fromhex(nonce), hashlib.sha256).hexdigest()


@router.post("/hello")
def hello(body: Hello, state: State) -> dict:
    ws = state.workspace
    return {
        "mac": mac(state.launcher_key, b"server", body.nonce),
        "workspace": str(ws.root) if ws is not None else None,
    }


@router.post("/open", response_model=None)
def open_(body: Open, state: State):
    expected = mac(state.launcher_key, b"open", body.nonce)
    mac_ok = body.mac.isascii() and hmac.compare_digest(expected, body.mac)
    # Burn the nonce only once the MAC proves the caller holds the key.
    if not (mac_ok and state.burn_open_nonce(body.nonce)):
        return error_response("unauthenticated", "Launcher check failed")
    return {"code": state.session.issue_code()}
