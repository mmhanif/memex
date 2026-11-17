"""The client side of the already-running hand-off (SPEC §13.4).

Only a nonce is sent until the listener proves it holds the key in `run.json`;
an unverified listener never gets a code or the key.
"""

import hmac
import http.client
import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from memex.launcher.net import HOST
from memex.launcher.runfile import RunInfo
from memex.web.launcher_routes import mac

TIMEOUT = 3.0  # seconds; a listener this slow is treated as a stranger


@dataclass(frozen=True)
class Running:
    """A verified Memex on `port`, serving `workspace` (None while it waits for Setup)."""

    port: int
    workspace: str | None


def verify(info: RunInfo) -> Running | None:
    """Challenge the listener on `info.port`. None unless it proves it holds `info.key`."""
    nonce = secrets.token_hex(32)
    reply = _post(info.port, "/launcher/hello", {"nonce": nonce})
    if not isinstance(reply, dict):
        return None
    their_mac, workspace = reply.get("mac"), reply.get("workspace")
    if not (isinstance(their_mac, str) and their_mac.isascii()):
        return None
    if not hmac.compare_digest(their_mac, mac(info.key, b"server", nonce)):
        return None
    if workspace is not None and not isinstance(workspace, str):
        return None
    return Running(port=info.port, workspace=workspace)


def request_code(info: RunInfo) -> str | None:
    """A fresh one-time code from a verified instance."""
    nonce = secrets.token_hex(32)
    reply = _post(
        info.port, "/launcher/open", {"nonce": nonce, "mac": mac(info.key, b"open", nonce)}
    )
    code = reply.get("code") if isinstance(reply, dict) else None
    return code if isinstance(code, str) and code.isascii() and code.isprintable() else None


def same_workspace(a: str | Path, b: str | Path) -> bool:
    """Compared as §13.4 says: `normcase(realpath)`."""
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def _post(port: int, path: str, body: dict) -> object:
    conn = http.client.HTTPConnection(HOST, port, timeout=TIMEOUT)
    try:
        conn.request("POST", path, json.dumps(body), {"Content-Type": "application/json"})
        response = conn.getresponse()
        data = response.read(64 * 1024)
        if response.status != 200:
            return None
        return json.loads(data)
    except OSError, http.client.HTTPException, ValueError:
        return None
    finally:
        conn.close()
