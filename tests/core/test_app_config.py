from pathlib import Path

import pytest

from memex.core.config import AppConfig, Location, load_app_config, locate_workspace, memex_home


def test_memex_home_env_overrides_the_per_user_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("MEMEX_HOME", str(tmp_path / "home"))

    assert memex_home() == tmp_path / "home"


def put(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def make_workspace(path: Path) -> Path:
    put(path / ".memex/config.yaml", b"format: 1\n")
    return path


def test_workspace_flag_wins_and_is_remembered(tmp_path: Path):
    home = tmp_path / "home"
    old, new = make_workspace(tmp_path / "old"), make_workspace(tmp_path / "new")
    put(home / "config.yaml", f"workspace: {old}  # mine\nport: 48000\nextra: 1\n".encode())

    found = locate_workspace(new, home)

    assert found == Location(path=new, ready=True)
    assert (home / "config.yaml").read_bytes() == (
        f"workspace: {new}  # mine\nport: 48000\nextra: 1\n".encode()
    )
    assert load_app_config(home) == AppConfig(workspace=new, port=48000)


def test_remembered_path_that_is_no_longer_a_workspace_needs_setup(tmp_path: Path):
    home = tmp_path / "home"
    gone = tmp_path / "gone"
    put(home / "config.yaml", f"workspace: {gone}\n".encode())

    assert locate_workspace(None, home) == Location(path=gone, ready=False)


def test_nothing_remembered_and_no_flag_needs_setup_without_writing(tmp_path: Path):
    home = tmp_path / "home"

    assert locate_workspace(None, home) == Location(path=None, ready=False)
    assert not home.exists()
