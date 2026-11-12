"""Change hints → cache → batched `changed` events (SPEC §5.6)."""

from pathlib import Path

import pytest

from memex.core.store import content_hash
from memex.core.watch import Change, ChangeFeed
from memex.core.workspace import Workspace


def put(root: Path, rel: str, data: bytes) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    root = tmp_path / "ws"
    put(root, ".memex/config.yaml", b"format: 1\n")
    return Workspace.open(root)


@pytest.fixture
def feed() -> ChangeFeed:
    return ChangeFeed()


def heard(feed: ChangeFeed) -> list[list[Change]]:
    batches: list[list[Change]] = []
    feed.subscribe(batches.append)
    return batches


def test_a_hint_rereads_the_file_and_publishes_its_new_hash(ws: Workspace, feed: ChangeFeed):
    batches = heard(feed)
    put(ws.root, "notes/a.md", b"# Outside\n")

    feed.hint(ws, ["notes/a.md"])

    assert batches == [[Change("notes/a.md", content_hash(b"# Outside\n"))]]
    cached = ws.cache.get("notes/a.md")
    assert cached is not None
    assert cached.title == "Outside"


def test_a_deleted_file_is_published_with_no_hash(ws: Workspace, feed: ChangeFeed):
    put(ws.root, "notes/a.md", b"x\n")
    ws.changed("notes/a.md")
    batches = heard(feed)
    (ws.root / "notes/a.md").unlink()

    feed.hint(ws, ["notes/a.md"])

    assert batches == [[Change("notes/a.md", None)]]
    assert ws.cache.get("notes/a.md") is None


def test_one_batch_per_hint_with_each_path_once(ws: Workspace, feed: ChangeFeed):
    batches = heard(feed)
    put(ws.root, "notes/b.md", b"b\n")
    put(ws.root, "notes/a.md", b"a\n")

    feed.hint(ws, ["notes/b.md", "notes/a.md", "notes/b.md"])

    assert [[c.path for c in batch] for batch in batches] == [["notes/a.md", "notes/b.md"]]


def test_temp_files_dot_folders_and_other_files_are_not_published(ws: Workspace, feed: ChangeFeed):
    batches = heard(feed)
    put(ws.root, "notes/.a.md.memex-tmp-0f0f0f", b"partial")
    put(ws.root, ".git/x.md", b"x\n")
    put(ws.root, "notes/pic.png", b"png")

    feed.hint(ws, ["notes/.a.md.memex-tmp-0f0f0f", ".git/x.md", "notes/pic.png"])

    assert batches == []


def test_a_new_folder_is_published_and_its_files_cached(ws: Workspace, feed: ChangeFeed):
    batches = heard(feed)
    put(ws.root, "notes/trip/day1.md", b"# Day 1\n")

    feed.hint(ws, ["notes/trip"])

    assert batches == [[Change("notes/trip", None)]]
    assert ws.cache.get("notes/trip/day1.md") is not None


def test_a_workspace_config_edit_is_published(ws: Workspace, feed: ChangeFeed):
    batches = heard(feed)
    put(ws.root, ".memex/config.yaml", b"format: 1\nme: ada\n")

    feed.hint(ws, [".memex/config.yaml"])

    assert batches == [[Change(".memex/config.yaml", content_hash(b"format: 1\nme: ada\n"))]]
    assert ws.config.me == "ada"


def test_an_unsubscribed_listener_hears_nothing(ws: Workspace, feed: ChangeFeed):
    batches: list[list[Change]] = []
    unsubscribe = feed.subscribe(batches.append)
    unsubscribe()
    put(ws.root, "notes/a.md", b"a\n")

    feed.hint(ws, ["notes/a.md"])

    assert batches == []
