"""Frontmatter splitter and ruamel.yaml round-trip editing (SPEC §5.2, §5.3).

Works on text with LF line endings and no BOM; the Store handles file bytes.
"""

import io
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.error import MarkedYAMLError, YAMLError

FENCE = "---"


@dataclass(frozen=True)
class Split:
    """A Note's text cut into its frontmatter block and body."""

    yaml: str | None  # None: the file has no frontmatter block
    body: str


def split(text: str) -> Split:
    """The file starts with a `---` line; frontmatter ends at the next `---` line."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\n") != FENCE:
        return Split(yaml=None, body=text)
    for i, line in enumerate(lines[1:], start=1):
        if line.rstrip("\n") == FENCE:
            return Split(yaml="".join(lines[1:i]), body="".join(lines[i + 1 :]))
    return Split(yaml=None, body=text)


class FrontmatterError(Exception):
    def __init__(self, message: str, line: int | None) -> None:
        super().__init__(message)
        self.message = message
        self.line = line  # 1-based line number in the file, when known


def parse(text: str) -> tuple[CommentedMap, Split]:
    """Parse a Note's frontmatter. A file without frontmatter yields an empty map.

    Raises FrontmatterError when the block isn't a YAML mapping.
    """
    parts = split(text)
    if parts.yaml is None or not parts.yaml.strip():
        return CommentedMap(), parts
    try:
        data = _yaml().load(parts.yaml)
    except MarkedYAMLError as e:
        mark = e.problem_mark or e.context_mark
        line = mark.line + 2 if mark else None  # +1 for 1-based, +1 for the opening fence
        raise FrontmatterError(str(e.problem or e), line) from None
    except YAMLError as e:
        raise FrontmatterError(str(e), None) from None
    if data is None:
        return CommentedMap(), parts
    if not isinstance(data, CommentedMap):
        raise FrontmatterError("frontmatter is not a mapping of fields", 2)
    return data, parts


def with_fields(text: str, set: Mapping[str, Any] | None = None, unset: Iterable[str] = ()) -> str:
    """Return `text` with fields set or removed; every body byte is kept.

    New keys go at the end of the existing frontmatter. Raises FrontmatterError
    if the existing frontmatter doesn't parse.
    """

    def change(data: CommentedMap) -> None:
        for key, value in (set or {}).items():
            data[key] = value
        for key in unset:
            data.pop(key, None)

    return edited(text, change)


def edited(text: str, change: Callable[[CommentedMap], None]) -> str:
    """Return `text` with its frontmatter changed in place by `change`; every body byte is kept.

    Editing the round-trip map in place keeps comments, quoting and list styles.
    Raises FrontmatterError if the existing frontmatter doesn't parse.
    """
    data, parts = parse(text)
    change(data)
    out = io.StringIO()
    if data:
        _yaml().dump(data, out)
    return f"{FENCE}\n{out.getvalue()}{FENCE}\n{parts.body}"


def _yaml() -> YAML:
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.width = 4096
    return yaml
