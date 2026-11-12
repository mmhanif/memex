"""The server side of the already-running hand-off (SPEC §13.4).

No cookie: both sides prove they hold the per-launch `key` from `run.json`.
The launcher checks our MAC before it trusts us; we check its MAC before
issuing a one-time code. Each `open` nonce works once.
"""

import hashlib
import hmac
from typing import Annotated

from fastapi import APIRouter, Request
from pydantic import BaseModel, StringConstraints

from memex.web.errors import error_response

router = APIRouter(prefix="/launcher")

Nonce = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32,128}$")]  # 16-64 bytes, hex


class Hello(BaseModel):
    nonce: Nonce


class Open(BaseModel):
    nonce: Nonce
    mac: Annotated[str, StringConstraints(max_length=64)]


def mac(key: bytes, label: bytes, nonce: str) -> str:
    """HMAC-SHA256(key, label ‖ nonce bytes), lowercase hex."""
    return hmac.new(key, label + bytes.fromhex(nonce), hashlib.sha256).hexdigest()


@router.post("/hello")
def hello(body: Hello, request: Request) -> dict:
    state = request.app.state.memex
    ws = state.workspace
    return {
        "mac": mac(state.launcher_key, b"server", body.nonce),
        "workspace": str(ws.root) if ws is not None else None,
    }


@router.post("/open", response_model=None)
def open_(body: Open, request: Request):
    state = request.app.state.memex
    expected = mac(state.launcher_key, b"open", body.nonce)
    if not (body.mac.isascii() and hmac.compare_digest(expected, body.mac)):
        return error_response("unauthenticated", "Launcher check failed")
    if not state.burn_open_nonce(body.nonce):
        return error_response("unauthenticated", "Launcher check failed")
    return {"code": state.session.issue_code()}
