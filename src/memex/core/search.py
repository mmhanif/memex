"""Search: one engine over the parse cache, shared by REST and MCP (SPEC §9).

A query is free text plus filter tokens. Text terms must all match (AND), ignoring
case and accents. Names (Id, title, aliases) match by fuzzy subsequence; everything
else by word-prefix; `"quoted phrases"` match exactly. Hits are ranked in tiers (§9.5).
"""

import datetime as dt
import re
import threading
import weakref
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from typing import Literal, cast

from memex.core.bookmarks import Bookmark, parse_bookmarks
from memex.core.cache import Cache, CachedFile
from memex.core.entities import refers
from memex.core.names import fold, match_person
from memex.core.schema import TODO_STATUSES, WORK_STATUSES, EntityType, parse_date
from memex.core.textindex import BODY, NAME, Term, TextIndex, find_term, texts
from memex.core.views import due_of, end_of_week
from memex.core.workspace import BOOKMARKS, Workspace

# Tiers (§9.5): where the text matched, EXACT … BODY (see `textindex`). 0 is a query of
# only filters: everything that passes ranks alike.
FILTERS_ONLY = 0


FilterKind = Literal["type", "status", "person", "label", "due"]


@dataclass(frozen=True)
class Filter:
    """One filter token. Its `values` combine with OR; filters combine with AND (§9.4)."""

    kind: FilterKind
    values: tuple[str, ...]
    token: str  # as typed


@dataclass(frozen=True)
class TokenError:
    token: str
    message: str
    candidates: tuple[str, ...] = ()


@dataclass(frozen=True)
class Query:
    terms: tuple[Term, ...]
    filters: tuple[Filter, ...]
    errors: tuple[TokenError, ...]

    @property
    def text(self) -> str:
        """The free text, without the filter tokens."""
        return " ".join(f'"{t.text}"' if t.phrase else t.text for t in self.terms)


@dataclass(frozen=True)
class Snippet:
    """One line holding a match, with `highlights` as [start, end) spans of `text`."""

    text: str
    highlights: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class Hit:
    file: CachedFile  # for a Bookmark, `bookmarks.md`
    tier: int
    closeness: int = 0  # within the fuzzy tier, lower is closer
    snippets: tuple[Snippet, ...] = ()
    bookmark: Bookmark | None = None

    @property
    def id(self) -> str:
        return self.file.id

    @property
    def type(self) -> str:
        return type_key(self.file, self.bookmark)


@dataclass(frozen=True)
class SearchResult:
    hits: tuple[Hit, ...]  # the page asked for
    total: int  # every hit, not just the page
    counts: dict[str, int]  # every hit by type: "project", …, "note", "bookmark"
    query: Query

    @property
    def filters(self) -> tuple[Filter, ...]:
        return self.query.filters

    @property
    def errors(self) -> tuple[TokenError, ...]:
        return self.query.errors


def search(
    ws: Workspace,
    query: str,
    limit: int = 50,
    offset: int = 0,
    include_archived: bool = True,
    hide_completed: bool = False,
    types: Iterable[str] = (),
) -> SearchResult:
    """Ranked hits for `query`. Archived and finished items are demoted, not hidden,
    unless `include_archived` is off or `hide_completed` is on (an explicit `status:`
    filter overrides `hide_completed`). `types` narrows like a `type:` token. A token
    error means no hits (§9.4)."""
    types = list(types)
    parsed = parse_query(ws, f"{query} type:{','.join(types)}" if types else query)
    if parsed.errors or not (parsed.terms or parsed.filters):
        return SearchResult((), 0, {}, parsed)
    hide_completed = hide_completed and not any(f.kind == "status" for f in parsed.filters)
    today = ws.clock.today()
    index = _index_for(ws.cache)
    generation = ws.cache.generation  # read first: a change after this resyncs next time
    files = [f for f in ws.cache.files() if f.rel != BOOKMARKS]
    # Text first, over every file so the index stays whole; then the filters on what matched.
    if parsed.terms:
        places = index.text.match(files, parsed.terms, generation)
        matched = [
            (files[i], tier, closeness if tier == NAME else 0)
            for i, (tier, closeness) in places.items()
        ]
    else:
        matched = [(f, FILTERS_ONLY, 0) for f in files]
    ranked: list[tuple[tuple[int, int, int, float, str, int], Hit | CachedFile]] = []
    counts: dict[str, int] = {}
    for f, tier, closeness in matched:
        kind, group = index.meta(f)
        if (not include_archived and f.fields.get("archived")) or (hide_completed and group == 2):
            continue
        if all(_passes(flt, f, None, today) for flt in parsed.filters):
            ranked.append(((tier, closeness, group, -f.mtime, f.rel, 0), f))
            counts[kind] = counts.get(kind, 0) + 1
    if (bookmarks := ws.cache.get(BOOKMARKS)) is not None:
        for hit in _bookmark_hits(index, bookmarks, parsed, today):
            ranked.append((_rank_key(hit), hit))
            counts["bookmark"] = counts.get("bookmark", 0) + 1
    ranked.sort(key=lambda r: r[0])
    page = tuple(
        _with_snippets(_as_hit(key, item), parsed.terms, index)
        for key, item in ranked[offset : offset + limit]
    )
    return SearchResult(page, len(ranked), counts, parsed)


def _as_hit(key: tuple[int, int, int, float, str, int], item: Hit | CachedFile) -> Hit:
    return item if isinstance(item, Hit) else Hit(item, key[0], key[1])


def warm(ws: Workspace) -> None:
    """Build the text index ahead of the first search: on a 50 MB Workspace that takes
    seconds. Searches meanwhile wait for it rather than build their own."""
    generation = ws.cache.generation
    files = [f for f in ws.cache.files() if f.rel != BOOKMARKS]
    _index_for(ws.cache).text.warm(files, generation)


# Query parsing (server-only, §9.1)

_TOKEN = re.compile(r'"([^"]*)"?|(\S+)')
_DUE_COMPARE = re.compile(r"^due([<>])(.*)$", re.IGNORECASE)
_DUE_WORDS = ("overdue", "today", "this-week", "none")
_TYPE_ALIASES = {"glossary": "glossary-term", "to-do": "todo"}
TYPE_KEYS = (*(t.value for t in EntityType), "note", "bookmark")
STATUSES = tuple(dict.fromkeys((*WORK_STATUSES, *TODO_STATUSES, "archived")))


def parse_query(ws: Workspace, query: str) -> Query:
    terms: list[Term] = []
    filters: list[Filter] = []
    errors: list[TokenError] = []
    for m in _TOKEN.finditer(query):
        phrase, word = m.group(1), m.group(2)
        if word is not None:
            parsed = _filter_token(ws, word)
            if isinstance(parsed, Filter):
                filters.append(parsed)
                continue
            if isinstance(parsed, TokenError):
                errors.append(parsed)
                continue
        text = fold(" ".join((phrase if phrase is not None else word or "").split()))
        if any(c.isalnum() for c in text):
            terms.append(Term(text, phrase is not None))
    return Query(tuple(terms), tuple(filters), tuple(errors))


def _filter_token(ws: Workspace, word: str) -> Filter | TokenError | None:
    """The filter `word` spells, the error in it, or None when it is plain text."""
    if word.startswith("@") and len(word) > 1:
        match = match_person(ws, word[1:])
        if match.id is None:
            return TokenError(word, match.message, match.candidates)
        return Filter("person", (match.id,), word)
    if compare := _DUE_COMPARE.match(word):
        op, value = compare.groups()
        if parse_date(value) is None:
            return TokenError(word, f"{word}: due{op} needs a real date, YYYY-MM-DD")
        return Filter("due", (f"{op}{value}",), word)
    key, colon, rest = word.partition(":")
    key = key.casefold()
    if not colon or key not in ("type", "status", "label", "due"):
        return None
    values = tuple(v.strip() for v in rest.split(",") if v.strip())
    if not values:
        return TokenError(word, f"{key}: needs a value")
    if key == "type":
        values = tuple(_TYPE_ALIASES.get(v.casefold(), v.casefold()) for v in values)
        allowed = TYPE_KEYS
    elif key == "status":
        values = tuple(v.casefold() for v in values)
        allowed = STATUSES
    elif key == "due":
        values = tuple(v.casefold() for v in values)
        allowed = _DUE_WORDS
    else:
        return Filter("label", values, word)
    if bad := [v for v in values if v not in allowed]:
        return TokenError(word, f"{key}: {bad[0]!r} isn't one of {', '.join(allowed)}", allowed)
    return Filter(cast(FilterKind, key), values, word)


# Filters

# Frontmatter references the `@person` filter follows: never Mentions (§4.4, §9.4).
PERSON_FIELDS = ("lead", "team", "stakeholders", "owner", "requester", "people", "manager")


def _passes(flt: Filter, f: CachedFile, bookmark: Bookmark | None, today: dt.date) -> bool:
    match flt.kind:
        case "type":
            return type_key(f, bookmark) in flt.values
        case "status":
            if bookmark is not None:
                return False
            return any(_has_status(f, v) for v in flt.values)
        case "person":
            return bookmark is None and refers(f, PERSON_FIELDS, flt.values[0])
        case "label":
            labels = bookmark.labels if bookmark else texts(f.fields.get("labels"))
            wanted = {fold(v) for v in flt.values}
            return any(fold(label) in wanted for label in labels)
        case "due":
            due = None if bookmark else due_of(f)
            return any(_due_matches(v, due, f, today) for v in flt.values)


def _has_status(f: CachedFile, value: str) -> bool:
    if value == "archived":
        return bool(f.fields.get("archived"))
    return f.fields.get("status") == value


def _due_matches(value: str, due: dt.date | None, f: CachedFile, today: dt.date) -> bool:
    if value == "none":
        return due is None
    if due is None:
        return False
    if value[0] in "<>":
        bound = parse_date(value[1:])
        assert bound is not None
        return due < bound if value[0] == "<" else due > bound
    if value == "today":
        return due == today
    if value == "overdue":
        return due < today and status_group(f) != 2
    return today <= due <= end_of_week(today)  # this-week


def type_key(f: CachedFile, bookmark: Bookmark | None = None) -> str:
    if bookmark is not None:
        return "bookmark"
    return f.type.value if f.type else "note"


# Per-Cache state: the text index, and the folded Bookmarks of `bookmarks.md`.


class _Index:
    def __init__(self) -> None:
        self.text = TextIndex()
        self._bookmarks: tuple[str, list[tuple[Bookmark, str]]] = ("", [])
        self._meta: dict[str, tuple[str, str, int]] = {}  # rel → (hash, type key, group)
        self._lock = threading.Lock()

    def meta(self, f: CachedFile) -> tuple[str, int]:
        """A file's type key and status group, remembered per version (frontmatter
        lookups are slow, and ranking needs them for every hit)."""
        found = self._meta.get(f.rel)
        if found is None or found[0] != f.hash:
            found = self._meta[f.rel] = (f.hash, type_key(f), status_group(f))
        return found[1], found[2]

    def bookmarks(self, f: CachedFile) -> list[tuple[Bookmark, str]]:
        """Each Bookmark in `f`, with its title, URL, note and Labels folded into one text."""
        with self._lock:
            if self._bookmarks[0] != f.hash:
                found = [
                    (b, fold(" ".join((b.title, b.url, b.note, *(f"#{x}" for x in b.labels)))))
                    for b in parse_bookmarks(f.body)
                ]
                self._bookmarks = (f.hash, found)
            return self._bookmarks[1]


_INDEXES: weakref.WeakKeyDictionary[Cache, _Index] = weakref.WeakKeyDictionary()
_INDEXES_LOCK = threading.Lock()


def _index_for(cache: Cache) -> _Index:
    with _INDEXES_LOCK:
        index = _INDEXES.get(cache)
        if index is None:
            index = _INDEXES[cache] = _Index()
        return index


# Matching


def _bookmark_hits(index: _Index, f: CachedFile, query: Query, today: dt.date) -> list[Hit]:
    """Bookmarks rank with body text (§9.6 "In text"), in file order."""
    hits = []
    for bookmark, text in index.bookmarks(f):
        if not all(_passes(flt, f, bookmark, today) for flt in query.filters):
            continue
        if all(find_term(t, text) >= 0 for t in query.terms):
            tier = BODY if query.terms else FILTERS_ONLY
            hits.append(Hit(f, tier, bookmark=bookmark))
    return hits


# Ranking (§9.5)

_GROUPS = {
    "on-hold": 1,
    "blocked": 1,
    "done": 2,
    "cancelled": 2,
}


def status_group(f: CachedFile) -> int:
    """0 open/active/not-started (and Themes, Notes), 1 on-hold/blocked, 2 finished or archived."""
    if f.fields.get("archived"):
        return 2
    status = f.fields.get("status")
    return _GROUPS.get(status, 0) if isinstance(status, str) else 0


def _rank_key(h: Hit) -> tuple[int, int, int, float, str, int]:
    line = h.bookmark.line if h.bookmark else 0
    return (h.tier, h.closeness, status_group(h.file), -h.file.mtime, h.file.rel, line)


# Snippets

SNIPPET_WIDTH = 160
MAX_SNIPPETS = 2


def _with_snippets(h: Hit, terms: Sequence[Term], index: _Index) -> Hit:
    if h.bookmark is not None:
        line = h.file.body.splitlines()[h.bookmark.line - 1]
        found = snippets(line, terms, 1) or [Snippet(line.strip(), ())]
        return replace(h, snippets=tuple(found))
    if h.tier != BODY:
        return h
    found = snippets(h.file.body, terms, folded=index.text.folded_body(h.file))
    return replace(h, snippets=tuple(found))


def snippets(
    text: str, terms: Iterable[Term], limit: int = MAX_SNIPPETS, folded: str | None = None
) -> list[Snippet]:
    """Up to `limit` lines of `text` holding a match, matches marked. `folded` is
    `fold(text)` when at hand, to find the lines without folding each one."""
    terms = list(terms)
    lines = text.split("\n")
    if folded is None or folded.count("\n") != len(lines) - 1:
        folded = "\n".join(fold(line) for line in lines)
    found: list[Snippet] = []
    for n in _matching_lines(folded, terms, limit):
        line = lines[n].removesuffix("\r")
        folded_line, starts = _fold_with_map(line)
        spans = []
        for term in terms:
            i = find_term(term, folded_line)
            while i >= 0:
                spans.append((starts[i], starts[i + len(term.text) - 1] + 1))
                i = find_term(term, folded_line, i + 1)
        if spans:
            found.append(_trim(line, sorted(spans)))
    return found


def _matching_lines(folded: str, terms: Sequence[Term], limit: int) -> list[int]:
    """The numbers of the first `limit` lines of `folded` where any term matches."""
    found: list[int] = []
    at = 0
    while len(found) < limit:
        hits = [p for t in terms if (p := find_term(t, folded, at)) >= 0]
        if not hits:
            break
        first = min(hits)
        found.append(folded.count("\n", 0, first))
        at = folded.find("\n", first) + 1
        if at == 0:
            break
    return found


def _fold_with_map(line: str) -> tuple[str, list[int]]:
    """`fold(line)`, and for each folded character the index of the original it came from."""
    parts: list[str] = []
    starts: list[int] = []
    for i, c in enumerate(line):
        piece = fold(c)
        parts.append(piece)
        starts.extend([i] * len(piece))
    return "".join(parts), starts


def _trim(line: str, spans: list[tuple[int, int]]) -> Snippet:
    first = spans[0][0]
    begin = max(0, min(first - 40, len(line) - SNIPPET_WIDTH))
    end = min(len(line), begin + SNIPPET_WIDTH)
    shown = line[begin:end]
    kept = tuple(
        (max(s, begin) - begin, min(e, end) - begin) for s, e in spans if s < end and e > begin
    )
    lead = "…" if begin > 0 else ""
    tail = "…" if end < len(line) else ""
    shift = len(lead)
    return Snippet(lead + shown + tail, tuple((s + shift, e + shift) for s, e in kept))


# The muted context line on a result row (§9.6)


def context_of(ws: Workspace, f: CachedFile) -> str:
    """A Project's Theme, a Deliverable's Project, a To-do's Owner → Requester, or a
    Note's folder; empty for the rest. References that don't resolve show as written."""

    def name(field: str) -> str:
        ref = f.fields.get(field)
        if not isinstance(ref, str) or not ref:
            return ""
        found = ws.cache.resolve(ref).file
        return found.title if found else ref

    match f.type:
        case EntityType.PROJECT:
            return name("theme")
        case EntityType.DELIVERABLE:
            return name("project")
        case EntityType.TODO:
            return f"{name('owner')} → {name('requester')}"
        case None:
            return PurePosixPath(f.rel).parent.as_posix().removeprefix(".")
        case _:
            return ""
