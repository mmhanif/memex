"""SPEC §5.6: `GET /api/events` against a real server and the real watcher."""

import json
import queue
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import httpx2 as httpx
import pytest

from memex.core.clock import FixedClock
from memex.core.store import content_hash
from memex.web.app import AppState
from tests.live import live_server
from tests.web.conftest import TODAY

pytestmark = pytest.mark.slow


@pytest.fixture
def server(root: Path, home: Path, tmp_path: Path) -> Iterator[AppState]:
    def make(port: int) -> AppState:
        return AppState.for_workspace(
            root, port=port, home=home, clock=FixedClock(TODAY), install_dir=tmp_path / "i"
        )

    with live_server(make) as state:
        yield state


class EventReader:
    """Reads `event:`/`data:` frames on a thread so the test can wait with a timeout."""

    def __init__(self, state: AppState) -> None:
        self.frames: queue.Queue[tuple[str, dict]] = queue.Queue()
        origin = f"http://127.0.0.1:{state.port}"
        self.client = httpx.Client(
            base_url=origin,
            headers={"X-Memex": "1"},
            cookies={"memex_session": state.session.secret},
            timeout=httpx.Timeout(5, read=None),
        )
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()
        assert self.next(5) == ("ready", {})

    def _read(self) -> None:
        try:
            with self.client.stream("GET", "/api/events") as response:
                event = None
                for line in response.iter_lines():
                    if line.startswith("event: "):
                        event = line.removeprefix("event: ")
                    elif line.startswith("data: ") and event:
                        self.frames.put((event, json.loads(line.removeprefix("data: "))))
                        event = None
        except httpx.HTTPError:
            pass

    def next(self, timeout: float) -> tuple[str, dict]:
        return self.frames.get(timeout=timeout)

    def changes_for(self, path: str, timeout: float = 5) -> list[dict]:
        """The first `changed` batch naming `path`. Earlier batches (e.g. its folder's
        own change, which some platforms report separately) are skipped."""
        deadline = time.monotonic() + timeout
        while True:
            event, data = self.next(max(deadline - time.monotonic(), 0.01))
            if event == "changed" and any(c["path"] == path for c in data["changes"]):
                return data["changes"]

    def close(self) -> None:
        self.client.close()


@pytest.fixture
def events(server: AppState) -> Iterator[EventReader]:
    reader = EventReader(server)
    time.sleep(0.5)  # let the watcher settle before the test writes
    yield reader
    reader.close()


def test_an_outside_write_sends_one_changed_event_with_the_new_hash(
    server: AppState, events: EventReader
):
    assert server.workspace is not None
    (server.workspace.root / "notes/a.md").write_bytes(b"# Outside\n")

    changes = events.changes_for("notes/a.md")

    assert {"path": "notes/a.md", "hash": content_hash(b"# Outside\n")} in changes
    cached = server.workspace.cache.get("notes/a.md")
    assert cached is not None
    assert cached.title == "Outside"


def test_ten_quick_writes_send_one_batched_event(server: AppState, events: EventReader):
    assert server.workspace is not None
    for i in range(10):
        (server.workspace.root / f"notes/n{i}.md").write_bytes(b"x\n")
        time.sleep(0.01)

    changes = events.changes_for("notes/n0.md")

    assert {c["path"] for c in changes} >= {f"notes/n{i}.md" for i in range(10)}
    try:
        extra = events.next(timeout=1)
    except queue.Empty:
        extra = None
    assert extra is None


def test_a_deleted_file_is_sent_with_a_null_hash(server: AppState, events: EventReader):
    assert server.workspace is not None
    (server.workspace.root / "bookmarks.md").unlink()

    changes = events.changes_for("bookmarks.md")

    assert {"path": "bookmarks.md", "hash": None} in changes


def test_R10_events_need_the_memex_header(server: AppState):
    response = httpx.get(
        f"http://127.0.0.1:{server.port}/api/events",
        cookies={"memex_session": server.session.secret},
    )

    assert response.status_code == 403
