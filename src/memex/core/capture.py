"""Inline To-do capture: turn a Note's unchecked task items into To-do files (SPEC §6.4).

An explicit action only. The preview parses each item with the quick-add parser and
records the Note's hash; the confirm is all-or-nothing: recheck the hash, create every
To-do, then rewrite the Note with the hash check, and if that fails move the new To-dos
to trash.
"""

import datetime as dt
import re
import textwrap
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from memex.core import frontmatter
from memex.core.cache import CachedFile, without_fenced_code
from memex.core.entities import Saved, create_entity, find
from memex.core.errors import (
    Conflict,
    FieldProblem,
    MeNotSet,
    UnknownReference,
    Validation,
)
from memex.core.quickadd import QuickAddError, parse_quick_add
from memex.core.schema import EntityType
from memex.core.workspace import Workspace

# `- [ ] text`, `* [ ] text`, `+ [ ] text`, at any indent.
_TASK = re.compile(r"^([ \t]*)([-*+]) \[ \][ \t]+(\S.*?)\s*$")
# An item whose only content is a To-do Mention has been converted already.
_SOLE_MENTION = re.compile(r"^\[\[([^\[\]\n]+)\]\]$")


@dataclass(frozen=True)
class TaskItem:
    """One unconverted task item in a body, with its indented sub-lines.

    "Task item" is the Markdown `- [ ]` syntax (SPEC §6.4), not a To-do.
    """

    start: int  # 0-based line index of the item in the body
    end: int  # one past its last sub-line
    indent: str
    bullet: str
    text: str  # the item's content after `[ ] `
    detail: str  # the sub-lines, dedented: the To-do's body


def task_items(ws: Workspace, body: str) -> list[TaskItem]:
    """Every unconverted task item in a Note's body, in order.

    Unchecked items (`-`, `*` or `+` bullets) at any indent, outside fenced code, and
    not ones whose only content is a Mention of a To-do (converted already; a Mention
    naming nothing counts too, as its To-do has gone). An item's sub-lines are the
    lines after it indented deeper, up to the next unchecked item.
    """
    lines = body.splitlines(keepends=True)
    masked = without_fenced_code(body).splitlines(keepends=True)
    items: list[TaskItem] = []
    for i, line in enumerate(masked):
        match = _TASK.match(line)
        if not match or _converted(ws, match.group(3)):
            continue
        indent = match.group(1)
        end = last = i + 1  # `last`: one past the last non-blank sub-line
        while end < len(lines):
            if lines[end].strip():
                if _indent(lines[end]) <= len(indent) or _TASK.match(masked[end]):
                    break
                last = end + 1
            end += 1
        detail = textwrap.dedent("".join(lines[i + 1 : last]))
        if detail and not detail.endswith("\n"):
            detail += "\n"
        items.append(TaskItem(i, last, indent, match.group(2), match.group(3), detail))
    return items


def _converted(ws: Workspace, text: str) -> bool:
    mention = _SOLE_MENTION.match(text)
    if mention is None:
        return False
    found = ws.cache.resolve(mention.group(1).strip()).file
    return found is None or found.type is EntityType.TODO


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


@dataclass(frozen=True)
class Row:
    """One preview row: an item as the quick-add parser reads it, with the defaults."""

    index: int  # the item's position among the Note's task items
    line: int  # 1-based line in the body
    text: str
    title: str
    owner: str | None
    requester: str | None
    due: dt.date | None
    about: str | None
    body: str
    errors: tuple[QuickAddError, ...]


@dataclass(frozen=True)
class Preview:
    note: CachedFile
    hash: str  # the Note's hash when the preview opened: confirm checks it
    rows: tuple[Row, ...]


def preview(ws: Workspace, id: str) -> Preview:
    """The rows "Create N To-dos" offers for a Note, and the Note's hash now."""
    note = _note(ws, id)
    current = ws.store.read(note.rel)
    about = _about(ws, note)
    return Preview(
        note,
        current.hash,
        tuple(
            _row(ws, n, item, about)
            for n, item in enumerate(task_items(ws, frontmatter.split(current.text).body))
        ),
    )


def _row(ws: Workspace, n: int, item: TaskItem, about: str | None) -> Row:
    parsed = parse_quick_add(ws, item.text)
    return Row(
        index=n,
        line=item.start + 1,
        text=item.text,
        title=parsed.title,
        owner=parsed.owner,
        requester=parsed.requester,
        due=parsed.due,
        about=about,
        body=item.detail,
        errors=parsed.errors,
    )


def _note(ws: Workspace, id: str) -> CachedFile:
    note = find(ws, id)
    if note.type is not None:
        raise Validation("To-dos are captured from Notes only")
    return note


def _about(ws: Workspace, note: CachedFile) -> str | None:
    """The Note's `about`, when it names exactly one Project or Deliverable."""
    work = (EntityType.PROJECT, EntityType.DELIVERABLE)
    found = {
        f.id
        for r in note.references
        if r.field == "about" and (f := ws.cache.resolve(r.id).file) and f.type in work
    }
    return found.pop() if len(found) == 1 else None


# Confirm

_EDITABLE = ("owner", "requester", "due", "about")


@dataclass(frozen=True)
class RowChoice:
    """A ticked row to create. `edits` overrides the parsed `owner`, `requester`, `due`
    or `about`; an edited field's parse error counts as fixed. `None` clears `due` or
    `about`."""

    index: int
    edits: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Captured:
    note: Saved
    todos: tuple[Saved, ...]


def confirm(ws: Workspace, id: str, expected_hash: str, rows: Sequence[RowChoice]) -> Captured:
    """Create the chosen rows' To-dos and rewrite their items to `- [ ] [[todo-id]]`.

    `conflict` when the Note changed since the preview (nothing is written), or when the
    Note's rewrite fails (the new To-dos are moved to trash first).
    """
    note = _note(ws, id)
    current = ws.store.read(note.rel)
    if current.hash != expected_hash:
        raise Conflict(note.rel, current)
    body = frontmatter.split(current.text).body
    items = task_items(ws, body)
    about = _about(ws, note)
    chosen = _chosen(rows, len(items))
    planned = [_fields(ws, _row(ws, c.index, items[c.index], about), c, note.id) for c in chosen]

    created: list[Saved] = []
    try:
        for c, fields in zip(chosen, planned, strict=True):
            detail = items[c.index].detail
            created.append(create_entity(ws, EntityType.TODO, fields, body=detail or None))
        lines = body.splitlines(keepends=True)
        for c, saved in reversed(list(zip(chosen, created, strict=True))):
            item = items[c.index]
            ending = "\n" if lines[item.end - 1].endswith("\n") else ""
            converted = f"{item.indent}{item.bullet} [ ] [[{saved.id}]]{ending}"
            lines[item.start : item.end] = [converted]
        head = current.text[: len(current.text) - len(body)]
        new_hash = ws.store.write(note.rel, head + "".join(lines), expected_hash)
    except Exception:  # all or nothing: no new To-do outlives a Note left unchanged
        stamp = ws.clock.now().strftime("%Y%m%d-%H%M%S")
        for saved in created:
            ws.store.trash(saved.rel, stamp)
        raise
    return Captured(Saved(note.id, note.rel, new_hash), tuple(created))


def _me_missing(e: QuickAddError) -> bool:
    """A party with no token that fell back to Me while Me isn't set: `me_not_set`."""
    return e.token is None and e.field in ("owner", "requester")


def _chosen(rows: Sequence[RowChoice], count: int) -> list[RowChoice]:
    if not rows:
        raise Validation("Tick at least one To-do to create")
    seen: set[int] = set()
    for c in rows:
        if not 0 <= c.index < count or c.index in seen:
            raise Validation(f"Row {c.index} isn't a task item of this Note: review again")
        if unknown := set(c.edits) - set(_EDITABLE):
            raise Validation(f"Only {', '.join(_EDITABLE)} can be edited, not {sorted(unknown)[0]}")
        seen.add(c.index)
    return sorted(rows, key=lambda c: c.index)


def _fields(ws: Workspace, row: Row, choice: RowChoice, source: str) -> dict[str, Any]:
    """The To-do's fields: parsed, then edited. A parse error left unedited blocks."""
    problems = [
        FieldProblem(e.field, f"Line {row.line}: {e.message}")
        for e in row.errors
        if e.field not in choice.edits and not _me_missing(e)
    ]
    message = "; ".join(p.message for p in problems)
    unresolved = [e for e in row.errors if e.unresolved and e.field not in choice.edits]
    if bad := next(iter(unresolved), None):
        raise UnknownReference(
            bad.field, bad.token or "", "a Person", bad.candidates, problems, message
        )
    if problems:
        raise Validation(message, problems)
    values: dict[str, Any] = {
        "owner": row.owner,
        "requester": row.requester,
        "due": row.due,
        "about": row.about,
        **choice.edits,
    }
    fields: dict[str, Any] = {"title": row.title, "source": source}
    for name in _EDITABLE:
        if values[name] not in (None, ""):
            fields[name] = values[name]
    for party in ("owner", "requester"):
        if party not in fields:
            me = ws.me()
            if me is None:
                raise MeNotSet()
            fields[party] = me.id
    return fields
