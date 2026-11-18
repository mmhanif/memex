"""Creating and updating Entities and Notes, with strict-write validation (SPEC §4.5, §8.1, §8.2).

Every surface (UI, REST, MCP) writes through here, so the app never writes invalid
frontmatter or a Broken Reference.
"""

import datetime as dt
import difflib
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Literal

from ruamel.yaml.comments import CommentedSeq

from memex.core import frontmatter
from memex.core.cache import CachedFile, FileWarning
from memex.core.errors import (
    AmbiguousId,
    BadPath,
    Conflict,
    FieldProblem,
    IdTaken,
    MeNotSet,
    NotFound,
    UnknownReference,
    Validation,
)
from memex.core.ids import make_id
from memex.core.schema import (
    AUTOMATIC,
    FIELD_BY_NAME,
    FIELDS,
    FINISHED_TODO,
    EntityType,
    Field,
    Target,
    check_value,
    is_missing,
    parse_date,
)
from memex.core.store import FileVersion
from memex.core.templates import render, templates_for
from memex.core.workspace import Workspace

NOTES_FOLDER = "notes"


@dataclass(frozen=True)
class Saved:
    """A write's result: the file's Id, path and new hash (§5.3)."""

    id: str
    rel: str
    hash: str


def find(ws: Workspace, id: str) -> CachedFile:
    """The file an Id names. NotFound or AmbiguousId otherwise."""
    found = ws.cache.resolve(id)
    if found.status == "ambiguous":
        raise AmbiguousId(id)
    if found.file is None:
        raise NotFound(id)
    return found.file


def create_entity(
    ws: Workspace,
    entity_type: EntityType | None,
    fields: Mapping[str, Any],
    body: str | None = None,
    template: str | None = None,
    folder: str | None = None,
    id: str | None = None,
) -> Saved:
    """Create an Entity, or a Note when `entity_type` is None (§8.1).

    Template defaults first, the caller's fields over them, then validate, pick the
    Id, and write with `created: today`. A Note goes in `notes/` unless `folder` names
    another, `""` being the Workspace root (Files page "New file here", §7.4).
    `id` takes a given Id instead of one made from the title: Broken Reference **Create**
    (§8.5) makes the file the references already name.
    """
    _refuse_automatic(fields)
    folder = _note_folder(entity_type, folder)
    title = fields.get("title")
    title = title.strip() if isinstance(title, str) else ""
    chosen = templates_for(ws.root, entity_type, ws.config.hidden_templates).get(template)
    me = ws.me()
    t_fields, t_body = render(chosen, title, ws.clock.today(), me.id if me else None)
    merged: dict[str, Any] = {**t_fields, **fields}
    if title:
        merged["title"] = title
    for spec in FIELDS[entity_type]:
        if spec.default is not None and is_missing(merged.get(spec.name)):
            merged[spec.name] = spec.default
    today = ws.clock.today()
    if entity_type is EntityType.TODO:
        if is_missing(merged.get("requester")):
            if me is None:
                raise MeNotSet()
            merged["requester"] = me.id
        if merged.get("status") in FINISHED_TODO:
            merged["completed"] = today
    merged["created"] = today
    from_template = {k for k in t_fields if k not in fields}
    _validate(
        ws,
        entity_type,
        merged,
        changed=merged.keys(),
        from_template=from_template,
        template_key=chosen.key,
    )

    dated = entity_type is EntityType.TODO or (entity_type is None and "date" in merged)
    date = today if entity_type is EntityType.TODO else parse_date(merged.get("date"))
    if id is not None:
        require_free_id(ws, id)
        new_id = id
    else:
        new_id = make_id(title, {f.id for f in ws.cache.files()}, date if dated else None)
    rel = f"{folder}/{new_id}.md" if folder else f"{new_id}.md"
    text = frontmatter.with_fields("", _ordered(entity_type, merged))
    new_hash = ws.store.create(rel, text + (t_body if body is None else body))
    return Saved(new_id, rel, new_hash)


def update_fields(
    ws: Workspace,
    id: str,
    expected_hash: str,
    set: Mapping[str, Any] | None = None,
    unset: Iterable[str] = (),
) -> Saved:
    """A partial, hash-checked frontmatter change (§8.2). The body is untouched."""
    entry = find(ws, id)
    set, unset = dict(set or {}), list(unset)
    _refuse_automatic({**set, **dict.fromkeys(unset)})
    if overlap := set.keys() & unset:
        raise Validation(f"{sorted(overlap)[0]} can't be both set and unset")
    merged = {k: v for k, v in entry.fields.items() if k not in unset} | set
    if entry.type is EntityType.TODO and "status" in set:
        if set["status"] in FINISHED_TODO and entry.fields.get("status") not in FINISHED_TODO:
            set["completed"] = ws.clock.today()
        elif set["status"] == "open":
            unset.append("completed")
    if set.get("archived") and ws.is_me(entry):
        raise Validation("Me can't be archived", [FieldProblem("archived", "Me can't be archived")])
    _validate(ws, entry.type, merged, changed=[*set, *unset], self_id=entry.id)
    new_hash = ws.store.update_fields(
        entry.rel, expected_hash, set=_ordered(entry.type, set, keep_order=True), unset=unset
    )
    return Saved(entry.id, entry.rel, new_hash)


def replace_body(ws: Workspace, id: str, body: str, expected_hash: str) -> Saved:
    """A whole-body, hash-checked replace (§8.2). The frontmatter is kept byte for byte.

    A conflict carries what is on disk now as the body alone, with the file's hash.
    """
    entry = find(ws, id)
    current = ws.store.read(entry.rel)
    if current.hash != expected_hash:
        raise _body_conflict(entry.rel, current)
    try:
        new_hash = ws.store.write(entry.rel, _with_body(current.text, body), expected_hash)
    except Conflict as e:
        raise _body_conflict(entry.rel, e.current) from None
    return Saved(entry.id, entry.rel, new_hash)


def append_body(ws: Workspace, id: str, text: str) -> Saved:
    """Add `text` to the end of the body (§8.2), on a fresh new line."""
    entry = find(ws, id)
    current = ws.store.read(entry.rel)
    body = frontmatter.split(current.text).body
    if body and not body.endswith("\n"):
        body += "\n"
    new_hash = ws.store.write(entry.rel, _with_body(current.text, body + text), current.hash)
    return Saved(entry.id, entry.rel, new_hash)


def require_free_id(ws: Workspace, id: str) -> None:
    """No file has `id`, ignoring case; files in trash don't count (§4.1). IdTaken otherwise."""
    if ws.cache.resolve(id).status != "missing":
        raise IdTaken(id)


def _note_folder(entity_type: EntityType | None, folder: str | None) -> str:
    if entity_type is not None:
        if folder is not None:
            raise Validation(f"A {entity_type.display_name} always goes in {entity_type.folder}/")
        return entity_type.folder
    if folder is None:
        return NOTES_FOLDER
    parts = PurePosixPath(folder).parts
    if EntityType.for_folder(folder) or any(p.startswith(".") for p in parts):
        raise BadPath(folder, "Notes can't go in type folders or hidden folders")
    return folder


def body_of(version: FileVersion) -> FileVersion:
    """A file version cut down to its body, keeping the whole file's hash."""
    return FileVersion(text=frontmatter.split(version.text).body, hash=version.hash)


def _body_conflict(rel: str, current: FileVersion) -> Conflict:
    return Conflict(rel, body_of(current))


def _with_body(text: str, body: str) -> str:
    old_body = frontmatter.split(text).body
    return text[: len(text) - len(old_body)] + body


# Validation (§4.5)


def _refuse_automatic(fields: Mapping[str, Any]) -> None:
    for name in sorted(AUTOMATIC):
        if name in fields:
            raise Validation(
                f"{name} is set automatically", [FieldProblem(name, f"{name} is set automatically")]
            )


def _validate(
    ws: Workspace,
    entity_type: EntityType | None,
    fields: Mapping[str, Any],
    changed: Iterable[str],
    self_id: str | None = None,
    from_template: Iterable[str] = (),
    template_key: str | None = None,
) -> None:
    """Strict write: the fields being written must be valid, and required ones present.

    Fields not being written keep whatever an outside edit left there.
    """
    specs = FIELD_BY_NAME[entity_type]
    changed = list(dict.fromkeys(changed))
    templated = set(from_template)

    def source(name: str) -> str:
        return f" (from Template {template_key})" if name in templated else ""

    problems: list[FieldProblem] = []
    for spec in FIELDS[entity_type]:
        value = fields.get(spec.name)
        if is_missing(value):
            if spec.required:
                problems.append(FieldProblem(spec.name, f"{spec.name} is required"))
        elif spec.name in changed and (p := check_value(spec, value)):
            problems.append(FieldProblem(p.field, p.message + source(p.field), p.allowed))
    if problems:
        raise Validation("; ".join(p.message for p in problems), problems)

    for name in changed:
        spec = specs.get(name)
        value = fields.get(name)
        if spec is None or spec.shape not in ("ref", "refs") or is_missing(value):
            continue
        for ref in value if isinstance(value, list) else [value]:
            _check_reference(ws, spec, str(ref), source(name))
    if entity_type is EntityType.PERSON and "manager" in changed and fields.get("manager"):
        _check_manager(ws, self_id, fields["manager"])


def _check_reference(ws: Workspace, spec: Field, ref: str, source: str) -> None:
    expected = describe_targets(spec.targets)
    found = ws.cache.resolve(ref)
    if found.status == "ambiguous":
        message = f"{ref!r} names more than one file"
    elif found.file is None or found.file.type not in spec.targets:
        message = f"{ref!r} is not {expected}"
    else:
        return
    suggestions = _suggest(ws, ref, spec.targets)
    hint = f": did you mean {', '.join(suggestions)}?" if suggestions else ""
    problem = FieldProblem(spec.name, f"{spec.name}: {message}{hint}{source}")
    raise UnknownReference(spec.name, ref, expected, suggestions, [problem], problem.message)


def _suggest(ws: Workspace, ref: str, targets: tuple[Target, ...]) -> list[str]:
    candidates = [f.id for f in ws.cache.files() if f.type in targets and not f.ambiguous]
    return difflib.get_close_matches(ref, candidates, n=3, cutoff=0.6)


def describe_targets(targets: tuple[Target, ...]) -> str:
    names = [t.display_name if t else "Note" for t in targets]
    if len(names) == 1:
        return f"a {names[0]}"
    return "a " + ", ".join(names[:-1]) + f" or {names[-1]}"


def _check_manager(ws: Workspace, self_id: str | None, manager: str) -> None:
    """Not themself, and no cycle up the chain (§4.5)."""
    if self_id is None:
        return  # a new Person has no reports yet, so can't close a loop
    if manager.casefold() == self_id.casefold():
        message = "manager can't be the Person themself"
    elif _manages(ws, self_id, manager):
        message = f"manager: {manager!r} would create a manager cycle"
    else:
        return
    raise Validation(message, [FieldProblem("manager", message)])


def _manages(ws: Workspace, person: str, start: str | None) -> bool:
    """Whether `person` is on the manager chain going up from `start`."""
    seen: set[str] = set()
    current = start
    while isinstance(current, str) and current.casefold() not in seen:
        if current.casefold() == person.casefold():
            return True
        seen.add(current.casefold())
        found = ws.cache.resolve(current).file
        current = found.fields.get("manager") if found else None
    return False


# Writing values


def _ordered(
    entity_type: EntityType | None, fields: Mapping[str, Any], keep_order: bool = False
) -> dict[str, Any]:
    """Values in YAML form; for a new file, known fields in schema order, others after."""
    specs = FIELD_BY_NAME[entity_type]
    names = list(fields)
    if not keep_order:
        known = [s.name for s in FIELDS[entity_type] if s.name in fields and s.name != "created"]
        others = [n for n in fields if n not in specs]
        names = known + others + (["created"] if "created" in fields else [])
    return {n: _yaml_value(specs.get(n), fields[n]) for n in names}


def _yaml_value(spec: Field | None, value: Any) -> Any:
    if spec is not None and spec.shape == "date":
        return parse_date(value) or value
    if isinstance(value, list):
        seq = CommentedSeq(value)
        seq.fa.set_flow_style()
        return seq
    return value


# Reading (§4.6, §11.5)


@dataclass(frozen=True)
class BrokenReference:
    field: str  # a frontmatter field, or "mention" for `[[id]]` in the body
    id: str
    status: Literal["missing", "ambiguous", "wrong_type"]


@dataclass(frozen=True)
class EntityDetail:
    file: CachedFile
    warnings: tuple[FileWarning, ...]  # the file's own, plus cross-file ones (manager cycles)
    broken: tuple[BrokenReference, ...]
    names: Mapping[str, str]  # title of each file its fields and Mentions name, by Id as written
    children: tuple[CachedFile, ...]  # a Theme's Projects, a Project's Deliverables
    todos: tuple[CachedFile, ...]  # To-dos `about` it
    notes: tuple[CachedFile, ...]  # Notes with `about` including it
    mentioned_in: tuple[CachedFile, ...]


def entity_detail(ws: Workspace, id: str) -> EntityDetail:
    entry = find(ws, id)
    specs = FIELD_BY_NAME[entry.type]
    broken: list[BrokenReference] = []
    names: dict[str, str] = {}
    for ref in entry.references:
        found = ws.cache.resolve(ref.id)
        if found.status == "ambiguous":
            broken.append(BrokenReference(ref.field, ref.id, "ambiguous"))
        elif found.file is None:
            broken.append(BrokenReference(ref.field, ref.id, "missing"))
        else:
            names[ref.id] = found.file.title
            if found.file.type not in specs[ref.field].targets:
                broken.append(BrokenReference(ref.field, ref.id, "wrong_type"))
    for mention in dict.fromkeys(entry.mentions):
        found = ws.cache.resolve(mention)
        if found.file is None:
            status = "ambiguous" if found.status == "ambiguous" else "missing"
            broken.append(BrokenReference("mention", mention, status))
        else:
            names[mention] = found.file.title

    warnings = list(entry.warnings)
    if entry.type is EntityType.PERSON and _manages(ws, entry.id, entry.fields.get("manager")):
        warnings.append(FileWarning("validation", "manager: part of a manager cycle"))

    key = entry.id.casefold()
    files = [f for f in ws.cache.files() if f.rel != entry.rel]

    def names_it(f: CachedFile, field: str) -> bool:
        return refers(f, [field], entry.id)

    child_type, child_field = _CHILDREN.get(entry.type, (None, ""))
    return EntityDetail(
        file=entry,
        warnings=tuple(warnings),
        broken=tuple(broken),
        names=names,
        children=tuple(
            f for f in files if child_type and f.type is child_type and names_it(f, child_field)
        ),
        todos=tuple(f for f in files if f.type is EntityType.TODO and names_it(f, "about")),
        notes=tuple(f for f in files if f.type is None and names_it(f, "about")),
        mentioned_in=tuple(f for f in files if key in {m.casefold() for m in f.mentions}),
    )


_LINE_MARKER = re.compile(r"^\s*(?:#{1,6}\s+|[-*+]\s+(?:\[[ xX]\]\s+)?|\d+[.)]\s+|>\s*)*")


def mention_context(body: str, id: str) -> str | None:
    """The first line of `body` that Mentions `id` (ignoring case), without its list or
    heading marker: what a Linked Reference shows (§11.5)."""
    mention = re.compile(r"\[\[\s*" + re.escape(id) + r"\s*\]\]", re.IGNORECASE)
    for line in body.splitlines():
        if mention.search(line):
            return _LINE_MARKER.sub("", line, count=1).strip()
    return None


def refers(f: CachedFile, fields: Iterable[str], id: str) -> bool:
    """Whether one of `f`'s `fields` names `id`, ignoring case."""
    return any(r.field in fields and r.id.casefold() == id.casefold() for r in f.references)


_CHILDREN: dict[EntityType | None, tuple[EntityType, str]] = {
    EntityType.THEME: (EntityType.PROJECT, "theme"),
    EntityType.PROJECT: (EntityType.DELIVERABLE, "project"),
}


# The `person` filter: work they Lead or are Tagged on, and To-dos they own or requested.
_PERSON_FILTER_FIELDS = ("lead", "team", "stakeholders", "owner", "requester")


def list_entities(
    ws: Workspace,
    type: EntityType | None = None,
    notes: bool = False,
    status: str | None = None,
    theme: str | None = None,
    project: str | None = None,
    person: str | None = None,
    label: str | None = None,
    due_before: dt.date | None = None,
    include_archived: bool = False,
) -> list[CachedFile]:
    """Entity summaries, filtered, ordered by title (§17.2). `notes=True` lists Notes."""

    def keep(f: CachedFile) -> bool:
        if notes and f.type is not None:
            return False
        if not notes and (f.type is None or (type is not None and f.type is not type)):
            return False
        if not include_archived and f.fields.get("archived"):
            return False
        if status is not None and f.fields.get("status") != status:
            return False
        if theme is not None and not refers(f, ["theme"], theme):
            return False
        if project is not None and not refers(f, ["project"], project):
            return False
        if person is not None and not refers(f, _PERSON_FILTER_FIELDS, person):
            return False
        labels = f.fields.get("labels")
        if label is not None and not (isinstance(labels, list) and label in labels):
            return False
        if due_before is not None:
            due = parse_date(f.fields.get("due"))
            if due is None or due >= due_before:
                return False
        return True

    return sorted(filter(keep, ws.cache.files()), key=lambda f: (f.title.casefold(), f.id))
