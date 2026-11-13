"""SPEC §17.2: quick-add and the view routes, with the §17.1 error mapping."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from memex.web.app import AppState


def put(state: AppState, rel: str, text: str) -> None:
    assert state.workspace is not None
    path = state.workspace.root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    state.workspace.changed(rel)


@pytest.fixture
def alice(state: AppState) -> str:
    put(
        state,
        "people/alice-smith.md",
        "---\ntitle: Alice Smith\nkind: [team-member]\nmanager: ada-lovelace\n---\nAbout Alice\n",
    )
    return "alice-smith"


def unset_me(state: AppState) -> None:
    put(state, ".memex/config.yaml", "format: 1\n")


def test_parse_quick_add_previews_without_writing(api: TestClient, alice: str, root: Path):
    response = api.post("/api/parse/quick-add", json={"text": "Send deck @ali due:2026-11-20"})
    assert response.status_code == 200
    assert response.json() == {
        "title": "Send deck",
        "owner": "alice-smith",
        "requester": "ada-lovelace",
        "due": "2026-11-20",
        "errors": [],
        "names": {"alice-smith": "Alice Smith", "ada-lovelace": "Ada Lovelace"},
    }
    assert list((root / "todos").iterdir()) == []


def test_parse_quick_add_reports_token_errors_with_candidates(api: TestClient, alice: str):
    body = api.post(
        "/api/parse/quick-add", json={"text": "x @zz", "defaults": {"requester": alice}}
    ).json()
    assert body["requester"] == alice
    assert body["errors"] == [
        {"token": "@zz", "message": "No Person matches @zz", "candidates": []}
    ]


def test_parse_quick_add_without_text_is_422(api: TestClient):
    assert api.post("/api/parse/quick-add", json={}).status_code == 422


def test_quick_add_creates_the_todo(api: TestClient, alice: str, root: Path):
    response = api.post(
        "/api/todos/quick-add", json={"text": "Draft plan", "defaults": {"owner": alice}}
    )
    assert response.status_code == 201, response.text
    assert response.json()["id"] == "2026-11-12-draft-plan"
    text = (root / "todos/2026-11-12-draft-plan.md").read_text()
    assert "owner: alice-smith" in text
    assert "requester: ada-lovelace" in text


def test_quick_add_with_a_bad_token_is_422(api: TestClient):
    response = api.post("/api/todos/quick-add", json={"text": "x @zz"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation"
    assert error["field_errors"] == [{"field": "@zz", "message": "No Person matches @zz"}]


def test_quick_add_without_me_is_409_me_not_set(api: TestClient, state: AppState):
    unset_me(state)
    response = api.post("/api/todos/quick-add", json={"text": "Call vendor"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "me_not_set"


def test_todo_views_return_groups_and_names(api: TestClient, state: AppState, alice: str):
    put(
        state,
        "todos/t.md",
        "---\ntitle: T\nowner: alice-smith\nrequester: ada-lovelace\nstatus: open\n---\n",
    )
    body = api.get("/api/views/todos?view=waiting-on-them").json()
    [group] = body["groups"]
    assert (group["label"], group["person"]) == ("Alice Smith", "alice-smith")
    assert [t["id"] for t in group["todos"]] == ["t"]
    assert body["names"]["alice-smith"] == "Alice Smith"
    assert api.get("/api/views/todos?view=mine").json()["groups"] == []


def test_todo_views_for_a_person_are_their_person_view_columns(
    api: TestClient, state: AppState, alice: str
):
    put(
        state,
        "todos/t.md",
        "---\ntitle: T\nowner: alice-smith\nrequester: ada-lovelace\n"
        "status: done\ncompleted: 2026-11-11\n---\n",
    )
    url = "/api/views/todos?view=waiting-on-them&person=alice-smith"
    assert api.get(url).json()["groups"] == []
    [group] = api.get(url + "&include_done=true").json()["groups"]
    assert group["label"] == "Completed"


def test_todo_views_errors(api: TestClient, state: AppState):
    assert api.get("/api/views/todos?view=all").json()["error"]["code"] == "validation"
    unset_me(state)
    response = api.get("/api/views/todos?view=mine")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "me_not_set"


def test_dashboard(api: TestClient, state: AppState, alice: str):
    put(state, "projects/p.md", "---\ntitle: P\nstatus: blocked\ndue: 2026-11-13\n---\n")
    body = api.get("/api/views/dashboard").json()
    assert [f["id"] for f in body["due_soon"]] == ["p"]
    assert [f["id"] for f in body["blocked"]] == ["p"]
    assert body["directs"] == [
        {"person": body["directs"][0]["person"], "waiting_on_them": 0, "waiting_on_me": 0}
    ]
    assert body["directs"][0]["person"]["id"] == "alice-smith"
    assert body["waiting_on_them"] == []
    assert body["waiting_on_me"] == []
    assert body["get_started"] is False
    assert body["me_set"] is True


def test_dashboard_without_me_marks_the_me_cards(api: TestClient, state: AppState):
    unset_me(state)
    body = api.get("/api/views/dashboard").json()
    assert body["me_set"] is False
    assert body["waiting_on_them"] is None


def test_dashboard_without_a_workspace_is_404(state: AppState, api: TestClient):
    state.workspace = None
    assert api.get("/api/views/dashboard").status_code == 404


def test_people(api: TestClient, alice: str):
    body = api.get("/api/views/people").json()
    assert body["me"]["person"]["id"] == "ada-lovelace"
    assert [r["person"]["id"] for r in body["me"]["reports"]] == ["alice-smith"]
    assert body["manager"] is None
    assert body["others"] == []
    assert body["stakeholders"] == []


def test_person_view(api: TestClient, state: AppState, alice: str):
    put(state, "projects/p.md", "---\ntitle: P\nstatus: active\nlead: alice-smith\n---\n")
    body = api.get("/api/views/person/alice-smith").json()
    assert body["person"]["title"] == "Alice Smith"
    assert body["person"]["body"] == "About Alice\n"
    assert body["manager"]["id"] == "ada-lovelace"
    assert body["directs"] == []
    assert [(t["item"]["id"], t["roles"]) for t in body["tagged_on"]] == [("p", ["Lead"])]
    assert body["waiting_on_them"] == []
    assert body["notes"] == []


def test_person_view_of_a_project_is_404(api: TestClient, state: AppState):
    put(state, "projects/p.md", "---\ntitle: P\nstatus: active\n---\n")
    response = api.get("/api/views/person/p")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
