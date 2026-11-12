"""The conflict banner's side-by-side line diff (SPEC §5.7). No three-way merge."""

import difflib
from dataclasses import dataclass
from itertools import zip_longest
from typing import Literal

RowKind = Literal["equal", "replace", "delete", "insert"]


@dataclass(frozen=True)
class DiffRow:
    """One line pair: `disk` on the left, `mine` on the right; None where one side has none."""

    kind: RowKind
    disk: str | None
    mine: str | None


def side_by_side(disk: str, mine: str) -> list[DiffRow]:
    left, right = disk.splitlines(), mine.splitlines()
    rows: list[DiffRow] = []
    matcher = difflib.SequenceMatcher(a=left, b=right, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        for a, b in zip_longest(left[i1:i2], right[j1:j2]):
            kind: RowKind = "equal" if tag == "equal" else _kind(a, b)
            rows.append(DiffRow(kind, a, b))
    return rows


def _kind(disk: str | None, mine: str | None) -> RowKind:
    if disk is None:
        return "insert"
    if mine is None:
        return "delete"
    return "replace"
