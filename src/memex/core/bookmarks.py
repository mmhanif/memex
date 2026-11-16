"""Bookmarks: one per list line of `bookmarks.md` (SPEC §10.1).

    - [Title](https://url) optional note #label #label

A bare `- https://…` line is a Bookmark with no title. Other lines are kept as text.
"""

import re
from dataclasses import dataclass

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
