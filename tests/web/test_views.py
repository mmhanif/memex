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
        {"field": "owner", "token": "@zz", "message": "No Person matches @zz", "candidates": []}
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


def test_quick_add_with_an_unmatched_person_is_422_unknown_reference(
    api: TestClient, state: AppState, alice: str
):
    put(state, "people/alan-po.md", "---\ntitle: Alan Po\nkind: [team-member]\n---\n")
    response = api.post("/api/todos/quick-add", json={"text": "x @al"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "unknown_reference"
    assert error["suggestions"] == ["alan-po", "alice-smith"]
    assert error["field_errors"] == [
        {"field": "owner", "message": "@al could be alan-po, alice-smith"}
    ]


def test_quick_add_with_a_bad_date_is_422_validation(api: TestClient):
    response = api.post("/api/todos/quick-add", json={"text": "x due:2026-02-30"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation"
    assert [f["field"] for f in error["field_errors"]] == ["due"]


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


def test_todo_views_count_each_views_open_todos_and_say_when_the_week_ends(
    api: TestClient, state: AppState, alice: str
):
    put(
        state,
        "todos/t.md",
        "---\ntitle: T\nowner: alice-smith\nrequester: ada-lovelace\nstatus: open\n---\n",
    )
    put(state, "todos/u.md", "---\ntitle: U\nowner: ada-lovelace\nrequester: alice-smith\n---\n")
    body = api.get("/api/views/todos?view=waiting-on-me").json()
    assert body["counts"] == {"mine": 1, "waiting-on-them": 1, "waiting-on-me": 1}
    assert body["week_ends"] == "2026-11-15"  # today is Thursday 2026-11-12
    assert api.get("/api/tree").json()["workspace"]["open_todos"] == body["counts"]["mine"]


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


def test_dashboard_names_the_parents_leads_and_abouts_its_rows_show(
    api: TestClient, state: AppState, alice: str
):
    put(state, "projects/p.md", "---\ntitle: Data Migration\nstatus: active\n---\n")
    put(
        state,
        "deliverables/d.md",
        "---\ntitle: Ledger Export\nproject: p\nstatus: blocked\nlead: alice-smith\n---\n",
    )
    put(state, "themes/t.md", "---\ntitle: Reliability\n---\n")
    put(state, "notes/call.md", "---\ntitle: Vendor call\nabout: [t]\n---\n")
    names = api.get("/api/views/dashboard").json()["names"]
    assert names["p"] == "Data Migration"
    assert names["t"] == "Reliability"
    assert names["alice-smith"] == "Alice Smith"


def test_dashboard_without_me_marks_the_me_cards(api: TestClient, state: AppState):
    unset_me(state)
    body = api.get("/api/views/dashboard").json()
    assert body["waiting_on_them"] is None
    assert body["directs"] is None


def test_dashboard_without_a_workspace_is_404(state: AppState, api: TestClient):
    state.workspace = None
    assert api.get("/api/views/dashboard").status_code == 404


def test_people(api: TestClient, alice: str):
    body = api.get("/api/views/people").json()
    assert body["me"]["person"]["id"] == "ada-lovelace"
    assert [d["person"]["id"] for d in body["me"]["directs"]] == ["alice-smith"]
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


def test_todo_views_for_a_person_take_only_the_two_column_views(
    api: TestClient, state: AppState, alice: str
):
    response = api.get("/api/views/todos?view=mine&person=alice-smith")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation"
    unset_me(state)
    response = api.get("/api/views/todos?view=waiting-on-them&person=alice-smith")
    assert response.status_code == 200


@pytest.fixture
def portfolio(state: AppState, alice: str) -> None:
    put(state, "themes/platform.md", "---\ntitle: Platform\n---\n")
    put(
        state,
        "projects/migrate.md",
        "---\ntitle: Migrate\ntheme: platform\nstatus: blocked\nlead: alice-smith\n---\n",
    )
    put(
        state,
        "deliverables/cutover.md",
        "---\ntitle: Cutover\nproject: migrate\nstatus: active\n---\n",
    )


def test_portfolio_board(api: TestClient, portfolio: None):
    response = api.get("/api/views/portfolio?mode=board&kind=project&themes=platform,other")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "board"
    assert body["kind"] == "project"
    assert [c["status"] for c in body["columns"]] == [
        "not-started",
        "active",
        "on-hold",
        "blocked",
        "done",
    ]
    assert [i["id"] for i in body["columns"][3]["items"]] == ["migrate"]
    assert [t["id"] for t in body["chips"]] == ["platform"]
    assert body["names"] == {"alice-smith": "Alice Smith", "platform": "Platform"}
    assert body["attention"] == {}


def test_portfolio_board_carries_attention_and_the_no_theme_filter(
    api: TestClient, state: AppState, portfolio: None
):
    put(state, "projects/loose.md", "---\ntitle: Loose\nstatus: active\n---\n")
    put(
        state,
        "deliverables/stuck.md",
        "---\ntitle: Stuck\nproject: migrate\nstatus: blocked\n---\n",
    )
    body = api.get("/api/views/portfolio?mode=board").json()
    assert [d["id"] for d in body["attention"]["migrate"]] == ["stuck"]
    body = api.get("/api/views/portfolio?mode=board&unthemed=true").json()
    assert [i["id"] for c in body["columns"] for i in c["items"]] == ["loose"]
    body = api.get("/api/views/portfolio?mode=outline&unthemed=true").json()
    assert [g["theme"] for g in body["themes"]] == [None]


def test_portfolio_outline(api: TestClient, portfolio: None):
    body = api.get("/api/views/portfolio?mode=outline").json()
    assert body["mode"] == "outline"
    [group] = body["themes"]
    assert group["theme"]["id"] == "platform"
    [project] = group["projects"]
    assert project["project"]["id"] == "migrate"
    assert [d["id"] for d in project["deliverables"]] == ["cutover"]
    assert body["without_project"] == []
    assert [t["id"] for t in body["chips"]] == ["platform"]


def test_portfolio_errors(api: TestClient):
    assert api.get("/api/views/portfolio?mode=list").json()["error"]["code"] == "validation"
    response = api.get("/api/views/portfolio?mode=board&kind=theme")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation"
