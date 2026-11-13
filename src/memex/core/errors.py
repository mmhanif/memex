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


class HasReferences(CoreError):
    """Other files refer to what would be deleted (§8.4). `referrers` are their paths."""

    code = "has_references"

    def __init__(self, rel: str, referrers: tuple[str, ...]) -> None:
        n = len(referrers)
        super().__init__(f"{rel} is referred to by {n} file{'' if n == 1 else 's'}")
        self.rel = rel
        self.referrers = referrers


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


class MeNotSet(CoreError):
    """`me` is missing or names no Person (§3.5). Memex never guesses a replacement."""

    code = "me_not_set"

    def __init__(self) -> None:
        super().__init__("Me isn't set: pick or create")


class ReadOnly(CoreError):
    """The Workspace was written by a newer Memex, so it opens read-only (§3.5)."""

    code = "read_only"

    def __init__(self) -> None:
        super().__init__("This Workspace needs a newer Memex: upgrade Memex to edit it")


class UnknownReference(CoreError):
    code = "unknown_reference"

    def __init__(self, field: str, id: str, expected: str) -> None:
        super().__init__(f"{field}: {id!r} is not {expected}")
        self.field = field
        self.id = id
