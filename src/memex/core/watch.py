"""watchfiles → cache → batched `changed` events (SPEC §5.6).

Watcher events are hints only: each hinted path is reread and its hash published.
"""

import logging
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import watchfiles

from memex.core.errors import BadPath
from memex.core.paths import resolve_workspace_path
from memex.core.store import TEMP_MARKER, WORKSPACE_CONFIG, content_hash
from memex.core.workspace import Workspace

log = logging.getLogger(__name__)

# How long the watcher waits for quiet before sending a batch, and the most it waits.
QUIET_MS = 200
MAX_BATCH_MS = 1000


@dataclass(frozen=True)
class Change:
    """A path that changed, with its new hash; None when it's gone or is a folder."""

    path: str
    hash: str | None


Listener = Callable[[list[Change]], None]


class ChangeFeed:
    """Fans each batch of changes out to the listeners (one per open event stream)."""

    def __init__(self) -> None:
        self._listeners: set[Listener] = set()
        self._lock = threading.Lock()

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        with self._lock:
            self._listeners.add(listener)
        return lambda: self._unsubscribe(listener)

    def _unsubscribe(self, listener: Listener) -> None:
        with self._lock:
            self._listeners.discard(listener)

    def hint(self, ws: Workspace, rels: Iterable[str]) -> list[Change]:
        """Reread each hinted path, update the cache, and publish one batch."""
        changes: list[Change] = []
        for rel in sorted(set(rels)):
            if _ignored(rel):
                continue
            path = ws.root / rel
            if path.is_file() and not (rel.endswith(".md") or rel == WORKSPACE_CONFIG):
                continue
            ws.changed(rel)
            changes.append(Change(rel, _hash(ws.root, rel)))
        if changes:
            with self._lock:
                listeners = list(self._listeners)
            for listener in listeners:
                try:
                    listener(changes)
                except Exception:  # e.g. a stream whose event loop has closed
                    log.exception("A change listener failed")
        return changes

    def run(self, ws: Workspace, stop: threading.Event) -> None:
        """Watch the Workspace until `stop` is set."""
        root = Path(ws.root).resolve()
        for batch in watchfiles.watch(
            root,
            stop_event=stop,
            step=QUIET_MS,
            debounce=MAX_BATCH_MS,
            force_polling=ws.config.polling or None,
            ignore_permission_denied=True,
            raise_interrupt=False,
        ):
            rels = [r for _, p in batch if (r := _relative(root, p)) is not None]
            try:
                self.hint(ws, rels)
            except Exception:
                log.exception("Couldn't process a change hint")


def _ignored(rel: str) -> bool:
    parts = PurePosixPath(rel).parts
    if TEMP_MARKER in parts[-1]:
        return True
    return rel != WORKSPACE_CONFIG and any(p.startswith(".") for p in parts)


def _relative(root: Path, path: str) -> str | None:
    try:
        return Path(path).relative_to(root).as_posix()
    except ValueError:
        return None


def _hash(root: Path, rel: str) -> str | None:
    try:
        return content_hash(resolve_workspace_path(root, rel).read_bytes())
    except BadPath, OSError:  # outside, gone, a folder or locked: the client rechecks
        return None
