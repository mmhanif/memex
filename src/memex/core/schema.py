"""Entity types, their fields, and field-level validation (SPEC §2, §4.3, §4.5).

Checks here look at one file's fields alone. Whether a reference names an existing
Entity of the right type needs the whole Workspace, so that lives in `entities`.
"""

import datetime as dt
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from memex.core.errors import FieldProblem


class EntityType(StrEnum):
    THEME = "theme"
    PROJECT = "project"
    DELIVERABLE = "deliverable"
    PERSON = "person"
    TODO = "todo"
    GLOSSARY_TERM = "glossary-term"

    @property
    def folder(self) -> str:
        return _FOLDERS[self]

    @property
    def label(self) -> str:
        return _LABELS[self]

    @classmethod
    def for_folder(cls, folder: str) -> EntityType | None:
        return _BY_FOLDER.get(folder)


_FOLDERS = {
    EntityType.THEME: "themes",
    EntityType.PROJECT: "projects",
    EntityType.DELIVERABLE: "deliverables",
    EntityType.PERSON: "people",
    EntityType.TODO: "todos",
    EntityType.GLOSSARY_TERM: "glossary",
}
_BY_FOLDER = {folder: t for t, folder in _FOLDERS.items()}
_LABELS = {
    EntityType.THEME: "Theme",
    EntityType.PROJECT: "Project",
    EntityType.DELIVERABLE: "Deliverable",
    EntityType.PERSON: "Person",
    EntityType.TODO: "To-do",
    EntityType.GLOSSARY_TERM: "Glossary Term",
}

WORK_STATUSES = ("not-started", "active", "on-hold", "blocked", "done", "cancelled")
TODO_STATUSES = ("open", "done", "cancelled")
FINISHED_TODO = ("done", "cancelled")
KINDS = ("team-member", "stakeholder")
WORK = (EntityType.THEME, EntityType.PROJECT, EntityType.DELIVERABLE)

# What a reference may point at: an Entity type, or None for a Note.
Target = EntityType | None

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class Field:
    name: str
    shape: Literal["text", "date", "enum", "ref", "refs", "texts"]
    required: bool = False
    allowed: tuple[str, ...] = ()  # enum values; for `texts`, a non-empty list of these
    targets: tuple[Target, ...] = ()  # for `ref`/`refs`
    default: str | None = None  # filled in at creation when missing
    automatic: bool = False  # set by the app only (`created`, `completed`)


def _person(name: str, required: bool = False) -> Field:
    return Field(name, "ref", required, targets=(EntityType.PERSON,))


def _people(name: str) -> Field:
    return Field(name, "refs", targets=(EntityType.PERSON,))


_TITLE = Field("title", "text", required=True)
_CREATED = Field("created", "date", automatic=True)
_LABELS_FIELD = Field("labels", "texts")
_TAGS = (_person("lead"), _people("team"), _people("stakeholders"))
_DATES = (Field("start", "date"), Field("due", "date"))
_ARCHIVED = Field("archived", "date")

FIELDS: dict[EntityType | None, tuple[Field, ...]] = {
    EntityType.THEME: (_TITLE, *_TAGS, _LABELS_FIELD, _ARCHIVED, _CREATED),
    EntityType.PROJECT: (
        _TITLE,
        Field("theme", "ref", targets=(EntityType.THEME,)),
        Field("status", "enum", True, WORK_STATUSES, default="not-started"),
        *_TAGS,
        *_DATES,
        _LABELS_FIELD,
        _CREATED,
    ),
    EntityType.DELIVERABLE: (
        _TITLE,
        Field("project", "ref", True, targets=(EntityType.PROJECT,)),
        Field("status", "enum", True, WORK_STATUSES, default="not-started"),
        *_TAGS,
        *_DATES,
        _LABELS_FIELD,
        _CREATED,
    ),
    EntityType.PERSON: (
        _TITLE,
        Field("kind", "texts", True, KINDS),
        _person("manager"),
        Field("role", "text"),
        Field("organisation", "text"),
        Field("email", "text"),
        _ARCHIVED,
        _CREATED,
    ),
    EntityType.TODO: (
        _TITLE,
        _person("owner", required=True),
        _person("requester", required=True),
        Field("status", "enum", True, TODO_STATUSES, default="open"),
        Field("due", "date"),
        Field("completed", "date", automatic=True),
        Field("about", "ref", targets=WORK),
        Field("source", "ref", targets=(None,)),
        _CREATED,
    ),
    None: (  # a Note
        Field("title", "text"),
        Field("date", "date"),
        _people("people"),
        Field("about", "refs", targets=WORK),
        _LABELS_FIELD,
        _CREATED,
    ),
    EntityType.GLOSSARY_TERM: (_TITLE, Field("aliases", "texts"), _LABELS_FIELD, _CREATED),
}
FIELD_BY_NAME = {t: {f.name: f for f in fields} for t, fields in FIELDS.items()}

# Frontmatter fields that hold Ids, by type; None is a Note (§4.3, §4.5).
REFERENCE_FIELDS: dict[EntityType | None, tuple[str, ...]] = {
    t: tuple(f.name for f in fields if f.shape in ("ref", "refs")) for t, fields in FIELDS.items()
}

# Fields a Template never supplies (§7.2): the app or the caller sets them.
NOT_FROM_TEMPLATES: dict[EntityType | None, frozenset[str]] = {
    t: frozenset({"title", "created", "completed"})
    | {f.name for f in fields if f.required and f.shape == "ref"}
    for t, fields in FIELDS.items()
}


def check_fields(entity_type: EntityType | None, fields: Mapping[str, Any]) -> list[FieldProblem]:
    """Problems with one file's known fields, judged alone. Unknown fields are fine."""
    errors: list[FieldProblem] = []
    for spec in FIELDS[entity_type]:
        value = fields.get(spec.name)
        if _missing(value):
            if spec.required:
                errors.append(FieldProblem(spec.name, f"{spec.name} is required"))
            continue
        if problem := check_value(spec, value):
            errors.append(problem)
    return errors


def check_value(spec: Field, value: Any) -> FieldProblem | None:
    """One present value against its field's shape; None when it is fine."""
    name = spec.name
    match spec.shape:
        case "text":
            if not isinstance(value, str | int | float) or isinstance(value, bool):
                return FieldProblem(name, f"{name} must be text")
        case "date":
            if parse_date(value) is None:
                return FieldProblem(name, f"{name} must be a date written YYYY-MM-DD")
        case "enum":
            if value not in spec.allowed:
                return _not_allowed(spec, value)
        case "ref":
            if not _is_id(value):
                return FieldProblem(name, f"{name} must be one Id")
        case "refs":
            if not isinstance(value, list) or not all(_is_id(v) for v in value):
                return FieldProblem(name, f"{name} must be a list of Ids")
        case "texts":
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                return FieldProblem(name, f"{name} must be a list of text")
            if spec.allowed:
                if not value:
                    return FieldProblem(name, f"{name} needs at least one value", spec.allowed)
                if bad := [v for v in value if v not in spec.allowed]:
                    return _not_allowed(spec, bad[0])
    return None


def _not_allowed(spec: Field, value: Any) -> FieldProblem:
    allowed = ", ".join(spec.allowed)
    return FieldProblem(spec.name, f"{spec.name}: {value!r} isn't one of {allowed}", spec.allowed)


def parse_date(value: Any) -> dt.date | None:
    """A real `YYYY-MM-DD` date, from YAML's date or a string; else None."""
    if isinstance(value, dt.datetime):
        return None
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str) and _DATE.match(value):
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _is_id(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())
