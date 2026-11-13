"""SPEC §17.2: raw files and the tree, with the §17.1 error mapping."""

from pathlib import Path

from fastapi.testclient import TestClient

from memex.core.store import content_hash
from memex.web.app import AppState
from tests.web.conftest import PORT, client_for


def put(root: Path, rel: str, data: bytes) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def test_get_file_returns_content_and_hash_as_etag(api: TestClient, root: Path):
    put(root, "notes/a.md", b"# A\r\nhello\r\n")

    response = api.get("/api/files", params={"path": "notes/a.md"})

    assert response.status_code == 200
    expected_hash = content_hash(b"# A\r\nhello\r\n")
    assert response.json() == {
        "path": "notes/a.md",
        "content": "# A\nhello\n",
        "hash": expected_hash,
    }
    assert response.headers["etag"] == f'"{expected_hash}"'


def test_get_missing_file_is_404_not_found(api: TestClient):
    response = api.get("/api/files", params={"path": "notes/nope.md"})

    assert response.status_code == 404
    assert response.json()["error"] == {"code": "not_found", "message": "notes/nope.md not found"}


def test_get_non_utf8_file_is_a_validation_error_not_a_crash(api: TestClient, root: Path):
    put(root, "notes/latin.md", "café".encode("latin-1"))

    response = api.get("/api/files", params={"path": "notes/latin.md"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation"


def test_create_file(api: TestClient, root: Path):
    response = api.post("/api/files", json={"path": "notes/new.md", "content": "hi"})

    assert response.status_code == 201
    assert response.json() == {"path": "notes/new.md", "hash": content_hash(b"hi\n")}
    assert (root / "notes/new.md").read_bytes() == b"hi\n"


def test_create_taken_path_is_409_exists(api: TestClient, root: Path):
    put(root, "notes/a.md", b"old\n")

    response = api.post("/api/files", json={"path": "notes/a.md", "content": "new"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "exists"
    assert (root / "notes/a.md").read_bytes() == b"old\n"


def test_create_non_md_is_400_bad_path(api: TestClient, root: Path):
    response = api.post("/api/files", json={"path": "notes/x.txt", "content": "x"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "bad_path"
    assert not (root / "notes/x.txt").exists()


def test_body_missing_a_field_is_422_validation_with_field_errors(api: TestClient):
    response = api.post("/api/files", json={"path": "notes/x.md"})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation"
    assert error["field_errors"][0]["field"] == "content"


def test_put_with_current_hash_overwrites(api: TestClient, root: Path):
    put(root, "notes/a.md", b"old\r\n")
    old = content_hash(b"old\r\n")

    response = api.put(
        "/api/files",
        json={"path": "notes/a.md", "content": "new\n"},
        headers={"If-Match": f'"{old}"'},
    )

    assert response.status_code == 200
    assert response.json() == {"path": "notes/a.md", "hash": content_hash(b"new\r\n")}
    assert response.headers["etag"] == f'"{content_hash(b"new\r\n")}"'
    assert (root / "notes/a.md").read_bytes() == b"new\r\n"


def test_put_with_stale_hash_is_409_conflict_carrying_current(api: TestClient, root: Path):
    put(root, "notes/a.md", b"outside edit\n")

    response = api.put(
        "/api/files",
        json={"path": "notes/a.md", "content": "mine\n"},
        headers={"If-Match": '"stale"'},
    )

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "conflict"
    assert error["current"] == {
        "hash": content_hash(b"outside edit\n"),
        "content": "outside edit\n",
    }
    assert (root / "notes/a.md").read_bytes() == b"outside edit\n"


def test_put_without_if_match_is_422_validation(api: TestClient, root: Path):
    put(root, "notes/a.md", b"old\n")

    response = api.put("/api/files", json={"path": "notes/a.md", "content": "new\n"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation"
    assert (root / "notes/a.md").read_bytes() == b"old\n"


def test_read_only_workspace_write_is_423(root: Path, home: Path):
    config = root / ".memex/config.yaml"
    config.write_text(config.read_text().replace("format: 1", "format: 2"))
    state = AppState.for_workspace(root, port=PORT, home=home)

    with client_for(state) as api:
        response = api.post("/api/files", json={"path": "notes/new.md", "content": "x"})

    assert response.status_code == 423
    assert response.json()["error"]["code"] == "read_only"


def hinted(state: AppState, rel: str, data: bytes) -> None:
    """An outside write plus the watcher's hint for it (the watcher arrives with SSE)."""
    assert state.workspace is not None
    put(state.workspace.root, rel, data)
    state.workspace.changed(rel)


def test_tree_lists_folders_and_indexed_files(api: TestClient, state: AppState):
    hinted(state, "notes/a.md", b"---\ntitle: Alpha\n---\nbody\n")
    hinted(state, "notes/sub/b.md", b"# Beta\n")
    hinted(state, ".obsidian/x.md", b"hidden\n")
    hinted(state, "notes/c.txt", b"not markdown\n")

    response = api.get("/api/tree")

    assert response.status_code == 200
    tree = response.json()
    assert tree["folders"] == [
        "deliverables",
        "glossary",
        "notes",
        "notes/sub",
        "people",
        "projects",
        "themes",
        "todos",
    ]
    by_path = {f["path"]: f for f in tree["files"]}
    assert set(by_path) == {
        "bookmarks.md",
        "notes/a.md",
        "notes/sub/b.md",
        "people/ada-lovelace.md",
    }
    assert by_path["notes/a.md"]["title"] == "Alpha"
    assert by_path["notes/a.md"]["type"] is None
    assert by_path["people/ada-lovelace.md"]["type"] == "person"
    assert by_path["people/ada-lovelace.md"]["id"] == "ada-lovelace"


def test_tree_flags_warnings(api: TestClient, state: AppState):
    hinted(state, "notes/bad.md", b"---\ntitle: [unclosed\n---\n")

    tree = api.get("/api/tree").json()

    [bad] = [f for f in tree["files"] if f["path"] == "notes/bad.md"]
    assert bad["warnings"][0]["kind"] == "parse"


def test_unknown_api_route_is_404_not_found(api: TestClient):
    response = api.get("/api/nope")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


# Files page: new folder, move, delete (§11.8, §17.2)


def test_new_folder(api: TestClient, root: Path):
    response = api.post("/api/folders", json={"path": "notes/trips"})

    assert response.status_code == 201
    assert response.json() == {"path": "notes/trips"}
    assert (root / "notes/trips").is_dir()
    assert "notes/trips" in api.get("/api/tree").json()["folders"]


def test_new_folder_that_exists_is_409_exists(api: TestClient):
    response = api.post("/api/folders", json={"path": "notes"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "exists"


def test_move_renames_and_updates_the_tree(api: TestClient, state: AppState):
    hinted(state, "notes/a.md", b"# A\n")

    response = api.post("/api/move", json={"from": "notes/a.md", "to": "meetings/a.md"})

    assert response.status_code == 200
    assert response.json() == {"from": "notes/a.md", "to": "meetings/a.md"}
    paths = {f["path"] for f in api.get("/api/tree").json()["files"]}
    assert "meetings/a.md" in paths
    assert "notes/a.md" not in paths


def test_move_a_typed_entity_out_of_its_folder_is_400(api: TestClient, root: Path):
    put(root, "projects/x.md", b"---\ntitle: X\n---\n")

    response = api.post("/api/move", json={"from": "projects/x.md", "to": "notes/x.md"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "bad_path"


def test_move_missing_source_is_404(api: TestClient):
    response = api.post("/api/move", json={"from": "notes/nope.md", "to": "notes/b.md"})

    assert response.status_code == 404


def test_R14_move_refusals(api: TestClient, root: Path):
    put(root, "notes/a.md", b"a\n")
    put(root, "notes/b.md", b"b\n")
    put(root, "notes/f/x.md", b"x\n")

    responses = {
        "root as source": api.post("/api/move", json={"from": "", "to": "notes/z"}),
        "outside the root": api.post("/api/move", json={"from": "notes/a.md", "to": "../a.md"}),
        "into a descendant": api.post("/api/move", json={"from": "notes/f", "to": "notes/f/g"}),
        "existing": api.post("/api/move", json={"from": "notes/a.md", "to": "notes/b.md"}),
    }

    assert {k: r.status_code for k, r in responses.items()} == {
        "root as source": 400,
        "outside the root": 400,
        "into a descendant": 400,
        "existing": 409,
    }
    assert (root / "notes/a.md").read_bytes() == b"a\n"
    assert (root / "notes/b.md").read_bytes() == b"b\n"
    assert (root / "notes/f/x.md").exists()


def test_R14_move_with_overwrite_replaces_the_destination(api: TestClient, root: Path):
    put(root, "notes/a.md", b"a\n")
    put(root, "notes/b.md", b"b\n")

    response = api.post(
        "/api/move", json={"from": "notes/a.md", "to": "notes/b.md", "overwrite": True}
    )

    assert response.status_code == 200
    assert (root / "notes/b.md").read_bytes() == b"a\n"


def test_delete_moves_to_trash(api: TestClient, state: AppState):
    hinted(state, "notes/a.md", b"# A\n")

    response = api.delete("/api/files", params={"path": "notes/a.md"})

    assert response.status_code == 200
    assert response.json() == {
        "path": "notes/a.md",
        "trash": ".memex/trash/20261112-000000/notes/a.md",
    }
    assert state.workspace is not None
    assert (state.workspace.root / ".memex/trash/20261112-000000/notes/a.md").exists()


def test_delete_with_incoming_references_is_409_with_impact(api: TestClient, state: AppState):
    hinted(state, "notes/a.md", b"# A\n")
    hinted(state, "notes/b.md", b"see [[a]]\n")

    response = api.delete("/api/files", params={"path": "notes/a.md"})

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "has_references"
    assert error["impact"] == {"referrers": ["notes/b.md"]}


def test_delete_missing_is_404(api: TestClient):
    response = api.delete("/api/files", params={"path": "notes/nope.md"})

    assert response.status_code == 404


def test_tree_carries_the_workspace_status_for_the_banners(api: TestClient):
    status = api.get("/api/tree").json()["workspace"]

    assert status == {
        "read_only": False,
        "config_error": None,
        "me_set": True,
        "me": "ada-lovelace",
    }


def test_tree_status_flags_a_broken_config_and_missing_me(api: TestClient, state: AppState):
    hinted(state, ".memex/config.yaml", b"format: 1\nme: [unclosed\n")

    status = api.get("/api/tree").json()["workspace"]

    assert status["me_set"] is False
    assert status["me"] is None
    assert status["config_error"] is not None


def test_delete_a_type_folder_is_400_and_keeps_it(api: TestClient, root: Path):
    response = api.delete("/api/files", params={"path": "people"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "bad_path"
    assert (root / "people/ada-lovelace.md").exists()
