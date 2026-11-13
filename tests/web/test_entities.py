"""SPEC §17.2: Entities and Templates, with the §17.1 error mapping."""

from pathlib import Path

from fastapi.testclient import TestClient

from memex.web.app import AppState


def new(api: TestClient, type: str, **fields) -> dict:
    response = api.post("/api/entities", json={"type": type, "fields": fields})
    assert response.status_code == 201, response.text
    return response.json()


def test_create_returns_the_id_path_and_hash(api: TestClient, root: Path):
    response = api.post(
        "/api/entities", json={"type": "project", "fields": {"title": "Data migration"}}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["id"] == "data-migration"
    assert body["path"] == "projects/data-migration.md"
    assert response.headers["etag"] == f'"{body["hash"]}"'
    assert "## Goal" in (root / "projects/data-migration.md").read_text()


def test_create_a_note_with_a_template(api: TestClient):
    new_note = api.post(
        "/api/entities",
        json={"type": "note", "fields": {"title": "Platform sync"}, "template": "meeting"},
    ).json()
    assert new_note["path"] == "notes/2026-11-12-platform-sync.md"


def test_create_maps_validation_to_422_with_field_errors(api: TestClient):
    response = api.post(
        "/api/entities", json={"type": "project", "fields": {"title": "X", "status": "wip"}}
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation"
    [field_error] = error["field_errors"]
    assert field_error["field"] == "status"
    assert field_error["allowed"][0] == "not-started"


def test_create_maps_unknown_reference_to_422_with_suggestions(api: TestClient):
    response = api.post(
        "/api/entities",
        json={"type": "todo", "fields": {"title": "X", "owner": "ada-lovelase"}},
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "unknown_reference"
    assert error["suggestions"] == ["ada-lovelace"]
    assert error["field_errors"][0]["field"] == "owner"


def test_create_an_unknown_type_is_422(api: TestClient):
    response = api.post("/api/entities", json={"type": "widget", "fields": {"title": "X"}})
    assert response.status_code == 422


def test_list_entities_with_filters(api: TestClient):
    new(api, "project", title="A", status="blocked")
    new(api, "project", title="B")
    response = api.get("/api/entities", params={"type": "project", "status": "blocked"})
    assert response.status_code == 200
    [only] = response.json()["entities"]
    assert only["id"] == "a"
    assert only["type"] == "project"
    assert only["fields"]["status"] == "blocked"
    assert only["fields"]["created"] == "2026-11-12"
    assert only["hash"]


def test_list_entities_bad_date_is_422(api: TestClient):
    assert api.get("/api/entities", params={"due_before": "soon"}).status_code == 422


def test_entity_detail(api: TestClient):
    new(api, "project", title="Data migration", lead="ada-lovelace")
    new(api, "deliverable", title="Cutover", project="data-migration")
    response = api.get("/api/entities/data-migration")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "data-migration"
    assert body["type"] == "project"
    assert body["fields"]["lead"] == "ada-lovelace"
    assert body["names"] == {"ada-lovelace": "Ada Lovelace"}
    assert body["body"].startswith("## Goal")
    assert [c["id"] for c in body["children"]] == ["cutover"]
    assert body["broken"] == []
    assert response.headers["etag"] == f'"{body["hash"]}"'


def test_entity_detail_missing_is_404_and_ambiguous_is_409(api: TestClient, root: Path):
    assert api.get("/api/entities/nope").status_code == 404
    (root / "notes/Ada-Lovelace.md").write_text("x\n")
    state: AppState = api.app.state.memex  # type: ignore[attr-defined]
    assert state.workspace is not None
    state.workspace.changed("notes/Ada-Lovelace.md")  # no watcher in tests
    response = api.get("/api/entities/ada-lovelace")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ambiguous_id"


def test_patch_fields_is_hash_checked(api: TestClient, root: Path):
    created = new(api, "project", title="Data migration")
    response = api.patch(
        "/api/entities/data-migration",
        json={"set": {"status": "active"}, "unset": []},
        headers={"If-Match": f'"{created["hash"]}"'},
    )
    assert response.status_code == 200
    assert "status: active" in (root / "projects/data-migration.md").read_text()

    stale = api.patch(
        "/api/entities/data-migration",
        json={"set": {"status": "done"}},
        headers={"If-Match": f'"{created["hash"]}"'},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "conflict"
    assert "status: active" in stale.json()["error"]["current"]["content"]


def test_patch_without_if_match_is_422(api: TestClient):
    new(api, "project", title="Data migration")
    response = api.patch("/api/entities/data-migration", json={"set": {"status": "active"}})
    assert response.status_code == 422


def test_put_body_replaces_only_the_body(api: TestClient, root: Path):
    created = new(api, "project", title="Data migration")
    response = api.put(
        "/api/entities/data-migration/body",
        json={"body": "Hello\n"},
        headers={"If-Match": created["hash"]},
    )
    assert response.status_code == 200
    text = (root / "projects/data-migration.md").read_text()
    assert text.endswith("---\nHello\n")
    assert response.json()["hash"] != created["hash"]

    stale = api.put(
        "/api/entities/data-migration/body",
        json={"body": "Again\n"},
        headers={"If-Match": created["hash"]},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["current"]["content"] == "Hello\n"


def test_diff_of_a_body_compares_against_the_body_on_disk(api: TestClient):
    new(api, "project", title="Data migration")
    response = api.post(
        "/api/diff",
        json={"path": "projects/data-migration.md", "content": "## Goal\n", "part": "body"},
    )
    assert response.status_code == 200
    rows = response.json()["rows"]
    assert rows[0] == {"kind": "equal", "disk": "## Goal", "mine": "## Goal"}
    assert all("title:" not in (r["disk"] or "") for r in rows)


def test_templates_list_for_a_type(api: TestClient):
    response = api.get("/api/templates", params={"type": "person"})
    assert response.status_code == 200
    body = response.json()
    assert [t["key"] for t in body["templates"]] == [
        "person/blank",
        "person/person",
        "person/stakeholder",
    ]
    assert body["default"] == "person/person"
    person = body["templates"][1]
    assert person["fields"] == {"kind": ["team-member"]}
    assert person["source"] == "builtin"


def test_templates_bad_type_is_422(api: TestClient):
    assert api.get("/api/templates", params={"type": "widget"}).status_code == 422


def test_customise_a_template(api: TestClient, root: Path):
    response = api.post("/api/templates/customise", json={"type": "note", "name": "meeting"})
    assert response.status_code == 201
    assert response.json() == {"path": ".memex/templates/note/meeting.md"}
    assert (root / ".memex/templates/note/meeting.md").exists()
    again = api.post("/api/templates/customise", json={"type": "note", "name": "meeting"})
    assert again.status_code == 409


def test_create_a_note_in_a_folder(api: TestClient):
    response = api.post(
        "/api/entities",
        json={"type": "note", "fields": {"title": "Retro"}, "folder": "meetings"},
    )
    assert response.status_code == 201
    assert response.json()["path"] == "meetings/retro.md"
    bad = api.post(
        "/api/entities", json={"type": "note", "fields": {"title": "R"}, "folder": "projects"}
    )
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "bad_path"


def test_settings_read_and_hide_a_template(api: TestClient, root: Path):
    settings = api.get("/api/settings").json()
    assert settings["workspace"]["me"] == "ada-lovelace"
    assert settings["workspace"]["hidden_templates"] == []
    assert settings["version"]

    response = api.put(
        "/api/settings",
        json={"workspace": {"hidden_templates": ["note/meeting"]}},
        headers={"If-Match": settings["hash"]},
    )
    assert response.status_code == 200
    [meeting] = [
        t
        for t in api.get("/api/templates", params={"type": "note"}).json()["templates"]
        if t["name"] == "meeting"
    ]
    assert meeting["hidden"] is True

    stale = api.put(
        "/api/settings",
        json={"workspace": {"hidden_templates": []}},
        headers={"If-Match": settings["hash"]},
    )
    assert stale.status_code == 409


def test_settings_bad_value_is_422(api: TestClient):
    settings = api.get("/api/settings").json()
    response = api.put(
        "/api/settings",
        json={"workspace": {"hidden_templates": ["note/blank"]}},
        headers={"If-Match": settings["hash"]},
    )
    assert response.status_code == 422
