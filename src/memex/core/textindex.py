"""Text matching for search (SPEC §9.2, §9.3), kept fast enough for the §9.1 budget.

Everything here is derived from the parse cache, in memory, and updated per file when
its hash moves; nothing is written anywhere. Each file keeps its folded names, fields
and body, and gets a small id. A sorted vocabulary maps every folded word to the set
of ids whose text holds it, as an int bitmask: a word-prefix test is a bisect plus an
OR of masks, and terms combine with `&`. Names match by fuzzy subsequence with one
regex over all the names. Phrases and terms with punctuation take candidates from the
vocabulary and are then checked against the folded text of those candidates only.
"""

import bisect
import re
import threading
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from memex.core.cache import CachedFile
from memex.core.names import fold, rank_folded

# Where a query matched, best first: these are the search tiers they give (§9.5).
EXACT = 1  # the whole query is the Id or title
PREFIX = 2  # the whole query starts the Id or title
NAME = 3  # Id or title, fuzzy subsequence
ALIAS = 4
FIELD = 5  # Labels, Person role/organisation/email
BODY = 6

_WORD = re.compile(r"[^\W_]+")
_FIELD_TEXT = ("role", "organisation", "email")


@dataclass(frozen=True)
class Term:
    text: str  # folded
    phrase: bool = False

    @property
    def plain(self) -> bool:
        """A single word: letters and digits only."""
        return not self.phrase and _WORD.fullmatch(self.text) is not None


Place = tuple[int, int]  # (NAME…BODY, closeness within NAME: lower is closer)


def find_term(term: Term, text: str, start: int = 0) -> int:
    """Where `term` first matches in folded `text` at or after `start`, else -1."""
    return (find_phrase if term.phrase else find_word_prefix)(term.text, text, start)


def find_word_prefix(term: str, text: str, start: int = 0) -> int:
    """Where `term` first starts a word of `text`, else -1."""
    i = text.find(term, start)
    while i >= 0:
        if i == 0 or not text[i - 1].isalnum() or not term[0].isalnum():
            return i
        i = text.find(term, i + 1)
    return -1


def find_phrase(phrase: str, text: str, start: int = 0) -> int:
    """Where `phrase` first appears as whole words in `text`, else -1."""
    i = find_word_prefix(phrase, text, start)
    while i >= 0:
        end = i + len(phrase)
        if end == len(text) or not text[end].isalnum() or not phrase[-1].isalnum():
            return i
        i = find_word_prefix(phrase, text, i + 1)
    return -1


@dataclass(frozen=True)
class _Doc:
    id: int
    hash: str
    names: tuple[str, str]  # Id, title
    aliases: tuple[str, ...]
    fields: tuple[str, ...]
    body: str
    words: str  # every word of all its text, once each, space-separated


def _fold_file(id: int, f: CachedFile) -> _Doc:
    names = (fold(f.id), fold(f.title))
    aliases = tuple(fold(a) for a in texts(f.fields.get("aliases")))
    values = (*texts(f.fields.get("labels")), *(str(f.fields.get(k) or "") for k in _FIELD_TEXT))
    fields = tuple(fold(v) for v in values if v)
    body = fold(f.body)
    words = set(_WORD.findall(body))
    for text in (*names, *aliases, *fields):
        words.update(_WORD.findall(text))
    return _Doc(id, f.hash, names, aliases, fields, body, " ".join(words))


def texts(value: object) -> list[str]:
    """The strings of a YAML list; nothing for anything else."""
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


class _Lines:
    """Short texts, one per line, each owned by a document id."""

    def __init__(self, entries: Iterable[tuple[int, str]]) -> None:
        self.starts: list[int] = []
        self.owners: list[int] = []
        parts: list[str] = []
        at = 0
        for owner, text in entries:
            self.starts.append(at)
            self.owners.append(owner)
            parts.append(text)
            at += len(text) + 1
        self.text = "\n".join(parts)

    def _owner(self, pos: int) -> int:
        return self.owners[bisect.bisect_right(self.starts, pos) - 1]

    def fuzzy(self, q: str) -> set[int]:
        pattern = re.compile("[^\n]*?".join(map(re.escape, q)))
        return {self._owner(m.start()) for m in pattern.finditer(self.text)}

    def word_prefix(self, q: str) -> set[int]:
        found: set[int] = set()
        i = find_word_prefix(q, self.text)
        while i >= 0:
            found.add(self._owner(i))
            i = find_word_prefix(q, self.text, i + 1)
        return found


def _ids(mask: int) -> list[int]:
    """The ids set in a bitmask."""
    bits = bin(mask)[:1:-1]
    return [i for i, bit in enumerate(bits) if bit == "1"]


@dataclass(frozen=True)
class _View:
    """The index as one call sees it: positions in the caller's file list by id."""

    generation: object
    position: dict[int, int]  # doc id → position in `files`
    docs: dict[int, _Doc]  # by id
    names: _Lines
    aliases: _Lines
    fields: _Lines


class TextIndex:
    """Folded text for one Cache's files, kept in step with their hashes."""

    def __init__(self) -> None:
        self._docs: dict[str, _Doc] = {}  # by path
        self._free: list[int] = []  # ids of removed files, for reuse
        self._next_id = 0
        self._postings: dict[str, int] = {}  # word → bitmask of doc ids
        self._vocabulary: list[str] = []  # the words of `_postings`, sorted
        self._view: _View | None = None
        self._lock = threading.Lock()

    def match(
        self, files: Sequence[CachedFile], terms: Sequence[Term], generation: object
    ) -> dict[int, Place]:
        """For each of `files` (by position) that every term matches: its weakest place,
        and its closeness summed over terms matched by name. Terms must be non-empty.
        `generation` changes whenever `files` might have: the index resyncs then."""
        with self._lock:
            view = self._sync(files, generation)
            found: dict[int, Place] | None = None  # by doc id
            for term in terms:
                places = self._places(view, term, found)
                if found is None:
                    found = places
                else:
                    found = {
                        i: (max(found[i][0], p[0]), found[i][1] + p[1])
                        for i, p in places.items()
                        if i in found
                    }
                if not found:
                    return {}
            whole = " ".join(t.text for t in terms)
            return {
                view.position[i]: _whole_query(view.docs[i], whole) or p
                for i, p in (found or {}).items()
            }

    # Matching

    def _places(self, view: _View, term: Term, among: dict[int, Place] | None) -> dict[int, Place]:
        """Where `term` matches in each document (of `among`, when given)."""
        if term.plain:
            return self._scan(view, term.text)
        mask = self._candidates(term)
        if among is not None:
            mask &= sum(1 << i for i in among)
        return {
            i: place for i in _ids(mask) if (place := _place_in(view.docs[i], term)) is not None
        }

    def _scan(self, view: _View, q: str) -> dict[int, Place]:
        """A single word against every document."""
        places: dict[int, Place] = {}
        for i in view.names.fuzzy(q):
            rank = rank_folded(q, view.docs[i].names)
            if rank is not None:
                places[i] = (NAME, rank[0] * 1000 + rank[1])
        for i in view.aliases.fuzzy(q):
            places.setdefault(i, (ALIAS, 0))
        for i in view.fields.word_prefix(q):
            places.setdefault(i, (FIELD, 0))
        for i in _ids(self._prefixed(q)):
            places.setdefault(i, (BODY, 0))
        return places

    def _prefixed(self, prefix: str) -> int:
        """The documents holding a word that starts with `prefix`."""
        mask = 0
        at = bisect.bisect_left(self._vocabulary, prefix)
        for word in self._vocabulary[at:]:
            if not word.startswith(prefix):
                break
            mask |= self._postings[word]
        return mask

    def _candidates(self, term: Term) -> int:
        """Documents holding every word of a phrase or punctuated term: all but the last
        as whole words, the last as a prefix unless it's a phrase."""
        parts = _WORD.findall(term.text)
        mask = (1 << self._next_id) - 1
        for n, part in enumerate(parts):
            whole = term.phrase or n < len(parts) - 1
            mask &= self._postings.get(part, 0) if whole else self._prefixed(part)
            if not mask:
                break
        return mask

    # Keeping in step with the cache

    def warm(self, files: Sequence[CachedFile], generation: object) -> None:
        """Bring the index up to date now, so the next search doesn't wait for it."""
        with self._lock:
            self._sync(files, generation)

    def folded_body(self, f: CachedFile) -> str | None:
        """The folded body of `f`, if the index holds this version of it."""
        with self._lock:
            doc = self._docs.get(f.rel)
            return doc.body if doc is not None and doc.hash == f.hash else None

    def _sync(self, files: Sequence[CachedFile], generation: object) -> _View:
        if self._view is not None and self._view.generation == generation:
            return self._view
        current = {f.rel for f in files}
        for rel in [r for r in self._docs if r not in current]:
            self._remove(self._docs.pop(rel))
        for f in files:
            old = self._docs.get(f.rel)
            if old is not None and old.hash == f.hash:
                continue
            if old is not None:
                self._remove(old)
            self._docs[f.rel] = self._add(f)
        docs = {self._docs[f.rel].id: self._docs[f.rel] for f in files}
        self._view = _View(
            generation,
            {self._docs[f.rel].id: n for n, f in enumerate(files)},
            docs,
            _Lines((i, n) for i, d in docs.items() for n in d.names),
            _Lines((i, a) for i, d in docs.items() for a in d.aliases),
            _Lines((i, v) for i, d in docs.items() for v in d.fields),
        )
        return self._view

    def _add(self, f: CachedFile) -> _Doc:
        if self._free:
            id = self._free.pop()
        else:
            id = self._next_id
            self._next_id += 1
        doc = _fold_file(id, f)
        bit = 1 << id
        for word in doc.words.split():
            if word not in self._postings:
                bisect.insort(self._vocabulary, word)
                self._postings[word] = bit
            else:
                self._postings[word] |= bit
        return doc

    def _remove(self, doc: _Doc) -> None:
        keep = ~(1 << doc.id)
        for word in doc.words.split():
            mask = self._postings[word] & keep
            if mask:
                self._postings[word] = mask
            else:
                del self._postings[word]
                del self._vocabulary[bisect.bisect_left(self._vocabulary, word)]
        self._free.append(doc.id)


def _whole_query(doc: _Doc, whole: str) -> Place | None:
    """Tiers 1 and 2: the whole query is the Id or title, or starts it."""
    id, title = doc.names
    hyphenated = whole.replace(" ", "-")
    if whole in doc.names or hyphenated == id:
        return (EXACT, 0)
    if title.startswith(whole) or id.startswith(hyphenated):
        return (PREFIX, 0)
    return None


def _place_in(doc: _Doc, term: Term) -> Place | None:
    """Where a phrase or punctuated term best matches one document."""
    q = term.text
    if term.phrase:
        if any(find_phrase(q, n) >= 0 for n in doc.names):
            return (NAME, 0)
        if any(find_phrase(q, a) >= 0 for a in doc.aliases):
            return (ALIAS, 0)
    else:
        if (rank := rank_folded(q, doc.names)) is not None:
            return (NAME, rank[0] * 1000 + rank[1])
        if rank_folded(q, doc.aliases) is not None:
            return (ALIAS, 0)
    if any(find_term(term, v) >= 0 for v in doc.fields):
        return (FIELD, 0)
    return (BODY, 0) if find_term(term, doc.body) >= 0 else None
