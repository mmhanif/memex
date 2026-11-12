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
from memex.core.errors import BadPath, Conflict, Exists, Locked, NotFound, Validation
from memex.core.paths import resolve_workspace_path

BOM = b"\xef\xbb\xbf"


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
    def __init__(self, root: Path, on_change: Callable[[str], None] | None = None) -> None:
        """`on_change(rel)` runs after each successful write, e.g. `Cache.refresh`."""
        self.root = root
        self._on_change = on_change
        self._locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)
        self._locks_guard = threading.Lock()

    def read(self, rel: str) -> FileVersion:
        return _version(_read_bytes(resolve_workspace_path(self.root, rel), rel))

    def create(self, rel: str, text: str) -> str:
        """Create a new `.md` file (UTF-8, LF, trailing newline). Fails with `exists`."""
        path = self._markdown_path(rel)
        with self._lock(path):
            if path.exists() or path.is_symlink():
                raise Exists(rel)
            raw = NEW_FILE_SHAPE.encode(text if text.endswith("\n") else text + "\n")
            path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(path, raw, rel)
            self._changed(rel)
            return content_hash(raw)

    def write(self, rel: str, text: str, expected_hash: str) -> str:
        path = self._markdown_path(rel)
        with self._lock(path):
            current = _read_bytes(path, rel)
            if content_hash(current) != expected_hash:
                raise Conflict(rel, _version(current))
            raw = _Shape.of(current).encode(text)
            _atomic_write(path, raw, rel)
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
        path = self._markdown_path(rel)
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
            _atomic_write(path, raw, rel)
            self._changed(rel)
            return content_hash(raw)

    def _changed(self, rel: str) -> None:
        if self._on_change is not None:
            self._on_change(rel)

    def _markdown_path(self, rel: str) -> Path:
        if not rel.endswith(".md"):
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


def decode(raw: bytes) -> str:
    """File bytes as app text: UTF-8, BOM removed, LF line endings."""
    return _Shape.of(raw).decode(raw)


def _version(raw: bytes) -> FileVersion:
    return FileVersion(text=_Shape.of(raw).decode(raw), hash=content_hash(raw))


def _atomic_write(path: Path, raw: bytes, rel: str) -> None:
    """Write via a temp file in the same folder, then swap it in (§5.4)."""
    tmp = path.with_name(f".{path.name}.memex-tmp-{secrets.token_hex(6)}")
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
