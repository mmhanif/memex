"""SPEC §9 and §17.2: `GET /api/search`, with the §17.1 error mapping."""

from fastapi.testclient import TestClient

from memex.web.app import AppState
from tests.web.test_views import put


def test_search_returns_ranked_rows_with_context_counts_and_parsed_filters(
    api: TestClient, state: AppState
):
    put(state, "themes/platform.md", "---\ntitle: Platform\n---\n")
    put(
        state,
        "projects/data-migration.md",
        "---\ntitle: Data migration\ntheme: platform\nstatus: active\n---\n",
    )
    put(state, "notes/standup.md", "# Standup\n\nThe dmig cutover slipped.\n")

    response = api.get("/api/search", params={"q": "dmig type:project,note"})

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == {
        "text": "dmig",
        "filters": [{"kind": "type", "values": ["project", "note"], "token": "type:project,note"}],
        "errors": [],
    }
    assert body["total"] == 2
    assert body["counts"] == {"project": 1, "note": 1}
    project, note = body["hits"]
    assert project == {
        "kind": "file",
        "id": "data-migration",
        "type": "project",
        "title": "Data migration",
        "path": "projects/data-migration.md",
        "status": "active",
        "finished": False,
        "tier": 3,
        "context": "Platform",
        "snippets": [],
    }
    assert note["context"] == "notes"
    assert note["snippets"] == [{"text": "The dmig cutover slipped.", "highlights": [[4, 8]]}]


def test_search_rows_for_bookmarks_carry_the_url_and_line(api: TestClient, state: AppState):
    put(state, "bookmarks.md", "- [Wiki](https://w.example) team wiki #ref\n")
    [hit] = api.get("/api/search", params={"q": "wiki"}).json()["hits"]
    assert hit["kind"] == "bookmark"
    assert hit["bookmark"] == {
        "line": 1,
        "title": "Wiki",
        "url": "https://w.example",
        "note": "team wiki",
        "labels": ["ref"],
    }


def test_search_reports_token_errors_with_no_hits(api: TestClient):
    body = api.get("/api/search", params={"q": "ada @nobody"}).json()
    assert body["hits"] == []
    assert body["query"]["errors"] == [
        {"token": "@nobody", "message": "No Person matches @nobody", "candidates": []}
    ]


def test_search_pages_with_limit_and_offset(api: TestClient, state: AppState):
    for n in range(3):
        put(state, f"notes/plan-{n}.md", "x\n")
    body = api.get("/api/search", params={"q": "plan", "limit": 2, "offset": 2}).json()
    assert (body["total"], len(body["hits"])) == (3, 1)


def test_search_with_a_bad_limit_is_422_validation(api: TestClient):
    response = api.get("/api/search", params={"q": "x", "limit": 0})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation"
