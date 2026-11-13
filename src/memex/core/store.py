"""Hash-checked atomic writes (SPEC §5.3, §5.4)."""

import hashlib
import os
import secrets
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from memex.core import frontmatter
from memex.core.errors import BadPath, Conflict, Exists, Locked, NotFound, ReadOnly, Validation
from memex.core.paths import is_within, resolve_workspace_path

BOM = b"\xef\xbb\xbf"
WORKSPACE_CONFIG = ".memex/config.yaml"  # the one non-`.md` file the Store writes
TRASH = ".memex/trash"
TEMP_MARKER = ".memex-tmp-"  # in atomic writes' temp names; the watcher ignores them


@dataclass(frozen=True)
class FileVersion:
    """A file as the app sees it: text with LF line endings and no BOM, plus its hash."""

    text: str
    hash: str


@dataclass(frozen=True)
class _Shape:
    """How a file's bytes are laid out, so a save can keep it (§5.4)."""

    bom: bool
    newline: str

    @staticmethod
    def of(raw: bytes) -> _Shape:
        first_lf = raw.find(b"\n")
        crlf = first_lf > 0 and raw[first_lf - 1 : first_lf] == b"\r"
        return _Shape(bom=raw.startswith(BOM), newline="\r\n" if crlf else "\n")

    def decode(self, raw: bytes) -> str:
        text = raw.removeprefix(BOM).decode("utf-8")
        return text.replace("\r\n", "\n") if self.newline == "\r\n" else text

    def encode(self, text: str) -> bytes:
        raw = text.replace("\n", self.newline).encode("utf-8")
        return BOM + raw if self.bom else raw


NEW_FILE_SHAPE = _Shape(bom=False, newline="\n")

# Windows: os.replace fails while another program holds the target open (§5.4).
REPLACE_ATTEMPTS = 5
REPLACE_BACKOFF_S = 0.2


def content_hash(raw: bytes) -> str:
    """The version token: SHA-256 of the raw bytes, lowercase hex."""
    return hashlib.sha256(raw).hexdigest()


class Store:
    def __init__(
        self,
        root: Path,
        on_change: Callable[[str], None] | None = None,
        read_only: bool = False,
    ) -> None:
        """`on_change(rel)` runs after each successful write, e.g. `Cache.refresh`.

        A `read_only` Store refuses every write with `read_only` (§3.5).
        """
        self.root = root
        self.read_only = read_only
        self._on_change = on_change
        self._locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)
        self._locks_guard = threading.Lock()

    def read(self, rel: str) -> FileVersion:
        return _version(_read_bytes(resolve_workspace_path(self.root, rel), rel))

    def create(self, rel: str, text: str) -> str:
        """Create a new `.md` file (UTF-8, LF, trailing newline). Fails with `exists`.

        Empty text makes an empty (0-byte) file: it has no last line to end.
        """
        path = self._writable_path(rel)
        with self._lock(path):
            if path.exists() or path.is_symlink():
                raise Exists(rel)
            raw = NEW_FILE_SHAPE.encode(text if text.endswith("\n") or not text else text + "\n")
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(path, raw, rel)
            self._changed(rel)
            return content_hash(raw)

    def make_folder(self, rel: str, exist_ok: bool = True) -> None:
        """Create a folder (and any missing parents, the Workspace root included)."""
        if self.read_only:
            raise ReadOnly()
        path = resolve_workspace_path(self.root, rel)
        if not exist_ok and (path.exists() or Path(self.root, rel).is_symlink()):
            raise Exists(rel)
        path.mkdir(parents=True, exist_ok=True)

    def write(self, rel: str, text: str, expected_hash: str) -> str:
        path = self._writable_path(rel)
        with self._lock(path):
            current = _read_bytes(path, rel)
            if content_hash(current) != expected_hash:
                raise Conflict(rel, _version(current))
            raw = _Shape.of(current).encode(text)
            atomic_write(path, raw, rel)
            self._changed(rel)
            return content_hash(raw)

    def update_fields(
        self,
        rel: str,
        expected_hash: str,
        set: Mapping[str, Any] | None = None,
        unset: Iterable[str] = (),
    ) -> str:
        """Hash-checked frontmatter edit through ruamel round-trip; the body is untouched."""
        path = self._writable_path(rel)
        with self._lock(path):
            current = _read_bytes(path, rel)
            if content_hash(current) != expected_hash:
                raise Conflict(rel, _version(current))
            shape = _Shape.of(current)
            try:
                text = frontmatter.with_fields(shape.decode(current), set, unset)
            except frontmatter.FrontmatterError as e:
                raise Validation(f"{rel}: frontmatter doesn't parse ({e.message})") from None
            raw = shape.encode(text)
            atomic_write(path, raw, rel)
            self._changed(rel)
            return content_hash(raw)

    def move(self, src: str, dst: str, overwrite: bool = False) -> None:
        """Move or rename a file or folder (R14). Links are never moved (R13).

        `overwrite` replaces an existing file at `dst`, never a folder.
        """
        if self.read_only:
            raise ReadOnly()
        source = self._existing(src)
        is_folder = source.is_dir()
        if not is_folder and not (src.endswith(".md") and dst.endswith(".md")):
            raise BadPath(dst, "only .md files can be moved, and they stay .md")
        target = resolve_workspace_path(self.root, dst)
        same = os.path.normcase(source) == os.path.normcase(target)  # a case-only rename
        if is_folder and not same and is_within(source, target):
            raise BadPath(dst, "a folder can't move into itself")
        taken = not same and (target.exists() or target.is_symlink())
        if taken and (not overwrite or is_folder or target.is_dir()):
            raise Exists(dst)
        with self._lock(source):
            target.parent.mkdir(parents=True, exist_ok=True)
            _replace_with_retry(source, target, src)
        self._changed(src)
        self._changed(dst)

    def trash(self, rel: str, stamp: str) -> str:
        """Move a file or folder to `.memex/trash/<stamp>/<rel>` (§8.4); return that path.

        A link inside a trashed folder moves as a link; its target is never touched (R13).
        """
        if self.read_only:
            raise ReadOnly()
        source = self._existing(rel)
        entry, n = f"{TRASH}/{stamp}/{rel}", 1
        while (self.root / entry).exists() or (self.root / entry).is_symlink():
            n += 1
            entry = f"{TRASH}/{stamp}-{n}/{rel}"
        target = self.root / entry
        with self._lock(source):
            target.parent.mkdir(parents=True, exist_ok=True)
            _replace_with_retry(source, target, rel)
        self._changed(rel)
        return entry

    def _existing(self, rel: str) -> Path:
        """An existing file or folder that is not itself a link."""
        if Path(self.root, rel).is_symlink():
            raise BadPath(rel, "links can't be moved or deleted")
        path = resolve_workspace_path(self.root, rel)
        if not path.exists():
            raise NotFound(rel)
        return path

    def _changed(self, rel: str) -> None:
        if self._on_change is not None:
            self._on_change(rel)

    def _writable_path(self, rel: str) -> Path:
        """`.md` files, plus the Workspace config so Settings saves are hash-checked too."""
        if self.read_only:
            raise ReadOnly()
        if not rel.endswith(".md") and rel != WORKSPACE_CONFIG:
            raise BadPath(rel, "only .md files can be written")
        return resolve_workspace_path(self.root, rel)

    def _lock(self, path: Path) -> threading.Lock:
        with self._locks_guard:
            return self._locks[os.path.normcase(path)]


def _read_bytes(path: Path, rel: str) -> bytes:
    try:
        return path.read_bytes()
    except FileNotFoundError, IsADirectoryError:
        raise NotFound(rel) from None
    except PermissionError:
        if path.is_dir():  # how Windows reports opening a folder
            raise NotFound(rel) from None
        raise


def decode(raw: bytes) -> str:
    """File bytes as app text: UTF-8, BOM removed, LF line endings."""
    return _Shape.of(raw).decode(raw)


def _version(raw: bytes) -> FileVersion:
    return FileVersion(text=_Shape.of(raw).decode(raw), hash=content_hash(raw))


def atomic_write(path: Path, raw: bytes, rel: str) -> None:
    """Write via a temp file in the same folder, then swap it in (§5.4)."""
    tmp = path.with_name(f".{path.name}{TEMP_MARKER}{secrets.token_hex(6)}")
    try:
        with open(tmp, "xb") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        _replace_with_retry(tmp, path, rel)
    finally:
        tmp.unlink(missing_ok=True)


def _replace_with_retry(tmp: Path, path: Path, rel: str) -> None:
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt + 1 < REPLACE_ATTEMPTS:
                time.sleep(REPLACE_BACKOFF_S)
    raise Locked(rel)
