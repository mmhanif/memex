"""The in-memory parse cache of every indexed `.md` file (SPEC §5.2).

An optimisation only: the Store's hash check is authoritative.
"""

import os
import re
import threading
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from memex.core import frontmatter
from memex.core.errors import BadPath
from memex.core.paths import resolve_workspace_path
from memex.core.schema import REFERENCE_FIELDS, EntityType, check_fields
from memex.core.store import content_hash, decode

_HEADING = re.compile(r"^# (.+?)\s*$", re.MULTILINE)
_MENTION = re.compile(r"\[\[([^\[\]\n]+?)\]\]")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_INLINE_CODE = re.compile(r"(?<!`)(`+)(?!`).+?(?<!`)\1(?!`)", re.DOTALL)


@dataclass(frozen=True)
class FileWarning:
    """A problem found reading a file. Flagged where shown; never fixed (§4.5)."""

    kind: str  # "parse", "encoding", "validation"
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
        # Request threads and the watcher thread share the cache.
        self._lock = threading.RLock()
        self.generation = 0  # moves on every change, so derived state can tell it is stale

    @classmethod
    def build(cls, root: Path, ignore: Sequence[str] = ()) -> Cache:
        cache = cls(root, ignore)
        for rel in cache._walk():
            cache._load_into(rel)
        return cache

    def get(self, rel: str) -> CachedFile | None:
        with self._lock:
            entry = self._files.get(rel)
            return entry and self._with_ambiguity(entry)

    def files(self) -> list[CachedFile]:
        with self._lock:
            return [self._with_ambiguity(self._files[rel]) for rel in sorted(self._files)]

    def folders(self) -> list[str]:
        """Folders for the tree: never dot-folders, ignored ones or links (R13)."""
        found: list[str] = []
        for dirpath, dirnames, _ in os.walk(self.root, followlinks=False):
            kept = []
            for name in dirnames:
                rel = Path(dirpath, name).relative_to(self.root).as_posix()
                if self._in_tree(rel):
                    kept.append(name)
                    found.append(rel)
            dirnames[:] = kept
        return sorted(found)

    def other_files(self) -> list[str]:
        """Non-Markdown files for the tree, shown read-only (§2): the same skips as folders."""
        found: list[str] = []
        for dirpath, dirnames, filenames in os.walk(self.root, followlinks=False):
            dirnames[:] = [
                d
                for d in dirnames
                if self._in_tree(Path(dirpath, d).relative_to(self.root).as_posix())
            ]
            for name in filenames:
                rel = Path(dirpath, name).relative_to(self.root).as_posix()
                if not name.endswith(".md") and self._in_tree(rel):
                    found.append(rel)
        return sorted(found)

    def _in_tree(self, rel: str) -> bool:
        path = PurePosixPath(rel)
        return (
            not path.name.startswith(".")
            and not os.path.islink(self.root / rel)
            and not any(path.full_match(glob) for glob in self.ignore)
        )

    def resolve(self, id: str) -> Resolution:
        """Look up an Id, ignoring case. Ambiguous Ids resolve to nothing."""
        with self._lock:
            rels = self._by_id.get(id.casefold(), set())
            if not rels:
                return Resolution("missing")
            if len(rels) > 1:
                return Resolution("ambiguous")
            [rel] = rels
            return Resolution("found", self.get(rel))

    def under(self, rel: str) -> list[CachedFile]:
        """The file at `rel`, or every indexed file inside the folder `rel`."""
        with self._lock:
            prefix = f"{rel}/"
            return [self._files[r] for r in sorted(self._files) if r == rel or r.startswith(prefix)]

    def referrers(self, ids: Iterable[str]) -> list[CachedFile]:
        """Files with a reference or Mention naming any of `ids`, ignoring case."""
        wanted = {i.casefold() for i in ids}
        return [
            f
            for f in self.files()
            if wanted.intersection(
                [r.id.casefold() for r in f.references] + [m.casefold() for m in f.mentions]
            )
        ]

    def refresh(self, rel: str) -> None:
        """Reread one path after a write or a watcher hint; drop what's gone.

        `rel` may be a folder (moved, deleted or new): everything under it is reread.
        """
        with self._lock:
            self._drop(rel)
            prefix = f"{rel}/"
            for under in [r for r in self._files if r.startswith(prefix)]:
                self._drop(under)
            path = self.root / rel
            if path.is_dir() and not path.is_symlink() and self._contained(rel):
                for found in self._walk(path):
                    self._load_into(found)
            elif self.is_indexed(rel) and self._contained(rel):
                self._load_into(rel)

    def _load_into(self, rel: str) -> None:
        try:
            entry = load_file(self.root, rel)
        except FileNotFoundError, IsADirectoryError, NotADirectoryError:
            return  # gone (or never a file) by the time we looked: a later hint catches up
        self._put(entry)

    def _drop(self, rel: str) -> None:
        self.generation += 1
        entry = self._files.pop(rel, None)
        if entry is not None:
            key = entry.id.casefold()
            self._by_id[key].discard(rel)
            if not self._by_id[key]:
                del self._by_id[key]

    def _put(self, entry: CachedFile) -> None:
        self.generation += 1
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

    def _walk(self, top: Path | None = None) -> Iterator[str]:
        """Indexed paths. Links are never descended; linked files must stay inside."""
        for dirpath, dirnames, filenames in os.walk(top or self.root, followlinks=False):
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


def load_file(root: Path, rel: str) -> CachedFile:
    """Parse the file at `root/rel` as the index would (also used for files in trash)."""
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
        warnings=tuple(
            FileWarning("validation", e.message) for e in check_fields(base.type, fields)
        ),
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
    return tuple(m.id for m in mention_spans(body))


@dataclass(frozen=True)
class MentionSpan:
    """One `[[id]]` in a body: where it is (`start`, `end`) and the Id it names."""

    start: int
    end: int
    id: str


def mention_spans(body: str) -> list[MentionSpan]:
    """Every Mention in `body`, outside fenced and inline code (SPEC Appendix A.7)."""
    masked = _INLINE_CODE.sub(lambda m: _blank(m.group()), without_fenced_code(body))
    return [MentionSpan(m.start(), m.end(), m.group(1).strip()) for m in _MENTION.finditer(masked)]


def _blank(text: str) -> str:
    """Same length, line breaks kept, everything else a space: offsets stay valid."""
    return "".join(c if c == "\n" else " " for c in text)


def without_fenced_code(body: str) -> str:
    """`body` with fenced code blanked out (same length)."""
    kept: list[str] = []
    fence: str | None = None
    for line in body.splitlines(keepends=True):
        opener = _FENCE.match(line)
        if fence is None and opener:
            fence = opener.group(1)
            kept.append(_blank(line))
        elif fence is not None:
            if opener and opener.group(1)[0] == fence[0] and len(opener.group(1)) >= len(fence):
                fence = None
            kept.append(_blank(line))
        else:
            kept.append(line)
    return "".join(kept)
