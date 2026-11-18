"""SPEC §3.6: Settings covers both config files; app-config and polling changes need a relaunch."""

from pathlib import Path

from fastapi.testclient import TestClient

from memex.core.config import load_app_config
from tests.web.conftest import PORT


def put(api: TestClient, changes: dict) -> dict:
    current = api.get("/api/settings").json()
    response = api.put("/api/settings", json=changes, headers={"If-Match": current["hash"]})
    assert response.status_code == 200, response.text
    return api.get("/api/settings").json()


def test_settings_show_this_computer_and_about(api: TestClient, root: Path, home: Path):
    settings = api.get("/api/settings").json()

    assert settings["app"] == {"workspace": str(root), "port": PORT}
    assert settings["relaunch"] == []
    assert settings["about"] == {
        "version": settings["version"],
        "format": 1,
        "address": f"127.0.0.1:{PORT}",
        "logs": str(home / "logs"),
    }


def test_a_new_port_is_saved_to_app_config_and_waits_for_a_relaunch(api: TestClient, home: Path):
    settings = put(api, {"app": {"port": 47620}})

    assert load_app_config(home).port == 47620
    assert settings["app"]["port"] == 47620
    assert settings["running"]["port"] == PORT
    assert settings["relaunch"] == ["port"]

    settings = put(api, {"app": {"port": PORT}})
    assert settings["relaunch"] == []


def test_a_new_workspace_path_waits_for_a_relaunch(api: TestClient, home: Path, tmp_path: Path):
    other = tmp_path / "elsewhere"

    settings = put(api, {"app": {"workspace": str(other)}})

    assert load_app_config(home).workspace == other
    assert settings["app"]["workspace"] == str(other)
    assert settings["relaunch"] == ["workspace"]


def test_switching_polling_waits_for_a_relaunch(api: TestClient, root: Path):
    settings = put(api, {"workspace": {"polling": True}})

    assert "polling: true" in (root / ".memex/config.yaml").read_text("utf-8")
    assert settings["workspace"]["polling"] is True
    assert settings["running"]["polling"] is False
    assert settings["relaunch"] == ["polling"]


def test_app_config_alone_needs_no_if_match(api: TestClient, home: Path):
    response = api.put("/api/settings", json={"app": {"port": 47620}})

    assert response.status_code == 200
    assert load_app_config(home).port == 47620


def test_bad_app_config_values_are_422(api: TestClient, home: Path):
    for app in (
        {"port": 0},
        {"port": 70000},
        {"port": "47620"},
        {"port": True},
        {"workspace": "relative/path"},
        {"workspace": ""},
        {"colour": "blue"},
    ):
        response = api.put("/api/settings", json={"app": app})
        assert response.status_code == 422, app
    assert load_app_config(home).port == PORT


def test_ignore_and_me_are_saved(api: TestClient, root: Path):
    (root / "people/grace-hopper.md").write_text("---\ntitle: Grace Hopper\n---\n", "utf-8")
    api.app.state.memex.workspace.changed("people/grace-hopper.md")  # type: ignore[attr-defined]

    settings = put(api, {"workspace": {"me": "grace-hopper", "ignore": ["Archive/**"]}})

    assert settings["workspace"]["me"] == "grace-hopper"
    assert settings["workspace"]["ignore"] == ["Archive/**"]
    assert settings["relaunch"] == []
