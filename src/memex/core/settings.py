"""Settings saves (SPEC §3.6): the Workspace config, hash-checked like any write (§5.3),
and the app config (Workspace path, port), which takes effect at the next launch."""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ruamel.yaml.comments import CommentedSeq

from memex.core.config import save_app_config
from memex.core.errors import FieldProblem, UnknownReference, Validation
from memex.core.schema import EntityType
from memex.core.templates import BLANK, TEMPLATE_TYPES
from memex.core.workspace import Workspace

_TEMPLATE_TYPE_KEYS = frozenset(TEMPLATE_TYPES.values())


def save_workspace_settings(ws: Workspace, expected_hash: str, changes: Mapping[str, Any]) -> str:
    """Set Workspace config keys (`me`, `polling`, `ignore`, `hidden_templates`).

    `format` is the app's to write, and other keys aren't settings. Returns the new hash.
    """
    values = {key: _checked(ws, key, value) for key, value in changes.items()}
    return ws.save_config(expected_hash, values)


def checked_app_settings(changes: Mapping[str, Any]) -> dict[str, Any]:
    """App config keys (`workspace`, `port`), checked. Neither applies until a relaunch."""
    return {key: _checked_app(key, value) for key, value in changes.items()}


def save_app_settings(home: Path, values: Mapping[str, Any]) -> None:
    """Save values from `checked_app_settings`."""
    if values:
        save_app_config(home, **values)


def _checked_app(key: str, value: Any) -> Any:
    match key:
        case "workspace":
            path = Path(value).expanduser() if isinstance(value, str) and value.strip() else None
            if path is None or not path.is_absolute():
                raise _invalid(key, "Give the folder's full path, e.g. ~/Documents/Memex")
            return Path(os.path.normpath(path))
        case "port":
            if type(value) is not int or not 0 < value < 65536:
                raise _invalid(key, "a port is a number from 1 to 65535")
            return value
    raise _invalid(key, f"{key} isn't a setting Memex can change")


def _checked(ws: Workspace, key: str, value: Any) -> Any:
    match key:
        case "me":
            found = ws.cache.resolve(value).file if isinstance(value, str) else None
            if found is None or found.type is not EntityType.PERSON:
                raise UnknownReference("me", str(value), "a Person")
            return found.id
        case "polling":
            if not isinstance(value, bool):
                raise _invalid(key, "polling is true or false")
            return value
        case "ignore":
            return _flow(_strings(key, value))
        case "hidden_templates":
            keys = _strings(key, value)
            for item in keys:
                type_key, _, name = item.partition("/")
                if type_key not in _TEMPLATE_TYPE_KEYS or not name:
                    raise _invalid(key, f"{item!r} isn't a <type>/<name> Template key")
                if name == BLANK:
                    raise _invalid(key, "Blank can't be hidden")
            return _flow(sorted(set(keys)))
    raise _invalid(key, f"{key} isn't a setting Memex can change")


def _strings(key: str, value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise _invalid(key, f"{key} is a list of text")
    return value


def _flow(values: list[str]) -> CommentedSeq:
    seq = CommentedSeq(values)
    seq.fa.set_flow_style()
    return seq


def _invalid(key: str, message: str) -> Validation:
    return Validation(message, [FieldProblem(key, message)])
