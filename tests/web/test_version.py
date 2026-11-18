"""Memex runs from a bare checkout too (src on PYTHONPATH, no install): its version is "dev"."""

from importlib import metadata

import pytest
from fastapi.testclient import TestClient

from memex.launcher.cli import main


@pytest.fixture
def not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(name: str) -> str:
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(metadata, "version", missing)


def test_version_flag_from_a_checkout(not_installed: None, capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit) as exited:
        main(["--version"])

    assert exited.value.code == 0
    assert capsys.readouterr().out.strip() == "memex dev"


def test_settings_show_dev_from_a_checkout(not_installed: None, api: TestClient):
    response = api.get("/api/settings")

    assert response.status_code == 200
    assert response.json()["version"] == "dev"


def test_an_installed_memex_shows_its_package_version(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit):
        main(["--version"])

    assert capsys.readouterr().out.strip() == f"memex {metadata.version('memex')}"
