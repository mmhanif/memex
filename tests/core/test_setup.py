import datetime as dt
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from memex.core.clock import FixedClock
from memex.core.errors import UnknownReference, Validation
from memex.core.workspace import NewMe, apply_setup, scan_setup

TODAY = dt.date(2026, 11, 12)


@pytest.fixture
def install_dir(tmp_path: Path) -> Path:
    return tmp_path / "install"


def put(root: Path, rel: str, data: bytes) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def snapshot(root: Path) -> dict[str, bytes | None]:
    """Every file (with its bytes) and folder (None) under `root`."""
    return {
        p.relative_to(root).as_posix(): (p.read_bytes() if p.is_file() else None)
        for p in root.rglob("*")
    }


def test_setup_on_an_empty_folder_creates_exactly_the_seed(tmp_path: Path, install_dir: Path):
    root = tmp_path / "Memex"
    root.mkdir()

    ws = apply_setup(root, NewMe("Ada Lovelace"), clock=FixedClock(TODAY), install_dir=install_dir)

    assert snapshot(root) == {
        ".memex": None,
        ".memex/config.yaml": b"format: 1\nme: ada-lovelace\n",
        "themes": None,
        "projects": None,
        "deliverables": None,
        "people": None,
        "people/ada-lovelace.md": (
            b"---\ntitle: Ada Lovelace\nkind: [team-member]\ncreated: 2026-11-12\n---\n"
        ),
        "todos": None,
        "glossary": None,
        "notes": None,
        "bookmarks.md": b"",
    }
    assert ws.require_me().title == "Ada Lovelace"


def existing_folder(root: Path) -> None:
    put(root, "standup.md", b"# Standup\r\n\r\nnotes\r\n")
    put(root, "ideas/one.md", b"\xef\xbb\xbf---\ntitle: One\n---\nno newline")
    put(root, "ideas/two.md", b"---\ntitle: [broken\n---\n")
    put(root, "people/grace-hopper.md", b"---\ntitle: Grace Hopper\nkind: [stakeholder]\n---\n")
    put(root, ".obsidian/app.md", b"# not a Note\n")
    put(root, "diagram.png", b"\x89PNG")


def test_scan_reports_what_adoption_finds_and_writes_nothing(tmp_path: Path, install_dir: Path):
    root = tmp_path / "existing"
    existing_folder(root)
    before = snapshot(root)

    report = scan_setup(root, install_dir=install_dir)

    assert report.summary == "3 Notes, 1 Person"
    assert [p.id for p in report.persons] == ["grace-hopper"]
    assert snapshot(root) == before


def test_adoption_changes_no_pre_existing_file(tmp_path: Path, install_dir: Path):
    root = tmp_path / "existing"
    existing_folder(root)
    before = snapshot(root)

    ws = apply_setup(root, "grace-hopper", clock=FixedClock(TODAY), install_dir=install_dir)

    after = snapshot(root)
    assert {rel: after[rel] for rel in before} == before
    assert after[".memex/config.yaml"] == b"format: 1\nme: grace-hopper\n"
    assert ws.require_me().title == "Grace Hopper"


def setup_both_ways(root: Path, install_dir: Path) -> list[Callable[[], object]]:
    return [
        lambda: scan_setup(root, install_dir=install_dir),
        lambda: apply_setup(root, NewMe("Ada"), clock=FixedClock(TODAY), install_dir=install_dir),
    ]


def test_setup_rejects_a_path_inside_another_workspace(tmp_path: Path, install_dir: Path):
    put(tmp_path, "outer/.memex/config.yaml", b"format: 1\n")
    root = tmp_path / "outer/sub/inner"
    root.mkdir(parents=True)

    for attempt in setup_both_ways(root, install_dir):
        with pytest.raises(Validation, match="inside another Workspace"):
            attempt()
    assert snapshot(root) == {}


def test_setup_rejects_a_path_inside_the_install_folder(tmp_path: Path, install_dir: Path):
    root = install_dir / "Lib/site-packages/data"
    root.mkdir(parents=True)

    for attempt in setup_both_ways(root, install_dir):
        with pytest.raises(Validation, match="install folder"):
            attempt()
    assert snapshot(root) == {}


def test_setup_rejects_a_folder_that_is_already_a_workspace(tmp_path: Path, install_dir: Path):
    root = tmp_path / "ws"
    put(root, ".memex/config.yaml", b"format: 1\n")

    for attempt in setup_both_ways(root, install_dir):
        with pytest.raises(Validation, match="already a Workspace"):
            attempt()
    assert snapshot(root) == {".memex": None, ".memex/config.yaml": b"format: 1\n"}


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_setup_rejects_a_folder_that_is_not_writable(tmp_path: Path, install_dir: Path):
    root = tmp_path / "locked"
    root.mkdir()
    root.chmod(0o500)
    try:
        for attempt in setup_both_ways(root, install_dir):
            with pytest.raises(Validation, match="not writable"):
                attempt()
    finally:
        root.chmod(0o700)
    assert snapshot(root) == {}


def test_setup_with_an_unknown_person_as_me_is_rejected(tmp_path: Path, install_dir: Path):
    root = tmp_path / "existing"
    existing_folder(root)
    before = snapshot(root)

    with pytest.raises(UnknownReference):
        apply_setup(root, "ghost", clock=FixedClock(TODAY), install_dir=install_dir)
    assert snapshot(root) == before


def test_new_me_gets_a_free_id_when_adopting(tmp_path: Path, install_dir: Path):
    root = tmp_path / "existing"
    put(root, "notes/Ada-Lovelace.md", b"# a Note about Ada\n")

    ws = apply_setup(root, NewMe("Ada Lovelace"), clock=FixedClock(TODAY), install_dir=install_dir)

    assert ws.require_me().rel == "people/ada-lovelace-2.md"
