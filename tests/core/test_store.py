import contextlib
import datetime as dt
import hashlib
import threading
from pathlib import Path

import pytest

from memex.core.errors import BadPath, Conflict, Exists, Locked, NotFound, Validation
from memex.core.store import FileVersion, Store
from tests.core.hostile_paths import HOSTILE_PATHS


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def store(root: Path) -> Store:
    return Store(root)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_read_returns_text_and_the_sha256_of_the_raw_bytes(root: Path, store: Store):
    (root / "a.md").write_bytes(b"# Hello\n")
    version = store.read("a.md")
    assert version.text == "# Hello\n"
    assert version.hash == sha256(b"# Hello\n")


def test_write_with_the_current_hash_replaces_the_file_and_returns_the_new_hash(
    root: Path, store: Store
):
    (root / "a.md").write_bytes(b"old\n")
    new_hash = store.write("a.md", "new\n", expected_hash=sha256(b"old\n"))
    assert (root / "a.md").read_bytes() == b"new\n"
    assert new_hash == sha256(b"new\n")


def test_write_with_a_stale_hash_is_a_conflict_carrying_the_current_file(root: Path, store: Store):
    (root / "a.md").write_bytes(b"mine\n")
    stale = store.read("a.md").hash
    (root / "a.md").write_bytes(b"outside edit\n")

    with pytest.raises(Conflict) as info:
        store.write("a.md", "my edit\n", expected_hash=stale)

    assert info.value.current == FileVersion("outside edit\n", sha256(b"outside edit\n"))
    assert (root / "a.md").read_bytes() == b"outside edit\n"


def test_crlf_bom_file_without_trailing_newline_keeps_its_shape_when_saved(
    root: Path, store: Store
):
    (root / "a.md").write_bytes(b"\xef\xbb\xbf# T\r\nline one\r\nline two")
    version = store.read("a.md")
    assert version.text == "# T\nline one\nline two"

    store.write("a.md", version.text.replace("two", "2"), expected_hash=version.hash)

    assert (root / "a.md").read_bytes() == b"\xef\xbb\xbf# T\r\nline one\r\nline 2"


def test_write_leaves_no_temp_file_behind(root: Path, store: Store):
    (root / "a.md").write_bytes(b"old\n")
    store.write("a.md", "new\n", expected_hash=sha256(b"old\n"))
    assert [p.name for p in root.iterdir()] == ["a.md"]


def test_create_writes_a_utf8_lf_file_with_a_trailing_newline(root: Path, store: Store):
    new_hash = store.create("projects/x.md", "---\ntitle: X\n---\nbody")
    assert (root / "projects" / "x.md").read_bytes() == b"---\ntitle: X\n---\nbody\n"
    assert new_hash == sha256(b"---\ntitle: X\n---\nbody\n")


def test_create_on_a_taken_path_fails_with_exists(root: Path, store: Store):
    (root / "a.md").write_bytes(b"keep\n")
    with pytest.raises(Exists):
        store.create("a.md", "replace\n")
    assert (root / "a.md").read_bytes() == b"keep\n"


def test_create_of_a_non_markdown_file_is_a_bad_path(root: Path, store: Store):
    with pytest.raises(BadPath):
        store.create("x.txt", "hi\n")
    assert list(root.iterdir()) == []


@pytest.mark.parametrize("rel", HOSTILE_PATHS)
def test_hostile_path_write_leaves_disk_unchanged(tmp_path: Path, rel: str):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "a.md").write_bytes(b"keep\n")
    before = snapshot(tmp_path)
    with pytest.raises(BadPath):
        Store(root).create(rel, "pwned\n")
    assert snapshot(tmp_path) == before


def snapshot(folder: Path) -> dict[str, bytes]:
    return {str(p.relative_to(folder)): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


def test_readers_only_ever_see_a_whole_old_or_whole_new_file(root: Path, store: Store):
    versions = [("a" * 1_000_000 + "\n").encode(), ("b" * 1_000_000 + "\n").encode()]
    (root / "a.md").write_bytes(versions[0])
    seen: set[bytes] = set()
    stop = threading.Event()

    def reader() -> None:
        while not stop.is_set():
            # Windows: a reader may hit the file mid-swap and miss it, but never see half of it.
            with contextlib.suppress(PermissionError):
                seen.add((root / "a.md").read_bytes())

    thread = threading.Thread(target=reader)
    thread.start()
    try:
        current = sha256(versions[0])
        for i in range(20):
            current = store.write("a.md", versions[(i + 1) % 2].decode(), expected_hash=current)
    finally:
        stop.set()
        thread.join()
    assert seen <= set(versions)


@pytest.mark.windows
def test_save_over_a_file_held_open_without_share_delete_fails_with_locked(
    root: Path, store: Store
):
    (root / "a.md").write_bytes(b"old\n")
    with open(root / "a.md", "rb"), pytest.raises(Locked):
        store.write("a.md", "new\n", expected_hash=sha256(b"old\n"))
    assert (root / "a.md").read_bytes() == b"old\n"
    assert [p.name for p in root.iterdir()] == ["a.md"]


PROJECT = """\
---
# Data migration project
title: "Data migration"
status: not-started   # was planned
team: [alice, bob]
due: '2026-12-01'
custom_field: {keep: me}
---
Body line with trailing spaces\x20\x20\x20
---
Not frontmatter.
"""


def test_changing_one_field_preserves_comments_order_quoting_and_body_bytes(
    root: Path, store: Store
):
    (root / "x.md").write_bytes(PROJECT.encode())
    store.update_fields("x.md", expected_hash=store.read("x.md").hash, set={"status": "active"})
    # The end-of-line comment keeps its column.
    assert (root / "x.md").read_bytes().decode() == PROJECT.replace(
        "status: not-started   # was planned", "status: active        # was planned"
    )


def test_new_field_is_appended_and_unset_field_removed(root: Path, store: Store):
    (root / "x.md").write_bytes(b"---\ntitle: X\ndue: 2026-12-01\nstatus: open\n---\nbody\n")
    store.update_fields(
        "x.md",
        expected_hash=store.read("x.md").hash,
        set={"completed": dt.date(2026, 11, 12)},
        unset=["due"],
    )
    assert (root / "x.md").read_bytes().decode() == (
        "---\ntitle: X\nstatus: open\ncompleted: 2026-11-12\n---\nbody\n"
    )


def test_field_edit_keeps_crlf_bom_and_a_body_without_trailing_newline(root: Path, store: Store):
    (root / "x.md").write_bytes(b"\xef\xbb\xbf---\r\ntitle: X\r\nstatus: open\r\n---\r\nbody")
    store.update_fields("x.md", expected_hash=store.read("x.md").hash, set={"status": "done"})
    assert (root / "x.md").read_bytes() == (
        b"\xef\xbb\xbf---\r\ntitle: X\r\nstatus: done\r\n---\r\nbody"
    )


def test_field_edit_with_a_stale_hash_is_a_conflict(root: Path, store: Store):
    (root / "x.md").write_bytes(b"---\nstatus: open\n---\n")
    stale = store.read("x.md").hash
    (root / "x.md").write_bytes(b"---\nstatus: done\n---\n")
    with pytest.raises(Conflict):
        store.update_fields("x.md", expected_hash=stale, set={"status": "cancelled"})
    assert (root / "x.md").read_bytes().decode() == "---\nstatus: done\n---\n"


def test_field_edit_on_unparseable_frontmatter_is_refused(root: Path, store: Store):
    (root / "x.md").write_bytes(b"---\ntitle: [unclosed\n---\nbody\n")
    with pytest.raises(Validation):
        store.update_fields("x.md", expected_hash=store.read("x.md").hash, set={"title": "Y"})
    assert (root / "x.md").read_bytes().decode() == "---\ntitle: [unclosed\n---\nbody\n"


def test_read_write_or_field_edit_of_a_missing_file_is_not_found(store: Store):
    with pytest.raises(NotFound):
        store.read("gone.md")
    with pytest.raises(NotFound):
        store.write("gone.md", "x\n", expected_hash=sha256(b""))
    with pytest.raises(NotFound):
        store.update_fields("gone.md", expected_hash=sha256(b""), set={"a": 1})
