"""SPEC §17.2: inline capture preview and confirm, with the §17.1 error mapping."""

import pytest
from fastapi.testclient import TestClient

from memex.web.app import AppState
from tests.web.test_views import put

NOTE = "notes/standup.md"


@pytest.fixture
def note(state: AppState) -> str:
    put(state, "people/alice-smith.md", "---\ntitle: Alice Smith\nkind: [team-member]\n---\n")
    put(state, NOTE, "---\ntitle: Standup\n---\n- [ ] Draft plan @alice due:2026-11-20\n  why\n")
    return "standup"


def test_preview_lists_rows_with_the_note_hash(api: TestClient, note: str):
    response = api.get(f"/api/notes/{note}/capture")
    assert response.status_code == 200
    body = response.json()
    assert body["hash"] == response.headers["ETag"].strip('"')
    assert body["rows"] == [
        {
            "index": 0,
            "line": 1,
            "text": "Draft plan @alice due:2026-11-20",
            "title": "Draft plan",
            "owner": "alice-smith",
            "requester": "ada-lovelace",
            "due": "2026-11-20",
            "about": None,
            "body": "why\n",
            "errors": [],
        }
    ]
    assert body["names"]["alice-smith"] == "Alice Smith"


def test_preview_of_a_missing_note_is_404(api: TestClient):
    assert api.get("/api/notes/missing/capture").json()["error"]["code"] == "not_found"


def test_confirm_creates_todos_and_rewrites_the_note(api: TestClient, note: str, state: AppState):
    hash = api.get(f"/api/notes/{note}/capture").json()["hash"]
    response = api.post(
        f"/api/notes/{note}/capture",
        json={"hash": hash, "rows": [{"index": 0, "edits": {"requester": "alice-smith"}}]},
    )
    assert response.status_code == 201
    body = response.json()
    assert [t["id"] for t in body["todos"]] == ["2026-11-12-draft-plan"]
    assert body["note"]["hash"] == response.headers["ETag"].strip('"')
    assert state.workspace is not None
    text = (state.workspace.root / NOTE).read_text()
    assert text.endswith("- [ ] [[2026-11-12-draft-plan]]\n")
    detail = api.get(f"/api/entities/{note}").json()
    assert detail["unconverted_todos"] == 0


def test_confirm_against_a_stale_hash_is_409_conflict(api: TestClient, note: str):
    response = api.post(
        f"/api/notes/{note}/capture", json={"hash": "0" * 64, "rows": [{"index": 0}]}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_confirm_with_an_unfixed_error_is_422(api: TestClient, state: AppState, note: str):
    put(state, NOTE, "- [ ] Review due:2026-02-30\n")
    hash = api.get(f"/api/notes/{note}/capture").json()["hash"]
    response = api.post(f"/api/notes/{note}/capture", json={"hash": hash, "rows": [{"index": 0}]})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation"


def test_a_note_detail_counts_unconverted_todos(api: TestClient, note: str):
    assert api.get(f"/api/entities/{note}").json()["unconverted_todos"] == 1
    assert "unconverted_todos" not in api.get("/api/entities/alice-smith").json()


def test_dashboard_lists_notes_with_todos_to_create(api: TestClient, note: str):
    body = api.get("/api/views/dashboard").json()
    assert [n["id"] for n in body["capture_notes"]] == ["standup"]


def test_a_detail_carries_the_todos_its_body_mentions(api: TestClient, state: AppState, note: str):
    put(state, "todos/t1.md", "---\ntitle: T1\nowner: alice-smith\nrequester: ada-lovelace\n---\n")
    put(state, NOTE, "- [ ] [[t1]]\nSee [[alice-smith]]\n")
    body = api.get(f"/api/entities/{note}").json()
    assert [t["id"] for t in body["mentioned_todos"]] == ["t1"]


def test_confirm_with_an_unmatched_person_is_422_unknown_reference(
    api: TestClient, state: AppState, note: str
):
    put(state, NOTE, "- [ ] Review @zz\n")
    hash = api.get(f"/api/notes/{note}/capture").json()["hash"]
    response = api.post(f"/api/notes/{note}/capture", json={"hash": hash, "rows": [{"index": 0}]})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unknown_reference"
