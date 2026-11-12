"""Core error types. Each carries the API error `code` of SPEC §17.1.

Messages hold Workspace-relative paths only, never absolute ones (§5.1).
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from memex.core.store import FileVersion


class CoreError(Exception):
    code: str = "error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class BadPath(CoreError):
    code = "bad_path"

    def __init__(self, rel: str, reason: str) -> None:
        super().__init__(f"Bad path {rel!r}: {reason}")
        self.rel = rel
        self.reason = reason


class Conflict(CoreError):
    """The file changed since the caller read it. Carries what is on disk now."""

    code = "conflict"

    def __init__(self, rel: str, current: FileVersion) -> None:
        super().__init__(f"{rel} changed on disk")
        self.rel = rel
        self.current = current


class Exists(CoreError):
    code = "exists"

    def __init__(self, rel: str) -> None:
        super().__init__(f"{rel} already exists")
        self.rel = rel


class Locked(CoreError):
    """Another program holds the file open, so it can't be replaced (Windows)."""

    code = "locked"

    def __init__(self, rel: str) -> None:
        super().__init__(f"{rel} is locked by another program")
        self.rel = rel


class Validation(CoreError):
    code = "validation"


class NotFound(CoreError):
    code = "not_found"

    def __init__(self, rel: str) -> None:
        super().__init__(f"{rel} not found")
        self.rel = rel
