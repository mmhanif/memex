"""Entity lifecycle: Rename id, guided delete, trash and restore, Broken Reference repair,
and archive's loose ends (SPEC §5.5, §8.3 to §8.5).

Rename, delete and repair all come down to one move: rewrite every reference to an
Id, in frontmatter, in `[[id]]` Mentions and in `me`, to another Id or to nothing.
Each operation previews first (`dry_run`), then applies file by file through the
hash-checked write, skipping and reporting the files that fail.
"""

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from memex.core import frontmatter
from memex.core.cache import CachedFile, load_file, mention_spans
from memex.core.entities import (
    Saved,
    create_entity,
    describe_targets,
    find,
    refers,
    require_free_id,
    update_fields,
)
from memex.core.errors import (
    CoreError,
    HasReferences,
    NotBroken,
    NotFound,
    ReadOnly,
    UnknownReference,
    Validation,
)
from memex.core.ids import is_valid_id
from memex.core.schema import FIELD_BY_NAME, FINISHED_TODO, REFERENCE_FIELDS, EntityType, Target
from memex.core.store import TRASH, WORKSPACE_CONFIG, TrashEntry
from memex.core.workspace import Workspace

CONFIG_TITLE = "Workspace config"
# Where a reference is written, besides a frontmatter field's name:
MENTION = "mention"  # `[[id]]` in a body
ME = "me"  # `me` in the Workspace config


@dataclass(frozen=True)
class Edit:
    """One file an operation rewrites, as it was when previewed."""

    rel: str
    title: str
    hash: str
    fields: tuple[str, ...]  # frontmatter fields, MENTION, or ME
    count: int  # references rewritten


@dataclass(frozen=True)
class Blocker:
    """A required reference that Remove can't clear (§8.4)."""

    rel: str
    title: str
    field: str


@dataclass(frozen=True)
class Impact:
    edits: tuple[Edit, ...] = ()
    blocked: tuple[Blocker, ...] = ()

    @property
    def references(self) -> int:
        return sum(e.count for e in self.edits)

    @property
    def summary(self) -> str:
        """ "updates 14 references in 9 files" (§5.5)."""
        refs, files = self.references, len(self.edits)
        return f"updates {_count(refs, 'reference')} in {_count(files, 'file')}"


@dataclass(frozen=True)
class Skipped:
    """A file left alone because it changed since the preview, is locked, or went."""

    rel: str
    code: str
    message: str


@dataclass(frozen=True)
class Outcome:
    impact: Impact
    applied: bool
    skipped: tuple[Skipped, ...] = ()
    id: str | None = None  # the Id references now name: new Id, replacement, or created
    rel: str | None = None  # where that Entity's file is
    trash: str | None = None  # the trash path of a deleted file

    @property
    def hashes(self) -> dict[str, str]:
        """The hashes the preview saw, to pass back as `expected` when applying."""
        return {e.rel: e.hash for e in self.impact.edits}


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


# Rewriting references


@dataclass(frozen=True)
class _Rewrite:
    """Rewrite references to `old` to `new`; with `new=None` remove them, a Mention
    becoming `label` as plain text."""

    old: str
    new: str | None
    label: str = ""

    def names_old(self, value: Any) -> bool:
        return isinstance(value, str) and value.casefold() == self.old.casefold()


@dataclass(frozen=True)
class _Rewritten:
    text: str
    fields: tuple[str, ...]
    count: int
    blocked: tuple[str, ...]


def _rewrite_text(entity_type: EntityType | None, text: str, rw: _Rewrite) -> _Rewritten:
    fields: list[str] = []
    blocked: list[str] = []
    count = 0
    specs = FIELD_BY_NAME[entity_type]

    def change(data: Any) -> None:
        nonlocal count
        for name in REFERENCE_FIELDS[entity_type]:
            value = data.get(name)
            if rw.names_old(value):
                if rw.new is not None:
                    data[name] = rw.new
                elif specs[name].required:
                    blocked.append(name)
                    continue
                else:
                    del data[name]
            elif isinstance(value, list) and (hits := _hits(value, rw)):
                new = rw.new
                has_new = new is not None and any(
                    isinstance(v, str) and v.casefold() == new.casefold() for v in value
                )
                for i in reversed(hits):
                    if new is None or has_new or i != hits[0]:
                        del value[i]
                    else:
                        value[i] = new
                if not value:
                    del data[name]
                count += len(hits) - 1  # one more is counted below
            else:
                continue
            count += 1
            fields.append(name)

    try:
        changed = frontmatter.edited(text, change)
    except frontmatter.FrontmatterError:
        changed = text  # unreadable frontmatter holds no references the app knows of
    if fields:
        text = changed

    body = frontmatter.split(text).body
    head = text[: len(text) - len(body)]
    mentions = [m for m in mention_spans(body) if rw.names_old(m.id)]
    for m in reversed(mentions):
        body = body[: m.start] + (f"[[{rw.new}]]" if rw.new else rw.label) + body[m.end :]
    if mentions:
        fields.append(MENTION)
        count += len(mentions)
    return _Rewritten(head + body, tuple(fields), count, tuple(blocked))


def _hits(values: list[Any], rw: _Rewrite) -> list[int]:
    return [i for i, v in enumerate(values) if rw.names_old(v)]


def _referring(ws: Workspace, rw: _Rewrite, skip: str | None) -> list[CachedFile]:
    """Files whose references or Mentions name `rw.old`. `skip`: a file left out (the one
    being deleted)."""
    return [f for f in ws.cache.referrers([rw.old]) if f.rel != skip]


def _impact(ws: Workspace, rw: _Rewrite, skip: str | None = None) -> Impact:
    """What rewriting would change, read from disk now."""
    edits: list[Edit] = []
    blocked: list[Blocker] = []
    for f in _referring(ws, rw, skip):
        current = ws.store.read(f.rel)
        result = _rewrite_text(f.type, current.text, rw)
        blocked.extend(Blocker(f.rel, f.title, name) for name in result.blocked)
        if result.count:
            edits.append(Edit(f.rel, f.title, current.hash, result.fields, result.count))
    if rw.names_old(ws.config.me):
        if rw.new is None:
            blocked.append(Blocker(WORKSPACE_CONFIG, CONFIG_TITLE, ME))
        else:
            edits.append(Edit(WORKSPACE_CONFIG, CONFIG_TITLE, ws.config_hash(), (ME,), 1))
    return Impact(tuple(edits), tuple(blocked))


def _apply(
    ws: Workspace, rw: _Rewrite, expected: Mapping[str, str], skip: str | None = None
) -> tuple[Skipped, ...]:
    """Rewrite each file through the hash-checked write, against the preview's hash when
    given; files that fail are skipped and reported (§5.5).

    `me` goes first, and if it can't be written nothing else is: Me pointing at nothing
    is worse than one stale file, so that failure raises instead of being skipped.
    """
    if ws.read_only:
        raise ReadOnly()
    if rw.new is not None and rw.names_old(ws.config.me):
        ws.save_config(expected.get(WORKSPACE_CONFIG, ws.config_hash()), {ME: rw.new})
    skipped: list[Skipped] = []
    for f in _referring(ws, rw, skip):
        try:
            current = ws.store.read(f.rel)
            result = _rewrite_text(f.type, current.text, rw)
            if result.count:
                ws.store.write(f.rel, result.text, expected.get(f.rel, current.hash))
        except CoreError as e:
            skipped.append(Skipped(f.rel, e.code, e.message))
    return tuple(skipped)


# Rename id (§5.5)


def rename_id(
    ws: Workspace,
    id: str,
    new_id: str,
    dry_run: bool = True,
    expected: Mapping[str, str] | None = None,
) -> Outcome:
    """Preview, or apply, giving an Entity or Note a new Id.

    Applying rewrites `me`, then every reference and Mention, then renames the file.
    Pass the preview's `hashes` as `expected` so files changed since are skipped.
    """
    entry = find(ws, id)
    new_id = _new_id(new_id)
    if new_id == entry.id:
        raise Validation(f"{entry.title} already has the Id {new_id}")
    require_free_id(ws, new_id)
    new_rel = _renamed(entry.rel, new_id)
    rw = _Rewrite(entry.id, new_id)
    impact = _impact(ws, rw)
    if dry_run:
        return Outcome(impact, applied=False, id=new_id, rel=new_rel)
    skipped = _apply(ws, rw, expected or {})
    ws.store.move(entry.rel, new_rel)
    return Outcome(impact, applied=True, skipped=skipped, id=new_id, rel=new_rel)


def _new_id(new_id: str) -> str:
    new_id = new_id.strip()
    if not is_valid_id(new_id):
        raise Validation("An Id is lowercase letters, digits and -, at most 60 characters")
    return new_id


def _renamed(rel: str, new_id: str) -> str:
    parent = PurePosixPath(rel).parent.as_posix()
    return f"{new_id}.md" if parent == "." else f"{parent}/{new_id}.md"


# Archive (§8.3)


def archive(ws: Workspace, id: str, expected_hash: str) -> Saved:
    """Set `archived: <today>` on a Theme or Person. Me can't be archived."""
    entry = find(ws, id)
    if entry.type not in ARCHIVABLE:
        raise Validation("Only Themes and Persons are archived; work ends as done or cancelled")
    return update_fields(ws, id, expected_hash, set={"archived": ws.clock.today()})


def unarchive(ws: Workspace, id: str, expected_hash: str) -> Saved:
    return update_fields(ws, id, expected_hash, unset=["archived"])


ARCHIVABLE = (EntityType.THEME, EntityType.PERSON)


@dataclass(frozen=True)
class LooseEnd:
    """One line of the archive checklist: a warning only, never a block (§8.3)."""

    label: str
    items: tuple[CachedFile, ...]


def loose_ends(ws: Workspace, id: str) -> tuple[LooseEnd, ...]:
    """What archiving would leave hanging: a Person's open To-dos, active Lead roles and
    Directs; a Theme's unfinished Projects. Nothing for other types."""
    entry = find(ws, id)
    files = [f for f in ws.cache.files() if f.rel != entry.rel]

    def named(types: tuple[EntityType, ...], field: str) -> list[CachedFile]:
        found = (f for f in files if f.type in types and refers(f, [field], entry.id))
        return sorted(found, key=lambda f: (f.title.casefold(), f.id))

    def unfinished(f: CachedFile) -> bool:
        return f.fields.get("status") not in FINISHED_TODO

    ends: list[LooseEnd] = []
    if entry.type is EntityType.PERSON:
        todos = [t for t in named((EntityType.TODO,), "owner") if t.fields.get("status") == "open"]
        work = (EntityType.PROJECT, EntityType.DELIVERABLE)
        led = [f for f in named(work, "lead") if unfinished(f)]
        managed = named((EntityType.PERSON,), "manager")
        directs = [p for p in managed if not p.fields.get("archived")]
        ends = [
            LooseEnd(f"Owner of {_count(len(todos), 'open To-do')}", tuple(todos)),
            LooseEnd(f"Lead on {len(led)} active {_work_noun(len(led))}", tuple(led)),
            LooseEnd(f"Manager of {_count(len(directs), 'Person')}", tuple(directs)),
        ]
    elif entry.type is EntityType.THEME:
        projects = [p for p in named((EntityType.PROJECT,), "theme") if unfinished(p)]
        noun = "Project" if len(projects) == 1 else "Projects"
        ends = [LooseEnd(f"{len(projects)} {noun} not done or cancelled", tuple(projects))]
    return tuple(e for e in ends if e.items)


def _work_noun(n: int) -> str:
    return "Project or Deliverable" if n == 1 else "Projects or Deliverables"


# Delete (§8.4)

DeleteMode = Literal["plain", "replace", "remove"]


def delete_entity(
    ws: Workspace,
    id: str,
    mode: DeleteMode = "plain",
    replacement: str | None = None,
    dry_run: bool = True,
    expected: Mapping[str, str] | None = None,
) -> Outcome:
    """Preview, or apply, a guided delete to trash. No cascade.

    `plain` deletes only while nothing refers in; `replace` first rewrites every reference
    to `replacement` (an Entity of the same type); `remove` clears them, and is blocked by
    required references. The preview of `remove` is the impact preview for all three.
    """
    entry = find(ws, id)
    if ws.is_me(entry):
        raise Validation("Me can't be deleted: change Me in Settings first")
    if mode == "replace":
        rw = _Rewrite(entry.id, _replacement(ws, entry, replacement))
    else:
        rw = _Rewrite(entry.id, None, entry.title)
    impact = _impact(ws, rw, skip=entry.rel)
    if mode == "plain" and not dry_run and (impact.edits or impact.blocked):
        referrers = dict.fromkeys(x.rel for x in (*impact.edits, *impact.blocked))
        raise HasReferences(entry.rel, tuple(referrers))
    if dry_run:
        return Outcome(impact, applied=False, id=rw.new, rel=entry.rel)
    if mode == "remove" and impact.blocked:
        raise Validation(_blocked_message(impact.blocked))
    skipped = _apply(ws, rw, expected or {}, skip=entry.rel)
    if skipped:  # trashing now would leave Broken References behind
        return Outcome(impact, applied=True, skipped=skipped, id=rw.new, rel=entry.rel)
    replacement_title = rw.new and find(ws, rw.new).title
    done = Deletion(mode, impact.references, len(impact.edits), rw.new, replacement_title)
    trash = ws.store.trash(entry.rel, _stamp(ws), done.record())
    return Outcome(impact, applied=True, id=rw.new, rel=entry.rel, trash=trash)


def _replacement(ws: Workspace, entry: CachedFile, replacement: str | None) -> str:
    noun = entry.type.display_name if entry.type else "Note"
    found = find(ws, replacement) if replacement else None
    if found is None or found.type is not entry.type or found.rel == entry.rel:
        raise Validation(f"Replace with another {noun}")
    return found.id


def _blocked_message(blocked: tuple[Blocker, ...]) -> str:
    where = ", ".join(f"{b.title} ({b.field})" for b in blocked)
    return f"Remove is blocked by required references: {where}. Use Replace with… instead"


def _stamp(ws: Workspace) -> str:
    return ws.clock.now().strftime("%Y%m%d-%H%M%S")


# Trash (§8.4)


@dataclass(frozen=True)
class Deletion:
    """What a delete did to references, kept beside its trash entry (§8.4)."""

    mode: DeleteMode
    references: int  # references rewritten or removed
    files: int  # in this many files
    replacement: str | None = None  # Replace with…: the Id they now name
    replacement_title: str | None = None

    def record(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "references": self.references,
            "files": self.files,
            "replacement": self.replacement,
            "replacement_title": self.replacement_title,
        }

    @classmethod
    def from_record(cls, record: Mapping[str, Any] | None) -> Deletion | None:
        if not record or record.get("mode") not in ("plain", "replace", "remove"):
            return None
        try:
            return cls(
                record["mode"],
                int(record.get("references", 0)),
                int(record.get("files", 0)),
                record.get("replacement") or None,
                record.get("replacement_title") or None,
            )
        except TypeError, ValueError:
            return None


@dataclass(frozen=True)
class RestoreBlock:
    """Why Restore can't succeed now: an Id another file has, or a path that is taken."""

    reason: Literal["id", "path"]
    path: str  # the trashed file whose Id or path is taken
    id: str | None = None
    by: CachedFile | None = None  # the file that has the Id now


@dataclass(frozen=True)
class Trashed:
    entry: str  # the entry's name, to restore it by
    path: str  # what was deleted, at its original path
    files: tuple[str, ...]
    deleted: dt.datetime | None  # read from the entry's name
    type: str = "file"  # an Entity type, "note", "file" (not Markdown) or "folder"
    id: str | None = None  # a deleted Entity's or Note's Id
    title: str = ""
    deletion: Deletion | None = None  # None when the delete wasn't recorded
    blocked: RestoreBlock | None = None


def list_trash(ws: Workspace) -> list[Trashed]:
    """Every delete in the trash, newest first, with what it was, what it did to
    references and whether Restore can succeed now. Trash is never emptied automatically."""
    found = [_trashed(ws, e) for e in ws.store.trash_entries()]
    return sorted(found, key=lambda t: (t.deleted or dt.datetime.min, t.entry), reverse=True)


def _trashed(ws: Workspace, e: TrashEntry) -> Trashed:
    name = PurePosixPath(e.path).name
    kind, id, title = ("folder" if e.folder else "file"), None, name
    if not e.folder and ws.cache.is_indexed(e.path):
        try:
            f = load_file(ws.store.root / TRASH / e.name, e.path)
        except OSError:
            f = None
        if f is not None:
            kind, id, title = f.type or "note", f.id, f.title
    deletion = Deletion.from_record(e.record)
    return Trashed(
        e.name, e.path, e.files, _deleted_at(e.name), kind, id, title, deletion, _blocked(ws, e)
    )


def _blocked(ws: Workspace, e: TrashEntry) -> RestoreBlock | None:
    """The first reason Restore would fail: an Id another file has (the clearer one),
    else a path that is taken."""
    for rel in e.files:
        if ws.cache.is_indexed(rel):
            id = PurePosixPath(rel).stem
            found = ws.cache.resolve(id)
            if found.status != "missing" and (found.file is None or found.file.rel != rel):
                return RestoreBlock("id", rel, id, found.file)
    root = ws.store.root
    for rel in e.files or (e.path,):
        if Path(root, rel).exists() or Path(root, rel).is_symlink():
            return RestoreBlock("path", rel)
    return None


def restore(ws: Workspace, entry: str) -> Trashed:
    """Put a delete back at its original path, only if the path and every Id are free.

    References rewritten by the delete are not restored.
    """
    found = next((t for t in list_trash(ws) if t.entry == entry), None)
    if found is None:
        raise NotFound(f"{TRASH}/{entry}")
    for rel in found.files:
        if ws.cache.is_indexed(rel):
            require_free_id(ws, PurePosixPath(rel).stem)
    ws.store.restore(entry)
    return found


def _deleted_at(name: str) -> dt.datetime | None:
    try:
        return dt.datetime.strptime(name[:15], "%Y%m%d-%H%M%S")
    except ValueError:
        return None


# Broken references and repair (§4.6, §8.5)

ALL_TARGETS: tuple[Target, ...] = (*EntityType, None)


@dataclass(frozen=True)
class Use:
    """One place a Broken Reference is written."""

    rel: str
    id: str | None  # the referring file's Id; None for the Workspace config
    title: str
    type: EntityType | None  # the referring file's type
    field: str  # a frontmatter field, MENTION, or ME
    snippet: tuple[str, str, str] | None = None  # a Mention's words around it: before, it, after

    @property
    def targets(self) -> tuple[Target, ...]:
        """What this use says the Id should be. A Mention says nothing."""
        if self.field == ME:
            return (EntityType.PERSON,)
        if self.field == MENTION:
            return ALL_TARGETS
        return FIELD_BY_NAME[self.type][self.field].targets


@dataclass(frozen=True)
class BrokenGroup:
    id: str
    status: Literal["missing", "ambiguous"]
    uses: tuple[Use, ...]
    claimants: tuple[CachedFile, ...] = ()  # the files that share an ambiguous Id

    @property
    def types(self) -> tuple[Target, ...]:
        """The types every use agrees on: what Replace with… may pick."""
        agreed = set(ALL_TARGETS)
        for use in self.uses:
            agreed &= set(use.targets)
        return tuple(t for t in ALL_TARGETS if t in agreed)

    @property
    def create_types(self) -> tuple[Target, ...]:
        """The types **Create** may make. Empty when the uses disagree, or when the Id is
        ambiguous (a file already has it)."""
        return self.types if self.status == "missing" else ()


def broken_references(ws: Workspace) -> list[BrokenGroup]:
    """Every Broken Reference and ambiguous reference, grouped by Id, ignoring case."""
    groups: dict[str, BrokenGroup] = {}

    def note(id: str, use: Use) -> None:
        found = ws.cache.resolve(id)
        if found.status == "found":
            return
        key = id.casefold()
        group = groups.get(key) or BrokenGroup(id, found.status, ())
        groups[key] = BrokenGroup(group.id, group.status, (*group.uses, use))

    files = ws.cache.files()
    for f in files:
        for ref in f.references:
            note(ref.id, Use(f.rel, f.id, f.title, f.type, ref.field))
        for mention in dict.fromkeys(f.mentions):
            snippet = _mention_snippet(f.body, mention)
            note(mention, Use(f.rel, f.id, f.title, f.type, MENTION, snippet))
    if ws.config.me:
        note(ws.config.me, Use(WORKSPACE_CONFIG, None, CONFIG_TITLE, None, ME))
    claimed: dict[str, list[CachedFile]] = {}
    for f in files:
        if f.ambiguous and f.id.casefold() in groups:
            claimed.setdefault(f.id.casefold(), []).append(f)
    return [
        replace(groups[key], claimants=tuple(sorted(claimed.get(key, ()), key=lambda f: f.rel)))
        for key in sorted(groups)
    ]


SNIPPET_BEFORE = 40
SNIPPET_AFTER = 60


def _mention_snippet(body: str, id: str) -> tuple[str, str, str] | None:
    """The first Mention of `id` in `body`, with the words around it on its line."""
    span = next((m for m in mention_spans(body) if m.id.casefold() == id.casefold()), None)
    if span is None:
        return None
    start = body.rfind("\n", 0, span.start) + 1
    end = body.find("\n", span.end)
    before = body[start : span.start].lstrip()
    after = body[span.end : len(body) if end == -1 else end].rstrip()
    if len(before) > SNIPPET_BEFORE:
        cut = before[-SNIPPET_BEFORE:]
        before = "…" + (cut.split(" ", 1)[1] if " " in cut else cut)
    if len(after) > SNIPPET_AFTER:
        cut = after[:SNIPPET_AFTER]
        after = (cut.rsplit(" ", 1)[0] if " " in cut.strip() else cut) + "…"
    return before, body[span.start : span.end], after


RepairAction = Literal["replace", "remove", "create"]


def repair(
    ws: Workspace,
    id: str,
    action: RepairAction,
    replacement: str | None = None,
    as_type: Target | Literal["infer"] = "infer",
    dry_run: bool = True,
    expected: Mapping[str, str] | None = None,
) -> Outcome:
    """Preview, or apply, one repair of a Broken Reference group: Replace with…, Remove,
    or Create (§8.5).

    No automatic guessing: Create needs every use to agree on the type, or `as_type`
    naming one they allow.
    """
    group = next((g for g in broken_references(ws) if g.id.casefold() == id.casefold()), None)
    if group is None:
        raise NotBroken(id)
    if action == "create":
        return _create_for(ws, group, as_type, dry_run)
    if action == "replace":
        target = find(ws, replacement) if replacement else None
        if target is None:
            raise Validation("Replace with… needs an Entity")
        for use in group.uses:
            if target.type not in use.targets:
                expected_type = describe_targets(use.targets)
                raise UnknownReference(use.field, target.id, expected_type)
        rw = _Rewrite(group.id, target.id)
    else:
        rw = _Rewrite(group.id, None, group.id)
    impact = _impact(ws, rw)
    if dry_run:
        return Outcome(impact, applied=False, id=rw.new)
    if rw.new is None and impact.blocked:
        raise Validation(_blocked_message(impact.blocked))
    skipped = _apply(ws, rw, expected or {})
    return Outcome(impact, applied=True, skipped=skipped, id=rw.new)


def rename_claimant(ws: Workspace, id: str, rel: str, new_id: str) -> str:
    """Give one of the files sharing an ambiguous Id a new Id (§8.5): Rename id… on the
    Broken references page. References stay as written, so they resolve to the file left
    with the Id. Returns the file's new path."""
    group = next((g for g in broken_references(ws) if g.id.casefold() == id.casefold()), None)
    if group is None:
        raise NotBroken(id)
    if rel not in {f.rel for f in group.claimants}:
        raise Validation(f"{rel} doesn't claim the Id {group.id}")
    new_id = _new_id(new_id)
    require_free_id(ws, new_id)
    new_rel = _renamed(rel, new_id)
    ws.store.move(rel, new_rel)
    return new_rel


def _create_for(
    ws: Workspace, group: BrokenGroup, as_type: Target | Literal["infer"], dry_run: bool
) -> Outcome:
    allowed = group.create_types
    if group.status != "missing":
        raise Validation(f"{group.id} names more than one file, so it can't be created")
    if as_type == "infer":
        if len(allowed) != 1:
            why = "pick a type" if allowed else "the references disagree about its type"
            raise Validation(f"Can't create {group.id}: {why}")
        as_type = allowed[0]
    if as_type not in allowed:
        raise Validation(f"Can't create {group.id} as that type: its references need another")
    if dry_run:
        return Outcome(Impact(), applied=False, id=group.id)
    title = group.id.replace("-", " ").strip().title() or group.id
    saved = create_entity(ws, as_type, {"title": title}, id=group.id)
    return Outcome(Impact(), applied=True, id=saved.id, rel=saved.rel)
