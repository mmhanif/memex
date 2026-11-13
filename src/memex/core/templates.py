"""Templates for new Entities and Notes (SPEC §7).

Built-ins ship as `memex/core/templates/<type>/<name>.md`. Custom Templates at
`.memex/templates/<type>/<name>.md` replace a built-in of the same name or add a variant.
"""

import datetime as dt
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from memex.core import frontmatter
from memex.core.errors import NotFound, Validation
from memex.core.schema import NOT_FROM_TEMPLATES, EntityType
from memex.core.store import decode

if TYPE_CHECKING:
    from memex.core.workspace import Workspace

CUSTOM = ".memex/templates"
BLANK = "blank"

# The `<type>` part of a Template's key (§7.1). None is a Note.
TEMPLATE_TYPES: dict[EntityType | None, str] = {
    None: "note",
    EntityType.THEME: "theme",
    EntityType.PROJECT: "project",
    EntityType.DELIVERABLE: "deliverable",
    EntityType.PERSON: "person",
    EntityType.TODO: "todo",
    EntityType.GLOSSARY_TERM: "glossary",
}
_TYPE_FOR_KEY = {key: t for t, key in TEMPLATE_TYPES.items()}
_PLACEHOLDER = re.compile(r"\{\{(title|date|me)\}\}")
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def type_for_key(key: str) -> EntityType | None:
    """`note` → None, `glossary` → Glossary Term, …; Validation for anything else."""
    if key not in _TYPE_FOR_KEY:
        raise Validation(f"Unknown type {key!r}: one of {', '.join(_TYPE_FOR_KEY)}")
    return _TYPE_FOR_KEY[key]


@dataclass(frozen=True)
class Template:
    type: EntityType | None
    name: str  # the file stem, e.g. `meeting`
    label: str  # the display name
    source: Literal["blank", "builtin", "custom"]
    default: bool = False
    fields: Mapping[str, Any] = field(default_factory=dict)
    body: str = ""
    hidden: bool = False
    error: str | None = None  # a custom Template whose frontmatter doesn't parse
    overrides: bool = False  # a custom Template replacing a built-in

    @property
    def key(self) -> str:
        return f"{TEMPLATE_TYPES[self.type]}/{self.name}"

    @property
    def path(self) -> str | None:
        """The Workspace path of a custom Template."""
        return f"{CUSTOM}/{self.key}.md" if self.source == "custom" else None

    @property
    def usable(self) -> bool:
        return not self.hidden and self.error is None


@dataclass(frozen=True)
class TemplateSet:
    """Every Template for one type: built-in and custom, hidden and broken ones marked."""

    templates: tuple[Template, ...]
    default: Template
    warnings: tuple[str, ...] = ()

    @property
    def usable(self) -> tuple[Template, ...]:
        return tuple(t for t in self.templates if t.usable)

    def get(self, name: str | None) -> Template:
        """The named usable Template, or the default when `name` is None."""
        if name is None:
            return self.default
        for t in self.usable:
            if t.name == name:
                return t
        raise Validation(f"No Template {TEMPLATE_TYPES[self.default.type]}/{name!r} to use")


def templates_for(
    root: Path, entity_type: EntityType | None, hidden: tuple[str, ...] = ()
) -> TemplateSet:
    """Resolve a type's Templates (§7.1, §7.2, §7.5)."""
    type_key = TEMPLATE_TYPES[entity_type]
    builtins = {t.name: t for t in _builtins(entity_type)}
    customs = {t.name: t for t in _customs(root, entity_type)}
    found: list[Template] = []
    for name in sorted(builtins.keys() | customs.keys()):
        if name in customs:
            custom = customs[name]
            found.append(replace(custom, overrides=name in builtins))
        else:
            found.append(builtins[name])
    found = [
        replace(t, hidden=f"{type_key}/{t.name}" in hidden) if t.source == "builtin" else t
        for t in found
    ]
    blank = Template(entity_type, BLANK, "Blank", "blank")
    claims = [t for t in found if t.usable and t.default]
    warnings: tuple[str, ...] = ()
    if len(claims) > 1:
        names = ", ".join(t.key for t in claims)
        warnings = (f"Several {type_key} Templates claim default ({names}): using {claims[0].key}",)
    marked = [replace(t, default=t is (claims[0] if claims else blank)) for t in (blank, *found)]
    default = next(t for t in marked if t.default)
    return TemplateSet(tuple(marked), default=default, warnings=warnings)


def _builtin_files(entity_type: EntityType | None) -> list[Traversable]:
    folder = resources.files("memex.core").joinpath("templates", TEMPLATE_TYPES[entity_type])
    if not folder.is_dir():
        return []
    return [item for item in folder.iterdir() if item.name.endswith(".md")]


def _builtins(entity_type: EntityType | None) -> list[Template]:
    return [
        _parse(entity_type, item.name[:-3], item.read_text("utf-8"), "builtin")
        for item in _builtin_files(entity_type)
    ]


def _customs(root: Path, entity_type: EntityType | None) -> list[Template]:
    folder = root / CUSTOM / TEMPLATE_TYPES[entity_type]
    if not folder.is_dir():
        return []
    found = []
    for path in sorted(folder.glob("*.md")):
        name = path.stem
        if name == BLANK or not _NAME.match(name) or path.is_symlink():
            continue  # Blank can't be overridden (§7.2)
        try:
            text = decode(path.read_bytes())
        except UnicodeDecodeError:
            found.append(Template(entity_type, name, name, "custom", error="Not UTF-8"))
            continue
        found.append(_parse(entity_type, name, text, "custom"))
    return found


def _parse(
    entity_type: EntityType | None, name: str, text: str, source: Literal["builtin", "custom"]
) -> Template:
    try:
        fields, parts = frontmatter.parse(text)
    except frontmatter.FrontmatterError as e:
        line = f" (line {e.line})" if e.line else ""
        return Template(entity_type, name, name, source, error=f"{e.message}{line}")
    meta = fields.pop("template", None)
    meta = meta if isinstance(meta, Mapping) else {}
    label = meta.get("name")
    return Template(
        entity_type,
        name,
        label if isinstance(label, str) and label.strip() else name,
        source,
        default=meta.get("default") is True,
        fields=dict(fields),
        body=parts.body,
    )


def render(
    template: Template, title: str, today: dt.date, me: str | None
) -> tuple[dict[str, Any], str]:
    """The Template's fields and body with placeholders filled (§7.2).

    Fields the app controls are dropped. Without Me, `{{me}}` stays literal.
    """
    values = {"title": title, "date": today.isoformat(), "me": me}

    def fill(text: str) -> str:
        return _PLACEHOLDER.sub(lambda m: values[m.group(1)] or m.group(0), text)

    def fill_value(value: Any) -> Any:
        if isinstance(value, str):
            return fill(value)
        if isinstance(value, list):
            return [fill_value(v) for v in value]
        return value

    dropped = NOT_FROM_TEMPLATES[template.type]
    fields = {k: fill_value(v) for k, v in template.fields.items() if k not in dropped}
    return fields, fill(template.body)


def customise_template(ws: Workspace, entity_type: EntityType | None, name: str) -> str:
    """Settings → Customise: copy a built-in to `.memex/templates/` (§7.4); return its path."""
    for item in _builtin_files(entity_type):
        if item.name == f"{name}.md":
            rel = f"{CUSTOM}/{TEMPLATE_TYPES[entity_type]}/{name}.md"
            ws.store.create(rel, item.read_text("utf-8"))
            return rel
    raise NotFound(f"{TEMPLATE_TYPES[entity_type]}/{name}")
