"""SPEC §3.3, §3.4 and §17.2: first-run Setup over REST, and Quit."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from memex.core.config import load_app_config, locate_workspace
from memex.web.app import AppState
from tests.web.conftest import PORT, TODAY, client_for


@pytest.fixture
def fresh(home: Path, tmp_path: Path) -> AppState:
    """`memex` run with no app config and no `--workspace`."""
    from memex.core.clock import FixedClock

    return AppState.from_location(
        locate_workspace(None, home),
        port=PORT,
        home=home,
        clock=FixedClock(TODAY),
        install_dir=tmp_path / "install",
    )


@pytest.fixture
def setup_api(fresh: AppState) -> Iterator[TestClient]:
    with client_for(fresh) as client:
        yield client


def test_no_app_config_and_no_workspace_serves_the_setup_page(setup_api: TestClient):
    assert setup_api.get("/").status_code == 200

    response = setup_api.get("/api/setup")

    assert response.status_code == 200
    assert response.json() == {"needed": True, "path": str(Path("~/Documents/Memex").expanduser())}


def test_a_remembered_path_that_is_no_workspace_prefills_setup(home: Path, tmp_path: Path):
    gone = tmp_path / "gone"
    (home).mkdir()
    (home / "config.yaml").write_text(f"workspace: {gone}\n")
    state = AppState.from_location(locate_workspace(None, home), port=PORT, home=home)

    with client_for(state) as api:
        assert api.get("/api/setup").json() == {"needed": True, "path": str(gone)}


def test_workspace_routes_before_setup_are_404(setup_api: TestClient):
    response = setup_api.get("/api/tree")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_scan_reports_counts_and_writes_nothing(setup_api: TestClient, tmp_path: Path):
    folder = tmp_path / "adopt"
    (folder / "people").mkdir(parents=True)
    (folder / "people/grace.md").write_bytes(b"---\ntitle: Grace Hopper\n---\n")
    for name in ("a", "b", "c"):
        (folder / f"{name}.md").write_bytes(b"# x\n")
    before = sorted(p.as_posix() for p in folder.rglob("*"))

    response = setup_api.post("/api/setup/scan", json={"path": str(folder)})

    assert response.status_code == 200
    assert response.json() == {
        "summary": "3 Notes, 1 Person",
        "notes": 3,
        "persons": [{"id": "grace", "title": "Grace Hopper"}],
    }
    assert sorted(p.as_posix() for p in folder.rglob("*")) == before


def test_scan_inside_the_install_folder_is_422(setup_api: TestClient, tmp_path: Path):
    response = setup_api.post("/api/setup/scan", json={"path": str(tmp_path / "install/x")})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation"


def test_relative_path_is_422(setup_api: TestClient):
    response = setup_api.post("/api/setup/scan", json={"path": "Documents/Memex"})

    assert response.status_code == 422


def test_apply_with_a_new_name_opens_the_workspace_and_remembers_it(
    setup_api: TestClient, fresh: AppState, home: Path, tmp_path: Path
):
    folder = tmp_path / "Memex"

    response = setup_api.post(
        "/api/setup/apply", json={"path": str(folder), "me": {"name": "Ada Lovelace"}}
    )

    assert response.status_code == 200
    assert response.json() == {"me": "ada-lovelace"}
    assert (folder / "people/ada-lovelace.md").is_file()
    assert load_app_config(home).workspace == folder
    assert setup_api.get("/api/setup").json() == {"needed": False}
    paths = {f["path"] for f in setup_api.get("/api/tree").json()["files"]}
    assert "people/ada-lovelace.md" in paths


def test_apply_picking_an_existing_person(setup_api: TestClient, tmp_path: Path):
    folder = tmp_path / "adopt"
    (folder / "people").mkdir(parents=True)
    (folder / "people/grace.md").write_bytes(b"---\ntitle: Grace Hopper\n---\n")

    response = setup_api.post("/api/setup/apply", json={"path": str(folder), "me": {"id": "grace"}})

    assert response.status_code == 200
    assert response.json() == {"me": "grace"}
    assert (folder / "people/grace.md").read_bytes() == b"---\ntitle: Grace Hopper\n---\n"


def test_apply_with_an_unknown_person_is_422_unknown_reference(
    setup_api: TestClient, tmp_path: Path
):
    folder = tmp_path / "adopt"
    folder.mkdir()

    response = setup_api.post("/api/setup/apply", json={"path": str(folder), "me": {"id": "ghost"}})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unknown_reference"
    assert not (folder / ".memex").exists()


@pytest.mark.parametrize("me", [{}, {"name": "A", "id": "a"}, {"name": ""}])
def test_apply_needs_exactly_one_of_name_or_id(setup_api: TestClient, tmp_path: Path, me: dict):
    response = setup_api.post("/api/setup/apply", json={"path": str(tmp_path / "x"), "me": me})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation"


def test_setup_is_refused_once_a_workspace_is_open(api: TestClient, tmp_path: Path):
    assert api.get("/api/setup").json() == {"needed": False}

    responses = [
        api.post("/api/setup/scan", json={"path": str(tmp_path / "other")}),
        api.post("/api/setup/apply", json={"path": str(tmp_path / "other"), "me": {"name": "B"}}),
    ]

    assert [r.status_code for r in responses] == [422, 422]
    assert not (tmp_path / "other").exists()


def test_quit_shuts_down(api: TestClient, state: AppState):
    calls: list[bool] = []
    state.on_quit = lambda: calls.append(True)

    response = api.post("/api/quit", json={})

    assert response.status_code == 202
    assert calls == [True]
