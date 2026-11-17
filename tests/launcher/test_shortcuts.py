"""SPEC §13.5: `memex shortcuts [--remove]`."""

from pathlib import Path

import pytest

from tests.launcher.conftest import run_memex


@pytest.mark.windows
def test_shortcuts_adds_and_removes_a_start_menu_link(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    link = tmp_path / "appdata/Microsoft/Windows/Start Menu/Programs/Memex.lnk"

    added = run_memex(home, "shortcuts")
    assert added.returncode == 0, added.stderr
    assert link.is_file()

    removed = run_memex(home, "shortcuts", "--remove")
    assert removed.returncode == 0, removed.stderr
    assert not link.exists()
