"""Name matching for Persons named by `@token` (SPEC §6.3, §9.3).

Case and accents are ignored. Ranked in tiers: exact Id or title, then Id or title
starting with the query, then a word of the title starting with it, then fuzzy
subsequence (`dmig` → `data-migration`), tighter matches first.
"""

import functools
import sys
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

from memex.core.cache import CachedFile
from memex.core.schema import EntityType
from memex.core.workspace import Workspace

Rank = tuple[int, int]


def fold(text: str) -> str:
    """`text` for comparing ignoring case and accents: "José" → "jose", "Straße" → "strasse".

    Compatibility-decomposed, every mark (Unicode category M, as `\\p{M}` in the
    browser's fold() in static/app/text.js) dropped, then case-folded. The browser
    folds by the same rule; tests/fold_cases.py holds the cases both are checked on.
    """
    if text.isascii():
        return text.lower()  # the same as casefold for ASCII, and much faster
    return unicodedata.normalize("NFKD", text).translate(_marks()).casefold()


@functools.cache
def _marks() -> dict[int, None]:
    """A `str.translate` table deleting every mark (built once, when needed)."""
    return {
        c: None for c in range(sys.maxunicode + 1) if unicodedata.category(chr(c)).startswith("M")
    }


def name_rank(query: str, names: Iterable[str]) -> Rank | None:
    """How well `query` matches the best of `names`; lower is better, None is no match."""
    return rank_folded(fold(query), [fold(n) for n in names])


def rank_folded(q: str, names: Iterable[str]) -> Rank | None:
    """`name_rank` for a query and names already folded."""
    if not q:
        return None
    return min((r for n in names if (r := _rank(q, n)) is not None), default=None)


def _rank(q: str, name: str) -> Rank | None:
    if name == q:
        return (0, 0)
    if name.startswith(q):
        return (1, 0)
    if any(word.startswith(q) for word in name.replace("-", " ").split()):
        return (2, 0)
    if (span := _subsequence_span(q, name)) is not None:
        return (3, span)
    return None


def _subsequence_span(q: str, name: str) -> int | None:
    """The length of the shortest stretch of `name` holding `q`'s characters in order."""
    best: int | None = None
    for start, c in enumerate(name):
        if c != q[0]:
            continue
        pos = start
        for ch in q[1:]:
            pos = name.find(ch, pos + 1)
            if pos < 0:
                return best
        span = pos - start + 1
        best = span if best is None else min(best, span)
    return best


@dataclass(frozen=True)
class PersonMatch:
    """The Person a token names, or the reason it names none."""

    id: str | None
    message: str = ""
    candidates: tuple[str, ...] = ()


def match_person(ws: Workspace, token: str) -> PersonMatch:
    """Resolve `token` (without the `@`) to one non-archived Person, or say why not."""
    ranked: list[tuple[Rank, CachedFile]] = []
    for f in ws.cache.files():
        if f.type is not EntityType.PERSON or f.ambiguous or f.fields.get("archived"):
            continue
        if (rank := name_rank(token, (f.id, f.title))) is not None:
            ranked.append((rank, f))
    if not ranked:
        return PersonMatch(None, f"No Person matches @{token}")
    best = min(rank for rank, _ in ranked)
    top = sorted((f.id for rank, f in ranked if rank == best), key=str.casefold)
    if len(top) > 1:
        return PersonMatch(None, f"@{token} could be {', '.join(top)}", tuple(top))
    return PersonMatch(top[0])
