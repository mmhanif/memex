"""The in-memory parse cache of every indexed `.md` file (SPEC §5.2).

An optimisation only: the Store's hash check is authoritative.
"""

import os
import re
from collections import defaultdict
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from memex.core import frontmatter
from memex.core.errors import BadPath
from memex.core.paths import resolve_workspace_path
from memex.core.schema import REFERENCE_FIELDS, EntityType
from memex.core.store import content_hash, decode

_HEADING = re.compile(r"^# (.+?)\s*$", re.MULTILINE)
_MENTION = re.compile(r"\[\[([^\[\]\n]+?)\]\]")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_INLINE_CODE = re.compile(r"(?<!`)(`+)(?!`).+?(?<!`)\1(?!`)", re.DOTALL)


@dataclass(frozen=True)
class FileWarning:
    """A problem found reading a file. Flagged where shown; never fixed (§4.5)."""

    kind: str  # "parse", "encoding"
    message: str
    line: int | None = None


@dataclass(frozen=True)
class Reference:
    """A frontmatter field naming another file by Id."""

    field: str
    id: str


@dataclass(frozen=True)
class CachedFile:
    rel: str
    id: str
    type: EntityType | None  # None: a Note
    hash: str
    mtime: float
    fields: Mapping[str, Any]
    title: str
    body: str
    warnings: tuple[FileWarning, ...] = ()
    read_only: bool = False
    references: tuple[Reference, ...] = ()
    mentions: tuple[str, ...] = ()  # Ids written as [[id]] in the body, outside code
    ambiguous: bool = False  # another file has the same Id, ignoring case (§4.1)


@dataclass(frozen=True)
class Resolution:
    """What an Id names: one file, several (ambiguous), or nothing (missing)."""

    status: Literal["found", "ambiguous", "missing"]
    file: CachedFile | None = None


class Cache:
    def __init__(self, root: Path, ignore: Sequence[str] = ()) -> None:
        self.root = root
        self.ignore = tuple(ignore)
        self._files: dict[str, CachedFile] = {}
        self._by_id: defaultdict[str, set[str]] = defaultdict(set)

    @classmethod
    def build(cls, root: Path, ignore: Sequence[str] = ()) -> Cache:
        cache = cls(root, ignore)
        for rel in cache._walk():
            cache._load_into(rel)
        return cache

    def get(self, rel: str) -> CachedFile | None:
        entry = self._files.get(rel)
        return entry and self._with_ambiguity(entry)

    def files(self) -> list[CachedFile]:
        return [self._with_ambiguity(self._files[rel]) for rel in sorted(self._files)]

    def resolve(self, id: str) -> Resolution:
        """Look up an Id, ignoring case. Ambiguous Ids resolve to nothing."""
        rels = self._by_id.get(id.casefold(), set())
        if not rels:
            return Resolution("missing")
        if len(rels) > 1:
            return Resolution("ambiguous")
        [rel] = rels
        return Resolution("found", self.get(rel))

    def refresh(self, rel: str) -> None:
        """Reread one path after a write or a watcher hint; drop it if it's gone."""
        self._drop(rel)
        if self.is_indexed(rel) and self._contained(rel):
            self._load_into(rel)

    def _load_into(self, rel: str) -> None:
        try:
            entry = _load(self.root, rel)
        except FileNotFoundError, IsADirectoryError, NotADirectoryError:
            return  # gone (or never a file) by the time we looked: a later hint catches up
        self._put(entry)

    def _drop(self, rel: str) -> None:
        entry = self._files.pop(rel, None)
        if entry is not None:
            key = entry.id.casefold()
            self._by_id[key].discard(rel)
            if not self._by_id[key]:
                del self._by_id[key]

    def _put(self, entry: CachedFile) -> None:
        self._files[entry.rel] = entry
        self._by_id[entry.id.casefold()].add(entry.rel)

    def _with_ambiguity(self, entry: CachedFile) -> CachedFile:
        ambiguous = len(self._by_id.get(entry.id.casefold(), ())) > 1
        return replace(entry, ambiguous=ambiguous) if ambiguous else entry

    def is_indexed(self, rel: str) -> bool:
        """Whether `rel` belongs in the index: a `.md` file outside dot-folders and `ignore`."""
        parts = PurePosixPath(rel).parts
        return (
            rel.endswith(".md")
            and not any(part.startswith(".") for part in parts)
            and not any(PurePosixPath(rel).full_match(glob) for glob in self.ignore)
        )

    def _walk(self) -> Iterator[str]:
        """Indexed paths. Links are never descended; linked files must stay inside."""
        for dirpath, dirnames, filenames in os.walk(self.root, followlinks=False):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for name in filenames:
                rel = Path(dirpath, name).relative_to(self.root).as_posix()
                if self.is_indexed(rel) and self._contained(rel):
                    yield rel

    def _contained(self, rel: str) -> bool:
        try:
            resolve_workspace_path(self.root, rel)
        except BadPath:
            return False
        return True


def _load(root: Path, rel: str) -> CachedFile:
    path = root / rel
    raw = path.read_bytes()
    pure = PurePosixPath(rel)
    base = CachedFile(
        rel=rel,
        id=pure.stem,
        type=EntityType.for_folder(pure.parent.as_posix()),
        hash=content_hash(raw),
        mtime=path.stat().st_mtime,
        fields={},
        title=pure.stem,
        body="",
    )
    try:
        text = decode(raw)
    except UnicodeDecodeError:
        warning = FileWarning("encoding", "Not UTF-8: opened read-only")
        return replace(base, warnings=(warning,), read_only=True)
    try:
        fields, parts = frontmatter.parse(text)
    except frontmatter.FrontmatterError as e:
        warning = FileWarning("parse", f"Frontmatter doesn't parse: {e.message}", e.line)
        return replace(base, body=frontmatter.split(text).body, warnings=(warning,))
    return replace(
        base,
        fields=fields,
        title=_title(fields, parts.body, pure.stem),
        body=parts.body,
        references=_references(base.type, fields),
        mentions=_mentions(parts.body),
    )


def _references(entity_type: EntityType | None, fields: Mapping[str, Any]) -> tuple[Reference, ...]:
    refs: list[Reference] = []
    for field in REFERENCE_FIELDS[entity_type]:
        value = fields.get(field)
        values = value if isinstance(value, list) else [value]
        refs.extend(Reference(field, v) for v in values if isinstance(v, str) and v)
    return tuple(refs)


def _title(fields: Mapping[str, Any], body: str, stem: str) -> str:
    """`title` field, else the first `# ` heading, else the filename (§4.2)."""
    title = fields.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    if heading := _HEADING.search(body):
        return heading.group(1)
    return stem


def _mentions(body: str) -> tuple[str, ...]:
    prose = _INLINE_CODE.sub(" ", _without_fenced_code(body))
    return tuple(m.group(1).strip() for m in _MENTION.finditer(prose))


def _without_fenced_code(body: str) -> str:
    kept: list[str] = []
    fence: str | None = None
    for line in body.splitlines(keepends=True):
        opener = _FENCE.match(line)
        if fence is None and opener:
            fence = opener.group(1)
        elif fence is not None:
            if opener and opener.group(1)[0] == fence[0] and len(opener.group(1)) >= len(fence):
                fence = None
        else:
            kept.append(line)
    return "".join(kept)
