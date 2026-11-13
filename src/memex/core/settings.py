"""Settings saves to the Workspace config (SPEC §3.6). Hash-checked like any write (§5.3)."""

from collections.abc import Mapping
from typing import Any

from ruamel.yaml.comments import CommentedSeq

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
