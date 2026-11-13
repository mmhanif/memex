"""Files-page operations on a Workspace: move and delete to trash (SPEC §5, §8.4, §11.8)."""

import datetime as dt
import sys
from pathlib import Path

import pytest

from memex.core.clock import FixedClock
from memex.core.errors import BadPath, Exists, HasReferences, Validation
from memex.core.workspace import Workspace


def put(root: Path, rel: str, data: bytes) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


NOW = dt.datetime(2026, 11, 12, 9, 30, 5)


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    root = tmp_path / "ws"
    put(root, ".memex/config.yaml", b"format: 1\nme: ada\n")
    put(root, "people/ada.md", b"---\ntitle: Ada\nkind: [team-member]\n---\n")
    return Workspace.open(root, FixedClock(NOW.date(), NOW))


# Move (R14, §5 Acceptance)


def test_moving_a_note_to_another_folder_keeps_its_id(ws: Workspace):
    put(ws.root, "notes/a.md", b"# A\n")
    ws.changed("notes/a.md")

    ws.move("notes/a.md", "meetings/a.md")

    assert not (ws.root / "notes/a.md").exists()
    assert (ws.root / "meetings/a.md").read_bytes() == b"# A\n"
    assert ws.cache.get("notes/a.md") is None
    moved = ws.cache.get("meetings/a.md")
    assert moved is not None
    assert moved.id == "a"


def test_a_typed_entity_cannot_leave_its_folder(ws: Workspace):
    put(ws.root, "projects/x.md", b"---\ntitle: X\n---\n")

    with pytest.raises(BadPath):
        ws.move("projects/x.md", "notes/x.md")

    assert (ws.root / "projects/x.md").exists()
    assert not (ws.root / "notes/x.md").exists()


def test_a_typed_entity_can_be_renamed_within_its_folder(ws: Workspace):
    put(ws.root, "projects/x.md", b"---\ntitle: X\n---\n")

    ws.move("projects/x.md", "projects/y.md")

    assert (ws.root / "projects/y.md").exists()


def test_a_type_folder_cannot_be_moved(ws: Workspace):
    with pytest.raises(BadPath):
        ws.move("people", "staff")

    assert (ws.root / "people/ada.md").exists()


def test_moving_a_folder_moves_its_files_in_the_cache(ws: Workspace):
    put(ws.root, "notes/trip/day1.md", b"# Day 1\n")
    ws.changed("notes/trip/day1.md")

    ws.move("notes/trip", "notes/2026-trip")

    assert ws.cache.get("notes/trip/day1.md") is None
    assert ws.cache.get("notes/2026-trip/day1.md") is not None


def test_R14_a_folder_cannot_move_into_its_own_descendant(ws: Workspace):
    put(ws.root, "notes/a/b/x.md", b"x\n")

    with pytest.raises(BadPath):
        ws.move("notes/a", "notes/a/b/a")

    assert (ws.root / "notes/a/b/x.md").exists()


def test_R14_an_existing_destination_is_refused_without_overwrite(ws: Workspace):
    put(ws.root, "notes/a.md", b"a\n")
    put(ws.root, "notes/b.md", b"b\n")

    with pytest.raises(Exists):
        ws.move("notes/a.md", "notes/b.md")

    assert (ws.root / "notes/b.md").read_bytes() == b"b\n"


def test_R14_overwrite_replaces_an_existing_file(ws: Workspace):
    put(ws.root, "notes/a.md", b"a\n")
    put(ws.root, "notes/b.md", b"b\n")

    ws.move("notes/a.md", "notes/b.md", overwrite=True)

    assert (ws.root / "notes/b.md").read_bytes() == b"a\n"
    assert not (ws.root / "notes/a.md").exists()


def test_a_file_must_stay_markdown(ws: Workspace):
    put(ws.root, "notes/a.md", b"a\n")

    with pytest.raises(BadPath):
        ws.move("notes/a.md", "notes/a.txt")


# Delete to trash (§8.4, R13, R15)

STAMP = ".memex/trash/20261112-093005"


def test_deleting_an_unreferenced_note_moves_it_to_trash(ws: Workspace):
    put(ws.root, "notes/a.md", b"# A\n")
    ws.changed("notes/a.md")

    entry = ws.trash("notes/a.md")

    assert entry == f"{STAMP}/notes/a.md"
    assert not (ws.root / "notes/a.md").exists()
    assert (ws.root / STAMP / "notes/a.md").read_bytes() == b"# A\n"
    assert ws.cache.get("notes/a.md") is None


def test_a_second_delete_in_the_same_second_gets_its_own_trash_entry(ws: Workspace):
    put(ws.root, "notes/a.md", b"first\n")
    ws.trash("notes/a.md")
    put(ws.root, "notes/a.md", b"second\n")

    entry = ws.trash("notes/a.md")

    assert entry == f"{STAMP}-2/notes/a.md"
    assert (ws.root / STAMP / "notes/a.md").read_bytes() == b"first\n"
    assert (ws.root / entry).read_bytes() == b"second\n"


def test_trashed_files_are_not_read_as_entities(ws: Workspace):
    put(ws.root, "projects/x.md", b"---\ntitle: X\n---\n")
    ws.changed("projects/x.md")

    ws.trash("projects/x.md")

    assert ws.cache.resolve("x").status == "missing"


def test_a_file_with_incoming_references_is_refused(ws: Workspace):
    put(ws.root, "people/bob.md", b"---\ntitle: Bob\nkind: [stakeholder]\n---\n")
    put(ws.root, "projects/x.md", b"---\ntitle: X\nlead: bob\n---\n")
    put(ws.root, "notes/n.md", b"Met [[Bob]] today\n")
    for rel in ("people/bob.md", "projects/x.md", "notes/n.md"):
        ws.changed(rel)

    with pytest.raises(HasReferences) as e:
        ws.trash("people/bob.md")

    assert e.value.code == "has_references"
    assert e.value.referrers == ("notes/n.md", "projects/x.md")
    assert (ws.root / "people/bob.md").exists()


def test_me_cannot_be_deleted(ws: Workspace):
    with pytest.raises(Validation):
        ws.trash("people/ada.md")

    assert (ws.root / "people/ada.md").exists()


def test_a_folder_is_refused_while_something_outside_refers_into_it(ws: Workspace):
    put(ws.root, "notes/trip/plan.md", b"# Plan\n")
    put(ws.root, "notes/trip/log.md", b"see [[plan]]\n")
    put(ws.root, "notes/index.md", b"see [[plan]]\n")
    for rel in ("notes/trip/plan.md", "notes/trip/log.md", "notes/index.md"):
        ws.changed(rel)

    with pytest.raises(HasReferences) as e:
        ws.trash("notes/trip")

    assert e.value.referrers == ("notes/index.md",)
    assert (ws.root / "notes/trip/plan.md").exists()


def test_a_folder_whose_references_stay_inside_goes_to_trash(ws: Workspace):
    put(ws.root, "notes/trip/plan.md", b"# Plan\n")
    put(ws.root, "notes/trip/log.md", b"see [[plan]]\n")
    for rel in ("notes/trip/plan.md", "notes/trip/log.md"):
        ws.changed(rel)

    ws.trash("notes/trip")

    assert (ws.root / STAMP / "notes/trip/log.md").exists()
    assert ws.cache.get("notes/trip/plan.md") is None


def test_type_folders_cannot_be_deleted(ws: Workspace):
    with pytest.raises(BadPath):
        ws.trash("projects")

    assert (ws.root / "projects").is_dir() or not (ws.root / "projects").exists()


@pytest.mark.parametrize("rel", ["", ".", "/"])
def test_R15_the_workspace_root_cannot_be_deleted(ws: Workspace, rel: str):
    with pytest.raises(BadPath):
        ws.trash(rel)

    assert (ws.root / "people/ada.md").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_R13_deleting_a_folder_holding_a_link_never_touches_the_target(
    ws: Workspace, tmp_path: Path
):
    outside = tmp_path / "outside"
    put(outside, "secret.md", b"keep me\n")
    (ws.root / "notes/box").mkdir(parents=True)
    (ws.root / "notes/box/link").symlink_to(outside, target_is_directory=True)

    ws.trash("notes/box")

    assert (outside / "secret.md").read_bytes() == b"keep me\n"
    assert (ws.root / STAMP / "notes/box/link").is_symlink()


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_R13_a_link_itself_cannot_be_deleted(ws: Workspace, tmp_path: Path):
    outside = tmp_path / "outside"
    put(outside, "secret.md", b"keep me\n")
    (ws.root / "notes").mkdir(exist_ok=True)
    (ws.root / "notes/link.md").symlink_to(outside / "secret.md")

    with pytest.raises(BadPath):
        ws.trash("notes/link.md")

    assert (outside / "secret.md").read_bytes() == b"keep me\n"
