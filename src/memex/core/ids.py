"""Id rules (SPEC §4.1)."""

import datetime as dt
import re
import unicodedata

_APOSTROPHES = re.compile("['\u2019]")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")

MAX_LENGTH = 60
RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{n}" for n in range(1, 10)}
    | {f"lpt{n}" for n in range(1, 10)}
)


def make_id(title: str, taken: set[str], date: dt.date | None = None) -> str:
    """Generate a free Id for a new file from its title.

    `taken` holds the Ids already in use; comparison is case-insensitive.
    With `date` (To-dos, dated Notes) the Id is prefixed `YYYY-MM-DD-`.
    """
    prefix = f"{date.isoformat()}-" if date else ""
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    slug = _NON_ALNUM.sub("-", _APOSTROPHES.sub("", ascii_title.lower())).strip("-")
    base = prefix + (_truncate(slug, MAX_LENGTH - len(prefix)) or "untitled")
    return _first_free(base, {t.casefold() for t in taken})


def _truncate(slug: str, limit: int) -> str:
    if len(slug) <= limit:
        return slug
    boundary = slug.rfind("-", 0, limit + 1)
    cut = slug[:boundary] if boundary > 0 else slug[:limit]
    return cut.strip("-")


def _first_free(base: str, taken: set[str]) -> str:
    candidate, n = base, 1
    while candidate in RESERVED_NAMES or candidate in taken:
        n += 1
        candidate = f"{base}-{n}"
    return candidate
