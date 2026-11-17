"""Bookmarks: one per list line of `bookmarks.md` (SPEC §10.1).

    - [Title](https://url) optional note #label #label

A bare `- https://…` line is a Bookmark with no title. Other lines are kept as text.
Adding appends one line through the hash-checked write; nothing else is touched.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from memex.core.errors import FieldProblem, Validation
from memex.core.names import fold
from memex.core.workspace import BOOKMARKS, Workspace

_LINKED = re.compile(r"^\s*[-*+]\s+\[([^\]]*)\]\(([^)\s]+)\)\s*(.*?)\s*$")
_BARE = re.compile(r"^\s*[-*+]\s+(https?://\S+)\s*(.*?)\s*$")
_LABEL = re.compile(r"(?:^|\s)#([^\s#]+)")


@dataclass(frozen=True)
class Bookmark:
    line: int  # 1-based line of `bookmarks.md`
    title: str  # "" for a bare URL
    url: str
    note: str
    labels: tuple[str, ...]


def parse_bookmark(text: str, line: int) -> Bookmark | None:
    """The Bookmark on one line, or None when the line is text."""
    if m := _LINKED.match(text):
        title, url, rest = m.groups()
    elif m := _BARE.match(text):
        title = ""
        url, rest = m.groups()
    else:
        return None
    labels = tuple(_LABEL.findall(rest))
    note = " ".join(_LABEL.sub(" ", rest).split())
    return Bookmark(line, title.strip(), url, note, labels)


def parse_bookmarks(text: str) -> list[Bookmark]:
    return [b for n, line in enumerate(text.splitlines(), 1) if (b := parse_bookmark(line, n))]


# The Bookmarks page and Add (§10.1)


@dataclass(frozen=True)
class BookmarkLine:
    """One line of `bookmarks.md`: a Bookmark, or text kept as written."""

    line: int
    text: str
    bookmark: Bookmark | None


@dataclass(frozen=True)
class BookmarksView:
    lines: tuple[BookmarkLine, ...]
    labels: tuple[str, ...]  # every Label in the file, A to Z, for the filter


def bookmarks_view(ws: Workspace, label: str | None = None) -> BookmarksView:
    """Every line, in file order. With `label`, only the Bookmarks carrying it
    (ignoring case and accents, as search's `label:` does)."""
    f = ws.cache.get(BOOKMARKS)
    rows = [
        BookmarkLine(n, text, parse_bookmark(text, n))
        for n, text in enumerate(f.body.splitlines() if f else (), 1)
    ]
    labels: dict[str, str] = {}
    for row in rows:
        for name in row.bookmark.labels if row.bookmark else ():
            labels.setdefault(fold(name), name)
    if label is not None:
        wanted = fold(label)
        rows = [r for r in rows if r.bookmark and any(fold(x) == wanted for x in r.bookmark.labels)]
    return BookmarksView(tuple(rows), tuple(sorted(labels.values(), key=fold)))


_URL = re.compile(r"https?://[^\s()]+", re.IGNORECASE)


def add_bookmark(
    ws: Workspace,
    url: str,
    title: str = "",
    note: str = "",
    labels: Sequence[str] = (),
) -> str:
    """Append one Bookmark line to `bookmarks.md`, rereading and writing under the
    per-path lock (§14.3), leaving every other byte as it was. Returns the new hash."""
    return ws.store.append_line(BOOKMARKS, bookmark_line(url, title, note, labels))


def bookmark_line(url: str, title: str = "", note: str = "", labels: Sequence[str] = ()) -> str:
    """The list line for a Bookmark. Raises Validation for anything that wouldn't
    parse back to the same Bookmark (runs of spaces in the note read back as one)."""
    url, title, note = url.strip(), title.strip(), note.strip()
    names = [name.strip().removeprefix("#") for name in labels]
    problems: list[FieldProblem] = []
    if not _URL.fullmatch(url):
        problems.append(
            FieldProblem("url", "An http:// or https:// address, with no spaces or brackets")
        )
    if "]" in title or "\n" in title:
        problems.append(FieldProblem("title", "One line, with no ]"))
    if "\n" in note or _LABEL.search(note):
        problems.append(FieldProblem("note", "One line, with no #word: put Labels in Labels"))
    if any(not n or any(c.isspace() or c == "#" for c in n) for n in names):
        problems.append(FieldProblem("labels", "Each Label is one word, with no #"))
    if problems:
        raise Validation("That Bookmark can't be added", problems)
    head = f"[{title}]({url})" if title else url
    return " ".join(["-", head, *(note.split() if note else ()), *(f"#{n}" for n in names)])
