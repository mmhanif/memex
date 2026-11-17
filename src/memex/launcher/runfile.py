"""`run.json`: how a second `memex` finds and checks the running one (SPEC §13.4)."""

import json
import os
from dataclasses import dataclass
from pathlib import Path

RUN_FILE = "run.json"


@dataclass(frozen=True)
class RunInfo:
    pid: int
    port: int
    workspace: str | None
    key: bytes  # the per-launch HMAC key

    def __repr__(self) -> str:  # never show the key
        return f"RunInfo(pid={self.pid}, port={self.port}, workspace={self.workspace!r})"


def write_run_file(home: Path, info: RunInfo) -> None:
    """Write atomically; the file is `0600` on POSIX from the moment it exists."""
    home.mkdir(parents=True, exist_ok=True)
    data = {"pid": info.pid, "port": info.port, "workspace": info.workspace, "key": info.key.hex()}
    tmp = home / f".{RUN_FILE}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, home / RUN_FILE)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def read_run_file(home: Path) -> RunInfo | None:
    """The recorded instance, or None if the file is missing or malformed."""
    try:
        data = json.loads((home / RUN_FILE).read_text("utf-8"))
        info = RunInfo(
            pid=data["pid"],
            port=data["port"],
            workspace=data["workspace"],
            key=bytes.fromhex(data["key"]),
        )
    except OSError, ValueError, KeyError, TypeError:
        return None
    valid = (
        type(info.pid) is int
        and type(info.port) is int
        and 0 < info.port < 65536
        and (info.workspace is None or isinstance(info.workspace, str))
        and len(info.key) == 32
    )
    return info if valid else None


def remove_run_file(home: Path, key: bytes) -> None:
    """Remove `run.json` only if it is still ours: a later launch may have replaced it."""
    info = read_run_file(home)
    if info is not None and info.key == key:
        (home / RUN_FILE).unlink(missing_ok=True)
