"""SPEC §5.7, §17.2: `POST /api/diff`, the conflict banner's Compare."""

from pathlib import Path

from fastapi.testclient import TestClient

from memex.core.store import content_hash


def test_diff_pairs_disk_lines_with_the_editors_side_by_side(api: TestClient, root: Path):
    (root / "notes/a.md").write_bytes(b"one\ntwo\nthree\nfour\n")

    response = api.post(
        "/api/diff",
        json={"path": "notes/a.md", "content": "one\nTWO\nthree\nfour\nfive\n"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "path": "notes/a.md",
        "hash": content_hash(b"one\ntwo\nthree\nfour\n"),
        "rows": [
            {"kind": "equal", "disk": "one", "mine": "one"},
            {"kind": "replace", "disk": "two", "mine": "TWO"},
            {"kind": "equal", "disk": "three", "mine": "three"},
            {"kind": "equal", "disk": "four", "mine": "four"},
            {"kind": "insert", "disk": None, "mine": "five"},
        ],
    }


def test_uneven_replace_blocks_pad_the_shorter_side(api: TestClient, root: Path):
    (root / "notes/a.md").write_bytes(b"a\nb\nc\n")

    rows = api.post("/api/diff", json={"path": "notes/a.md", "content": "x\n"}).json()["rows"]

    assert rows == [
        {"kind": "replace", "disk": "a", "mine": "x"},
        {"kind": "delete", "disk": "b", "mine": None},
        {"kind": "delete", "disk": "c", "mine": None},
    ]


def test_diff_against_a_missing_file_is_404(api: TestClient):
    response = api.post("/api/diff", json={"path": "notes/gone.md", "content": "x"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
