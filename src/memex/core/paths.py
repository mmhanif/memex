"""The path gate (SPEC §5.1): the only way any surface reaches the filesystem."""

import os
import re
from pathlib import Path

from memex.core.errors import BadPath
from memex.core.ids import RESERVED_NAMES

_DRIVE = re.compile(r"^[A-Za-z]:")
_FORBIDDEN_CHARS = set('<>"|?*:\\')


def resolve_workspace_path(root: Path, rel: str) -> Path:
    """Check `rel` lexically, then resolve it and require it to stay inside `root`.

    Every link along the way is followed, dangling ones included, so a target
    that doesn't exist yet is judged by where it would really be created.
    """
    _check_lexical(rel)
    real_root = Path(os.path.realpath(root))
    real = Path(os.path.realpath(real_root / rel))
    if not is_within(real_root, real):
        raise BadPath(rel, "outside the Workspace")
    return real


def _check_lexical(rel: str) -> None:
    if not rel:
        raise BadPath(rel, "empty path")
    if _DRIVE.match(rel):
        raise BadPath(rel, "drive letter")
    if rel.startswith("/"):
        raise BadPath(rel, "absolute path")
    for segment in rel.split("/"):
        _check_segment(rel, segment)


def _check_segment(rel: str, segment: str) -> None:
    if segment in ("", ".", ".."):
        raise BadPath(rel, "empty, '.' or '..' segment")
    if bad := _FORBIDDEN_CHARS.intersection(segment):
        raise BadPath(rel, f"forbidden character {sorted(bad)[0]!r}")
    if any(ord(c) < 32 or ord(c) == 127 for c in segment):
        raise BadPath(rel, "control character")
    if segment[-1] in ". ":
        raise BadPath(rel, "segment ends in '.' or space")
    if segment.split(".", 1)[0].rstrip(" ").casefold() in RESERVED_NAMES:
        raise BadPath(rel, "reserved device name")


def is_within(root: Path, path: Path) -> bool:
    a, b = os.path.normcase(root), os.path.normcase(path)
    return os.path.commonpath([a, b]) == a
