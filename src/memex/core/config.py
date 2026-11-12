"""Workspace config and app config (SPEC §3.1, §3.2)."""

import io
import os
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.error import MarkedYAMLError, YAMLError

from memex.core.store import WORKSPACE_CONFIG, atomic_write


@dataclass(frozen=True)
class WorkspaceConfig:
    format: int = 1
    me: str | None = None
    polling: bool = False
    ignore: tuple[str, ...] = ()
    hidden_templates: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConfigError:
    """Why the Workspace config doesn't parse. Memex runs on defaults meanwhile (§3.5)."""

    message: str
    line: int | None  # 1-based, when known


def parse_workspace_config(text: str) -> tuple[WorkspaceConfig, ConfigError | None]:
    """Read the Workspace config leniently: a file that doesn't parse yields defaults."""
    try:
        data = _yaml().load(text) or {}
    except MarkedYAMLError as e:
        mark = e.problem_mark or e.context_mark
        return WorkspaceConfig(), ConfigError(str(e.problem or e), mark.line + 1 if mark else None)
    except YAMLError as e:
        return WorkspaceConfig(), ConfigError(str(e), None)
    if not isinstance(data, dict):
        return WorkspaceConfig(), ConfigError("config is not a mapping of keys", 1)
    return _config_from(data), None


def _config_from(data: Any) -> WorkspaceConfig:
    """Each key with the wrong type falls back to its default; nothing is fixed on disk."""
    default = WorkspaceConfig()
    format_ = data.get("format")
    me = data.get("me")
    polling = data.get("polling")
    return WorkspaceConfig(
        format=format_ if type(format_) is int else default.format,
        me=me if isinstance(me, str) and me else None,
        polling=polling if isinstance(polling, bool) else default.polling,
        ignore=_strings(data.get("ignore")),
        hidden_templates=_strings(data.get("hidden_templates")),
    )


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(v for v in value if isinstance(v, str))


def with_keys(text: str, set: Mapping[str, Any] | None = None, unset: Iterable[str] = ()) -> str:
    """Return the config `text` with keys set or removed, keeping comments and unknown keys.

    Raises ConfigUnparseable if `text` isn't a YAML mapping.
    """
    _, error = parse_workspace_config(text)
    if error is not None:
        raise ConfigUnparseable(error)
    data = _yaml().load(text) or CommentedMap()
    for key, value in (set or {}).items():
        data[key] = value
    for key in unset:
        data.pop(key, None)
    out = io.StringIO()
    _yaml().dump(data, out)
    return out.getvalue()


class ConfigUnparseable(Exception):
    def __init__(self, error: ConfigError) -> None:
        super().__init__(error.message)
        self.error = error


def _yaml() -> YAML:
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.width = 4096
    return yaml


# App config (§3.1): outside the Workspace, in the per-user Memex folder.


def memex_home() -> Path:
    """The per-user Memex folder. `MEMEX_HOME` overrides it (for tests)."""
    if override := os.environ.get("MEMEX_HOME"):
        return Path(override)
    if sys.platform == "win32":
        return Path(os.environ["LOCALAPPDATA"]) / "Memex"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Memex"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "Memex"


APP_CONFIG = "config.yaml"
DEFAULT_PORT = 47615


@dataclass(frozen=True)
class AppConfig:
    workspace: Path | None = None
    port: int = DEFAULT_PORT


def load_app_config(home: Path) -> AppConfig:
    """Read leniently: a missing or broken file, or a wrongly typed key, gives defaults."""
    data = _load_mapping(home / APP_CONFIG)
    workspace, port = data.get("workspace"), data.get("port")
    return AppConfig(
        workspace=Path(workspace) if isinstance(workspace, str) and workspace else None,
        port=port if type(port) is int else DEFAULT_PORT,
    )


def save_app_config(home: Path, **keys: Any) -> None:
    """Set keys, keeping comments and unknown keys. Paths are stored as strings."""
    path = home / APP_CONFIG
    try:
        text = path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        text = ""
    try:
        new = with_keys(text, {k: str(v) if isinstance(v, Path) else v for k, v in keys.items()})
    except ConfigUnparseable:
        new = with_keys("", keys)  # never block a launch on a broken app config
    home.mkdir(parents=True, exist_ok=True)
    atomic_write(path, new.encode("utf-8"), APP_CONFIG)


def _load_mapping(path: Path) -> dict[str, Any]:
    try:
        data = _yaml().load(path.read_bytes().decode("utf-8"))
    except OSError, UnicodeDecodeError, YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


@dataclass(frozen=True)
class Location:
    """Where the Workspace is (§3.3). Not `ready`: Setup, pre-filled with `path` if any."""

    path: Path | None
    ready: bool


def locate_workspace(cli_path: Path | None, home: Path) -> Location:
    """`--workspace` (remembered in app config), else the remembered path."""
    if cli_path is not None:
        path = Path(os.path.abspath(cli_path.expanduser()))
        if load_app_config(home).workspace != path:
            save_app_config(home, workspace=path)
    elif (path := load_app_config(home).workspace) is None:
        return Location(path=None, ready=False)
    return Location(path=path, ready=(path / WORKSPACE_CONFIG).is_file())
