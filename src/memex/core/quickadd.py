"""Quick-add To-dos: `Title words @owner from @requester due:YYYY-MM-DD` (SPEC §6.3).

Parsed only on the server. The same parser serves the To-dos page, the Person View
boxes, the Ctrl-K `+` prefix and inline capture.
"""

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass

from memex.core.entities import Saved, create_entity
from memex.core.errors import FieldProblem, MeNotSet, Validation
from memex.core.names import match_person
from memex.core.schema import EntityType, parse_date
from memex.core.workspace import Workspace

ME_NOT_SET = "Me isn't set: pick or create"


@dataclass(frozen=True)
class QuickAddError:
    token: str | None  # the token at fault as typed; None for the whole text
    message: str
    candidates: tuple[str, ...] = ()


@dataclass(frozen=True)
class QuickAdd:
    title: str
    owner: str | None
    requester: str | None
    due: dt.date | None
    errors: tuple[QuickAddError, ...] = ()


def parse_quick_add(
    ws: Workspace, text: str, defaults: Mapping[str, str] | None = None
) -> QuickAdd:
    """Parse quick-add text. `defaults` pre-fills `owner`/`requester` by context; typed
    tokens override them, and Me fills whatever is still empty."""
    words = text.split()
    title: list[str] = []
    found: dict[str, str] = {}  # "owner" | "requester" | "due" → the token as typed
    errors: list[QuickAddError] = []

    def take(kind: str, token: str, label: str) -> None:
        if kind in found:
            errors.append(QuickAddError(token, f"Only one {label} per To-do"))
        else:
            found[kind] = token

    i = 0
    while i < len(words):
        word = words[i]
        following = words[i + 1] if i + 1 < len(words) else ""
        if word.casefold() == "from" and _is_at(following):
            take("requester", f"{word} {following}", "from @requester")
            i += 2
            continue
        if _is_at(word):
            take("owner", word, "@owner")
        elif word.casefold().startswith("due:"):
            take("due", word, "due:")
        else:
            title.append(word)
        i += 1

    parties: dict[str, str | None] = {}
    for kind in ("owner", "requester"):
        parties[kind] = (defaults or {}).get(kind) or None
        if kind in found:
            token = found[kind]
            match = match_person(ws, token.split("@", 1)[1])
            parties[kind] = match.id
            if match.id is None:
                errors.append(QuickAddError(token, match.message, match.candidates))

    due = None
    if "due" in found:
        due = parse_date(found["due"][4:])
        if due is None:
            errors.append(QuickAddError(found["due"], "due: needs a real date, YYYY-MM-DD"))

    me = ws.me()
    for kind in ("owner", "requester"):
        if kind not in found and parties[kind] is None:
            if me is None:
                errors.append(QuickAddError(None, ME_NOT_SET))
                break
            parties[kind] = me.id

    joined = " ".join(title)
    if not joined:
        errors.insert(0, QuickAddError(None, "A To-do needs a title"))
    return QuickAdd(joined, parties["owner"], parties["requester"], due, tuple(errors))


def quick_add(ws: Workspace, text: str, defaults: Mapping[str, str] | None = None) -> Saved:
    """Create a To-do from quick-add text with the default To-do Template."""
    parsed = parse_quick_add(ws, text, defaults)
    if any(e.message == ME_NOT_SET for e in parsed.errors):
        raise MeNotSet()
    if parsed.errors:
        problems = [FieldProblem(e.token or "text", e.message) for e in parsed.errors]
        raise Validation("; ".join(p.message for p in problems), problems)
    fields: dict[str, object] = {
        "title": parsed.title,
        "owner": parsed.owner,
        "requester": parsed.requester,
    }
    if parsed.due:
        fields["due"] = parsed.due
    return create_entity(ws, EntityType.TODO, fields)


def _is_at(word: str) -> bool:
    return word.startswith("@") and len(word) > 1
