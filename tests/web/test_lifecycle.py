"""SPEC §17.2: Rename id, guided delete, trash, Broken references, with §17.1 errors."""

from pathlib import Path

from fastapi.testclient import TestClient

from memex.web.app import AppState


def put(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def person(api: TestClient, title: str) -> str:
    response = api.post(
        "/api/entities",
        json={"type": "person", "fields": {"title": title, "kind": ["stakeholder"]}},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def todo_for(api: TestClient, owner: str) -> dict:
    response = api.post(
        "/api/entities", json={"type": "todo", "fields": {"title": "Call", "owner": owner}}
    )
    assert response.status_code == 201, response.text
    return response.json()


# Rename id


def test_rename_previews_then_applies_against_the_preview_hashes(api: TestClient, root: Path):
    alice = person(api, "Alice")
    todo = todo_for(api, alice)

    preview = api.post(f"/api/entities/{alice}/rename", json={"new_id": "alice-smith"}).json()
    assert preview["applied"] is False
    assert preview["impact"]["summary"] == "updates 1 reference in 1 file"
    [edit] = preview["impact"]["edits"]
    assert edit == {
        "path": todo["path"],
        "title": "Call",
        "hash": todo["hash"],
        "fields": ["owner"],
        "count": 1,
    }

    done = api.post(
        f"/api/entities/{alice}/rename",
        json={"new_id": "alice-smith", "dry_run": False, "hashes": preview["hashes"]},
    ).json()

    assert done["applied"] is True and done["skipped"] == []
    assert done["id"] == "alice-smith" and done["path"] == "people/alice-smith.md"
    assert "owner: alice-smith" in (root / todo["path"]).read_text()


def test_rename_to_a_taken_id_is_409_exists(api: TestClient):
    alice = person(api, "Alice")
    person(api, "Bob")

    response = api.post(f"/api/entities/{alice}/rename", json={"new_id": "bob"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "exists"


def test_rename_to_a_bad_id_is_422(api: TestClient):
    alice = person(api, "Alice")

    response = api.post(f"/api/entities/{alice}/rename", json={"new_id": "Alice Smith"})

    assert response.status_code == 422


# Delete


def test_delete_preview_shows_the_impact_and_what_blocks_remove(api: TestClient):
    alice = person(api, "Alice")
    todo = todo_for(api, alice)

    preview = api.post(f"/api/entities/{alice}/delete", json={"mode": "remove"}).json()

    assert preview["impact"]["blocked"] == [
        {"path": todo["path"], "title": "Call", "field": "owner"}
    ]


def test_a_plain_delete_with_references_is_409_with_the_referrers(api: TestClient):
    alice = person(api, "Alice")
    todo = todo_for(api, alice)

    response = api.post(f"/api/entities/{alice}/delete", json={"mode": "plain", "dry_run": False})

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "has_references"
    assert error["impact"] == {"referrers": [todo["path"]]}


def test_delete_with_replace_moves_the_file_to_trash(api: TestClient, root: Path):
    alice = person(api, "Alice")
    bob = person(api, "Bob")
    todo = todo_for(api, alice)

    done = api.post(
        f"/api/entities/{alice}/delete",
        json={"mode": "replace", "replacement": bob, "dry_run": False},
    ).json()

    assert done["trash"] == ".memex/trash/20261112-000000/people/alice.md"
    assert "owner: bob" in (root / todo["path"]).read_text()


def test_deleting_me_is_422(api: TestClient):
    response = api.post("/api/entities/ada-lovelace/delete", json={"mode": "plain"})

    assert response.status_code == 422
    assert "Me can't be deleted" in response.json()["error"]["message"]


# Archive's loose ends


def test_a_persons_detail_lists_loose_ends(api: TestClient):
    alice = person(api, "Alice")
    todo = todo_for(api, alice)

    detail = api.get(f"/api/entities/{alice}").json()

    [end] = detail["loose_ends"]
    assert end["label"] == "Owner of 1 open To-do"
    assert [i["id"] for i in end["items"]] == [todo["id"]]


# Trash


def test_trash_lists_and_restores(api: TestClient, root: Path):
    alice = person(api, "Alice")
    api.post(f"/api/entities/{alice}/delete", json={"mode": "plain", "dry_run": False})

    [entry] = api.get("/api/trash").json()["entries"]
    assert entry == {
        "entry": "20261112-000000",
        "path": "people/alice.md",
        "files": ["people/alice.md"],
        "deleted": "2026-11-12T00:00:00",
    }

    response = api.post("/api/trash/restore", json={"entry": entry["entry"]})

    assert response.status_code == 200
    assert (root / "people/alice.md").exists()
    assert api.get("/api/trash").json()["entries"] == []


def test_restoring_over_a_reused_id_is_409(api: TestClient, root: Path):
    alice = person(api, "Alice")
    api.post(f"/api/entities/{alice}/delete", json={"mode": "plain", "dry_run": False})
    person(api, "Alice")

    response = api.post("/api/trash/restore", json={"entry": "20261112-000000"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "exists"


def test_restoring_an_unknown_entry_is_404(api: TestClient):
    response = api.post("/api/trash/restore", json={"entry": "nope"})

    assert response.status_code == 404


# Broken references


def test_broken_references_list_and_create_repair(api: TestClient, state: AppState):
    assert state.workspace is not None
    text = "---\ntitle: T\nowner: zed\nrequester: ada-lovelace\nstatus: open\n---\n"
    put(state.workspace.root, "todos/t1.md", text)
    state.workspace.changed("todos/t1.md")  # no watcher in tests

    [group] = api.get("/api/broken-references").json()["groups"]
    assert group == {
        "id": "zed",
        "status": "missing",
        "uses": [
            {"path": "todos/t1.md", "id": "t1", "title": "T", "type": "todo", "field": "owner"}
        ],
        "types": ["person"],
        "create_types": ["person"],
    }

    response = api.post(
        "/api/broken-references/repair", json={"id": "zed", "action": "create", "dry_run": False}
    )

    assert response.status_code == 200, response.text
    assert response.json()["path"] == "people/zed.md"
    assert api.get("/api/broken-references").json()["groups"] == []


def test_repairing_an_id_that_isnt_broken_is_404(api: TestClient):
    response = api.post("/api/broken-references/repair", json={"id": "zed", "action": "remove"})

    assert response.status_code == 404


# Archive


def test_archive_and_unarchive(api: TestClient, root: Path):
    alice = person(api, "Alice")
    detail = api.get(f"/api/entities/{alice}").json()
    assert detail["archivable"] is True

    archived = api.post(
        f"/api/entities/{alice}/archive",
        json={"archived": True},
        headers={"If-Match": detail["hash"]},
    )
    assert archived.status_code == 200, archived.text
    assert "archived: 2026-11-12" in (root / "people/alice.md").read_text()

    response = api.post(
        f"/api/entities/{alice}/archive",
        json={"archived": False},
        headers={"If-Match": archived.json()["hash"]},
    )
    assert response.status_code == 200
    assert "archived" not in (root / "people/alice.md").read_text()


def test_archiving_me_is_422(api: TestClient):
    me = api.get("/api/entities/ada-lovelace").json()

    response = api.post(
        "/api/entities/ada-lovelace/archive",
        json={"archived": True},
        headers={"If-Match": me["hash"]},
    )

    assert response.status_code == 422


# Repair: Replace and Remove


def broken_owner(state: AppState) -> None:
    assert state.workspace is not None
    text = "---\ntitle: T\nowner: zed\nrequester: ada-lovelace\nstatus: open\n---\nAsk [[zed]].\n"
    put(state.workspace.root, "todos/t1.md", text)
    state.workspace.changed("todos/t1.md")


def test_repair_replace_previews_then_rewrites(api: TestClient, state: AppState, root: Path):
    broken_owner(state)
    zoe = person(api, "Zoe")

    preview = api.post(
        "/api/broken-references/repair", json={"id": "zed", "action": "replace", "replacement": zoe}
    ).json()
    assert preview["applied"] is False
    assert preview["impact"]["summary"] == "updates 2 references in 1 file"

    done = api.post(
        "/api/broken-references/repair",
        json={
            "id": "zed",
            "action": "replace",
            "replacement": zoe,
            "dry_run": False,
            "hashes": preview["hashes"],
        },
    ).json()

    assert done["applied"] is True
    assert (
        (root / "todos/t1.md")
        .read_text()
        .endswith("owner: zoe\nrequester: ada-lovelace\nstatus: open\n---\nAsk [[zoe]].\n")
    )


def test_repair_replace_with_the_wrong_type_is_422(api: TestClient, state: AppState):
    broken_owner(state)
    api.post("/api/entities", json={"type": "theme", "fields": {"title": "Platform"}})

    response = api.post(
        "/api/broken-references/repair",
        json={"id": "zed", "action": "replace", "replacement": "platform", "dry_run": False},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unknown_reference"


def test_repair_remove_blocked_by_a_required_reference_is_422(api: TestClient, state: AppState):
    broken_owner(state)

    preview = api.post("/api/broken-references/repair", json={"id": "zed", "action": "remove"})
    assert preview.json()["impact"]["blocked"] == [
        {"path": "todos/t1.md", "title": "T", "field": "owner"}
    ]
    response = api.post(
        "/api/broken-references/repair", json={"id": "zed", "action": "remove", "dry_run": False}
    )

    assert response.status_code == 422
    assert "Remove is blocked" in response.json()["error"]["message"]
