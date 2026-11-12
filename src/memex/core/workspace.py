"""Opening a Workspace, Setup and adoption, and the format check (SPEC §3)."""

import contextlib
import os
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from ruamel.yaml.comments import CommentedSeq

from memex.core import frontmatter
from memex.core.cache import Cache, CachedFile
from memex.core.clock import Clock, SystemClock
from memex.core.config import (
    ConfigError,
    ConfigUnparseable,
    WorkspaceConfig,
    parse_workspace_config,
    with_keys,
)
from memex.core.errors import (
    BadPath,
    Conflict,
    Exists,
    HasReferences,
    MeNotSet,
    NotFound,
    UnknownReference,
    Validation,
)
from memex.core.ids import make_id
from memex.core.paths import is_within
from memex.core.schema import EntityType
from memex.core.store import WORKSPACE_CONFIG, Store

FORMAT = 1  # the Workspace format this Memex reads and writes


class Workspace:
    def __init__(
        self,
        root: Path,
        config: WorkspaceConfig,
        config_error: ConfigError | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.root = root
        self.clock = clock or SystemClock()
        self.config = config
        self.config_error = config_error
        self.read_only = config.format > FORMAT
        self.store = Store(root, on_change=self.changed, read_only=self.read_only)
        self.cache = Cache.build(root, config.ignore)

    @classmethod
    def open(cls, root: Path, clock: Clock | None = None) -> Workspace:
        text = Store(root).read(WORKSPACE_CONFIG).text
        return cls(root, *parse_workspace_config(text), clock=clock)

    def changed(self, rel: str) -> None:
        """A path changed on disk, from our own write or a watcher hint."""
        if rel == WORKSPACE_CONFIG:
            self._reload_config()
        else:
            self.cache.refresh(rel)

    def _reload_config(self) -> None:
        """Outside edits apply live (§3.2); a new `ignore` rebuilds the Cache."""
        old_ignore = self.config.ignore
        try:
            text = self.store.read(WORKSPACE_CONFIG).text
        except NotFound:
            self.config, self.config_error = (
                WorkspaceConfig(),
                ConfigError("config is missing", None),
            )
        else:
            self.config, self.config_error = parse_workspace_config(text)
        if self.config.ignore != old_ignore:
            self.cache = Cache.build(self.root, self.config.ignore)

    def move(self, src: str, dst: str, overwrite: bool = False) -> None:
        """Files-page Rename/move (§11.8). Typed Entities can't leave their folder."""
        _check_files_page_path(src)
        _check_files_page_path(dst)
        src_folder = PurePosixPath(src).parent.as_posix()
        entity_type = EntityType.for_folder(src_folder)
        if entity_type and PurePosixPath(dst).parent.as_posix() != src_folder:
            raise BadPath(dst, f"a {entity_type} stays in {src_folder}/")
        self.store.move(src, dst, overwrite)

    def trash(self, rel: str) -> str:
        """Files-page Delete (§8.4, §11.8): to trash, unless something outside refers in.

        Returns the trash entry's path. The guided delete with an impact preview
        (Replace with… / Remove references) is not here yet.
        """
        _check_files_page_path(rel)
        doomed = self.cache.under(rel)
        gone = {f.rel for f in doomed}
        if (me := self.me()) is not None and me.rel in gone:
            raise Validation("Me can't be deleted: change Me in Settings first")
        referrers = [f.rel for f in self.cache.referrers(f.id for f in doomed) if f.rel not in gone]
        if referrers:
            raise HasReferences(rel, tuple(referrers))
        return self.store.trash(rel, self.clock.now().strftime("%Y%m%d-%H%M%S"))

    def config_hash(self) -> str:
        return self.store.read(WORKSPACE_CONFIG).hash

    def save_config(
        self,
        expected_hash: str,
        set: Mapping[str, Any] | None = None,
        unset: Iterable[str] = (),
    ) -> str:
        """Hash-checked Settings save (§3.6). Refused while the config doesn't parse."""
        if self.config_error is not None:
            raise Validation(
                f"{WORKSPACE_CONFIG} doesn't parse (line {self.config_error.line}): "
                "fix it by hand before saving Settings"
            )
        current = self.store.read(WORKSPACE_CONFIG)
        if current.hash != expected_hash:
            raise Conflict(WORKSPACE_CONFIG, current)
        try:
            text = with_keys(current.text, set, unset)
        except ConfigUnparseable as e:
            raise Validation(f"{WORKSPACE_CONFIG} doesn't parse: {e.error.message}") from None
        return self.store.write(WORKSPACE_CONFIG, text, expected_hash)

    def me(self) -> CachedFile | None:
        """The Person `me` names, or None when it is missing, ambiguous or not a Person."""
        if not self.config.me:
            return None
        found = self.cache.resolve(self.config.me)
        if found.file is None or found.file.type is not EntityType.PERSON:
            return None
        return found.file

    def require_me(self) -> CachedFile:
        if (me := self.me()) is None:
            raise MeNotSet()
        return me


def _check_files_page_path(rel: str) -> None:
    """Type folders stay put, and dot-folders (`.memex`, `.git`, …) aren't the app's to touch."""
    if EntityType.for_folder(rel):
        raise BadPath(rel, "type folders can't be moved or deleted")
    if any(part.startswith(".") for part in PurePosixPath(rel).parts):
        raise BadPath(rel, "hidden files and folders can't be moved or deleted")


# Setup (§3.4)

SEED_FOLDERS = (*(t.folder for t in EntityType), "notes")
BOOKMARKS = "bookmarks.md"


@dataclass(frozen=True)
class NewMe:
    """Setup's "Your name": a new Person file for Me."""

    name: str


@dataclass(frozen=True)
class SetupScan:
    """What adopting a folder would find. Scanning writes nothing."""

    notes: int
    persons: tuple[CachedFile, ...]

    @property
    def summary(self) -> str:
        return f"{_count(self.notes, 'Note')}, {_count(len(self.persons), 'Person')}"


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def scan_setup(root: Path, install_dir: Path | None = None) -> SetupScan:
    check_setup_path(root, install_dir)
    files = Cache.build(root).files()
    return SetupScan(
        notes=sum(1 for f in files if f.type is None),
        persons=tuple(f for f in files if f.type is EntityType.PERSON),
    )


def apply_setup(
    root: Path,
    me: NewMe | str,
    clock: Clock | None = None,
    install_dir: Path | None = None,
) -> Workspace:
    """Make `root` a Workspace, adopting what is there. `me` is a new name or a Person's Id.

    Nothing that exists is moved or rewritten. The config is written last, because
    its presence is what makes a folder a Workspace.
    """
    check_setup_path(root, install_dir)
    clock = clock or SystemClock()
    cache = Cache.build(root)
    if isinstance(me, str):
        _check_existing_person(cache, me)
    store = Store(root)
    for folder in SEED_FOLDERS:
        store.make_folder(folder)
    with contextlib.suppress(Exists):
        store.create(BOOKMARKS, "")
    me_id = _create_me(store, cache, me, clock) if isinstance(me, NewMe) else me
    store.create(WORKSPACE_CONFIG, with_keys("", {"format": FORMAT, "me": me_id}))
    return Workspace.open(root, clock)


def check_setup_path(root: Path, install_dir: Path | None = None) -> None:
    """The Setup page's checks on its path (§3.4). Raises Validation."""
    real = Path(os.path.realpath(root))
    install = Path(os.path.realpath(install_dir or sys.prefix))
    if is_within(install, real):
        raise Validation("That folder is inside Memex's install folder: pick another")
    if (real / WORKSPACE_CONFIG).exists():
        raise Validation("That folder is already a Workspace")
    if any((ancestor / WORKSPACE_CONFIG).exists() for ancestor in real.parents):
        raise Validation("That folder is inside another Workspace: pick another")
    nearest = next(p for p in (real, *real.parents) if p.exists())
    if not (nearest.is_dir() and os.access(nearest, os.W_OK | os.X_OK)):
        raise Validation("That folder is not writable: pick another")


def _check_existing_person(cache: Cache, id: str) -> None:
    found = cache.resolve(id)
    if found.file is None or found.file.type is not EntityType.PERSON:
        raise UnknownReference("me", id, "a Person in that folder")


def _create_me(store: Store, cache: Cache, me: NewMe, clock: Clock) -> str:
    me_id = make_id(me.name, {f.id for f in cache.files()})
    kind = CommentedSeq(["team-member"])
    kind.fa.set_flow_style()
    fields = {"title": me.name, "kind": kind, "created": clock.today()}
    store.create(f"{EntityType.PERSON.folder}/{me_id}.md", frontmatter.with_fields("", fields))
    return me_id
