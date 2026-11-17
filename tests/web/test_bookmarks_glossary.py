"""SPEC §17.2: the Bookmarks and Glossary routes (§10), with the §17.1 error mapping."""

from pathlib import Path

from fastapi.testclient import TestClient

from memex.web.app import AppState
from tests.web.conftest import PORT, client_for
from tests.web.test_views import put


def test_bookmarks_lists_every_line_with_its_bookmark(api: TestClient, state: AppState):
    put(state, "bookmarks.md", "# Work\n- [Wiki](https://w.example) team wiki #ref\n")
    assert api.get("/api/bookmarks").json() == {
        "lines": [
            {"line": 1, "text": "# Work", "bookmark": None},
            {
                "line": 2,
                "text": "- [Wiki](https://w.example) team wiki #ref",
                "bookmark": {
                    "line": 2,
                    "title": "Wiki",
                    "url": "https://w.example",
                    "note": "team wiki",
                    "labels": ["ref"],
                },
            },
        ],
        "labels": ["ref"],
    }


def test_bookmarks_filters_by_label(api: TestClient, state: AppState):
    put(state, "bookmarks.md", "- https://a.example #x\n- https://b.example #y\n")
    lines = api.get("/api/bookmarks?label=y").json()["lines"]
    assert [n["bookmark"]["url"] for n in lines] == ["https://b.example"]


def test_adding_a_bookmark_appends_its_line(api: TestClient, root: Path):
    response = api.post(
        "/api/bookmarks",
        json={"url": "https://w.example", "title": "Wiki", "note": "team", "labels": ["ref"]},
    )
    assert response.status_code == 201
    assert response.headers["ETag"] == f'"{response.json()["hash"]}"'
    assert response.json()["path"] == "bookmarks.md"
    assert (root / "bookmarks.md").read_text() == "- [Wiki](https://w.example) team #ref\n"


def test_adding_a_bad_bookmark_is_422_with_field_errors(api: TestClient, root: Path):
    response = api.post("/api/bookmarks", json={"url": "javascript:alert(1)"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation"
    assert [e["field"] for e in error["field_errors"]] == ["url"]
    assert (root / "bookmarks.md").read_text() == ""


def test_adding_in_a_read_only_workspace_is_423(root: Path, home: Path):
    config = root / ".memex/config.yaml"
    config.write_text(config.read_text().replace("format: 1", "format: 2"))
    with client_for(AppState.for_workspace(root, port=PORT, home=home)) as api:
        response = api.post("/api/bookmarks", json={"url": "https://w.example"})
    assert response.status_code == 423
    assert response.json()["error"]["code"] == "read_only"


def test_glossary_lists_terms_by_letter_with_aliases_and_definitions(
    api: TestClient, state: AppState
):
    put(state, "glossary/slo.md", "---\ntitle: SLO\naliases: [SLOs]\n---\nUptime target.\n")
    body = api.get("/api/views/glossary").json()
    [group] = body["groups"]
    assert group["letter"] == "S"
    [term] = group["terms"]
    assert (term["id"], term["title"], term["path"]) == ("slo", "SLO", "glossary/slo.md")
    assert term["aliases"] == ["SLOs"]
    assert term["definition"] == "Uptime target.\n"


def test_glossary_without_a_workspace_is_404(api: TestClient, state: AppState):
    state.workspace = None
    response = api.get("/api/views/glossary")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
