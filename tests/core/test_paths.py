from pathlib import Path

import pytest

from memex.core.errors import BadPath
from memex.core.paths import resolve_workspace_path
from tests.core.hostile_paths import HOSTILE_PATHS


@pytest.mark.parametrize("rel", HOSTILE_PATHS)
def test_hostile_path_is_rejected(tmp_path: Path, rel: str):
    with pytest.raises(BadPath):
        resolve_workspace_path(tmp_path, rel)


def test_plain_relative_path_resolves_inside_the_workspace(tmp_path: Path):
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "a.md").write_bytes(b"hi")
    assert resolve_workspace_path(tmp_path, "notes/a.md") == (tmp_path / "notes" / "a.md").resolve()


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    target = tmp_path / "outside"
    target.mkdir()
    (target / "secret.md").write_bytes(b"secret")
    return target


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    return root


def test_symlinked_folder_pointing_outside_is_rejected(workspace: Path, outside: Path):
    (workspace / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(BadPath):
        resolve_workspace_path(workspace, "escape/secret.md")
    with pytest.raises(BadPath):
        resolve_workspace_path(workspace, "escape/new.md")


def test_symlinked_file_pointing_outside_is_rejected(workspace: Path, outside: Path):
    (workspace / "secret.md").symlink_to(outside / "secret.md")
    with pytest.raises(BadPath):
        resolve_workspace_path(workspace, "secret.md")


def test_dangling_symlink_pointing_outside_is_rejected(workspace: Path, outside: Path):
    (workspace / "new.md").symlink_to(outside / "missing.md")
    with pytest.raises(BadPath):
        resolve_workspace_path(workspace, "new.md")


def test_new_file_in_missing_folder_resolves_inside_the_workspace(workspace: Path):
    expected = workspace.resolve() / "projects" / "x.md"
    assert resolve_workspace_path(workspace, "projects/x.md") == expected


def test_error_message_holds_only_the_relative_path(workspace: Path, outside: Path):
    (workspace / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(BadPath) as info:
        resolve_workspace_path(workspace, "escape/secret.md")
    assert str(workspace) not in str(info.value)
    assert str(outside) not in str(info.value)
