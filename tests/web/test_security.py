"""SPEC §12: one test per rule, named by its ID (§16.6)."""

import base64
import hashlib
import os
import re
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from memex.core.workspace import Workspace
from memex.web.app import AppState, create_app
from memex.web.security import csp_for
from memex.web.session import COOKIE
from tests.core.hostile_paths import HOSTILE_PATHS
from tests.web.conftest import ORIGIN, PORT, client_for

BAD_HOSTS = [
    f"evil.example:{PORT}",
    f"127.0.0.1.evil.example:{PORT}",
    "127.0.0.1",  # no port
    f"127.0.0.1:{PORT + 1}",  # wrong port: Starlette's TrustedHostMiddleware ignores ports
    f"localhost:{PORT + 1}",
    f"[::1]:{PORT}",
]


@pytest.mark.parametrize("host", BAD_HOSTS)
@pytest.mark.parametrize("path", ["/", "/static/index.html", "/api/tree", "/auth", "/relaunch"])
def test_R04_wrong_host_gets_421_on_every_route(page_client: TestClient, host: str, path: str):
    response = page_client.get(path, headers={"Host": host, "X-Memex": "1"})

    assert response.status_code == 421


def test_R04_missing_host_gets_421(page_client: TestClient):
    # httpx always sends Host, so drive the ASGI app directly.
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [],
        "scheme": "http",
        "server": ("127.0.0.1", PORT),
        "client": ("127.0.0.1", 50000),
        "root_path": "",
    }
    # On its own thread: pytest-playwright keeps an event loop running on this one.
    app = page_client.app
    with ThreadPoolExecutor(1) as pool:
        pool.submit(asyncio.run, app(scope, receive, send)).result()  # type: ignore[arg-type]

    assert sent[0]["status"] == 421


@pytest.mark.parametrize("host", [f"127.0.0.1:{PORT}", f"localhost:{PORT}", f"LOCALHOST:{PORT}"])
def test_R04_allowed_hosts_pass(page_client: TestClient, host: str):
    assert page_client.get("/", headers={"Host": host}).status_code == 200


@pytest.mark.parametrize("path", ["/", "/static/index.html", "/api/tree", "/api/files?path=x.md"])
def test_R05_no_cookie_gets_401(anon: TestClient, path: str):
    response = anon.get(path, headers={"X-Memex": "1"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


def test_R05_wrong_cookie_gets_401(anon: TestClient):
    anon.cookies.set(COOKIE, "0" * 64)

    assert anon.get("/").status_code == 401


def test_R05_relaunch_page_needs_no_cookie(anon: TestClient):
    response = anon.get("/relaunch")

    assert response.status_code == 200
    assert "memex" in response.text.lower()


def test_R06_auth_sets_a_strict_httponly_cookie_and_redirects(anon: TestClient, state: AppState):
    code = state.session.issue_code()

    response = anon.get(f"/auth?code={code}")

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE}={state.session.secret};")
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie or "SameSite=Strict" in cookie
    assert "Path=/" in cookie
    assert anon.get("/").status_code == 200


def test_R06_reused_code_gets_401(anon: TestClient, state: AppState):
    code = state.session.issue_code()
    anon.get(f"/auth?code={code}")
    anon.cookies.clear()

    response = anon.get(f"/auth?code={code}")

    assert response.status_code == 401
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("query", ["?code=wrong", "", "?code=", "?code=%C3%BC"])
def test_R06_wrong_or_missing_code_gets_401(anon: TestClient, state: AppState, query: str):
    state.session.issue_code()

    response = anon.get(f"/auth{query}")

    assert response.status_code == 401
    assert "set-cookie" not in response.headers


# R7: the secret never leaves the process except as the cookie value.


def test_R07_secret_never_in_a_response_body(api: TestClient, state: AppState):
    code = state.session.issue_code()
    bodies = [
        api.get(path).text
        for path in ("/", "/relaunch", "/api/tree", "/api/files?path=bookmarks.md", "/api/setup")
    ]
    bodies.append(api.get(f"/auth?code={code}").text)

    assert all(state.session.secret not in body for body in bodies)


# R8: no CORS.


@pytest.mark.parametrize("path", ["/", "/api/tree", "/api/files", "/auth", "/launcher/hello"])
def test_R08_no_cors_headers_and_no_successful_preflight(api: TestClient, path: str):
    preflight = api.options(
        path,
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-memex, content-type",
        },
    )
    simple = api.get(path, headers={"Origin": "http://evil.example"})

    assert preflight.status_code >= 400
    for response in (preflight, simple):
        assert not [h for h in response.headers if h.lower().startswith("access-control-")]


# R9: writes need an exact same-origin Origin and a safe Sec-Fetch-Site.

BAD_ORIGINS = [
    None,
    "null",
    f"http://127.0.0.1:{PORT + 1}",
    "http://evil.example",
    f"https://127.0.0.1:{PORT}",
    f"http://127.0.0.1:{PORT}/",
]


@pytest.mark.parametrize("origin", BAD_ORIGINS)
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_R09_write_with_bad_origin_is_403(api: TestClient, root: Path, origin, method: str):
    before = snapshot(root)
    headers = {"Content-Type": "application/json"}
    if origin is None:
        api.headers.pop("Origin")
    else:
        headers["Origin"] = origin

    response = api.request(
        method, "/api/files", content=b'{"path": "notes/x.md", "content": "x"}', headers=headers
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    assert snapshot(root) == before


@pytest.mark.parametrize("site", ["cross-site", "same-site"])
def test_R09_cross_site_fetch_metadata_is_403(api: TestClient, root: Path, site: str):
    response = api.post(
        "/api/files",
        json={"path": "notes/x.md", "content": "x"},
        headers={"Sec-Fetch-Site": site},
    )

    assert response.status_code == 403
    assert not (root / "notes/x.md").exists()


@pytest.mark.parametrize("origin", [ORIGIN, f"http://localhost:{PORT}"])
def test_R09_same_origin_write_passes(api: TestClient, origin: str):
    host = origin.removeprefix("http://")
    response = api.post(
        "/api/files",
        json={"path": "notes/x.md", "content": "x"},
        headers={"Origin": origin, "Host": host},
    )

    assert response.status_code == 201


def test_R09_origin_must_match_the_host_used(api: TestClient):
    response = api.post(
        "/api/files",
        json={"path": "notes/x.md", "content": "x"},
        headers={"Origin": f"http://localhost:{PORT}", "Host": f"127.0.0.1:{PORT}"},
    )

    assert response.status_code == 403


# R10: JSON bodies only, and X-Memex on every /api/* request.


@pytest.mark.parametrize(
    "content_type",
    ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x", None],
)
def test_R10_write_without_json_content_type_is_415(api: TestClient, root: Path, content_type):
    headers = {} if content_type is None else {"Content-Type": content_type}

    response = api.post(
        "/api/files", content=b'{"path": "notes/x.md", "content": "x"}', headers=headers
    )

    assert response.status_code == 415
    assert not (root / "notes/x.md").exists()


def test_R10_json_with_charset_is_accepted(api: TestClient):
    response = api.post(
        "/api/files",
        content=b'{"path": "notes/x.md", "content": "x"}',
        headers={"Content-Type": "application/json; charset=utf-8"},
    )

    assert response.status_code == 201


@pytest.mark.parametrize("value", [None, "0", "true"])
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_R10_api_request_without_x_memex_is_403(api: TestClient, value, method: str):
    if value is None:
        api.headers.pop("X-Memex")
    headers = {} if value is None else {"X-Memex": value}

    response = api.request(
        method,
        "/api/files?path=bookmarks.md",
        json={"path": "notes/x.md", "content": "x"},
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


# R11: no GET changes disk state.

ALL_GETS = [
    "/",
    "/static/index.html",
    "/relaunch",
    "/auth?code=wrong",
    "/api/trash",
    "/api/broken-references",
    "/api/tree",
    "/api/files?path=bookmarks.md",
    "/api/files?path=people/ada-lovelace.md",
    "/api/files?path=notes/missing.md",
    "/api/setup",
    "/api/entities",
    "/api/entities?type=project&due_before=2026-12-01",
    "/api/entities/ada-lovelace",
    "/api/entities/missing",
    "/api/templates?type=note",
    "/api/settings",
    "/api/views/todos?view=mine",
    "/api/views/todos?view=waiting-on-me&person=ada-lovelace&include_done=true",
    "/api/views/dashboard",
    "/api/views/people",
    "/api/views/portfolio?mode=board&kind=deliverable&themes=x",
    "/api/views/portfolio?mode=outline&include_archived=true",
    "/api/views/person/ada-lovelace",
    "/api/search?q=ada",
    "/api/search?q=type:note%20@nobody&limit=5&offset=5&include_archived=false",
]


def test_R11_no_get_changes_disk_state(api: TestClient, root: Path, state: AppState):
    get_paths = {
        route.path
        for route in _all_routes(api.app.routes)  # type: ignore[attr-defined]
        if "GET" in getattr(route, "methods", ())
    }
    assert "/api/tree" in get_paths, "route discovery found no included routes"
    # The endless event stream can't run under TestClient; test_events.py reads it live.
    covered = {p.split("?")[0] for p in ALL_GETS} | {"/api/events"}
    missing = {
        p
        for p in get_paths
        if not any(re.fullmatch(re.sub(r"\{\w+\}", "[^/]+", p), c) for c in covered)
    }
    assert not missing, f"add these GET routes to ALL_GETS: {missing}"
    before = snapshot(root)

    for path in ALL_GETS:
        api.get(path)
    api.get(f"/auth?code={state.session.issue_code()}")

    assert snapshot(root) == before


def _all_routes(routes: Iterable[Any]) -> Iterator[Any]:
    """Routes, including those inside included routers (FastAPI wraps them)."""
    for route in routes:
        if inner := getattr(route, "original_router", None):
            yield from _all_routes(inner.routes)
        else:
            yield route


# R12: hostile paths are 400 and leave disk unchanged.


@pytest.mark.parametrize("rel", HOSTILE_PATHS)
def test_R12_hostile_paths_are_400_and_change_nothing(api: TestClient, root: Path, rel: str):
    before = snapshot(root)

    responses = [
        api.get("/api/files", params={"path": rel}),
        api.post("/api/files", json={"path": rel, "content": "x"}),
        api.put("/api/files", json={"path": rel, "content": "x"}, headers={"If-Match": '"x"'}),
    ]

    assert [r.status_code for r in responses] == [400, 400, 400]
    assert all(r.json()["error"]["code"] == "bad_path" for r in responses)
    assert snapshot(root) == before


def test_R12_percent_encoded_traversal_is_decoded_then_refused(api: TestClient):
    response = api.get("/api/files?path=%2e%2e/x.md")

    assert response.status_code == 400


def test_R12_writing_a_non_md_file_is_400(api: TestClient, root: Path):
    response = api.post("/api/files", json={"path": "notes/run.bat", "content": "x"})

    assert response.status_code == 400
    assert not (root / "notes/run.bat").exists()


# R13 (read, write and walk here; move and delete in tests/core/test_files.py).


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_bytes(b"outside the Workspace\n")
    return outside


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_R13_links_out_of_the_workspace_are_refused(api: TestClient, root: Path, outside: Path):
    (root / "notes/linkdir").symlink_to(outside, target_is_directory=True)
    (root / "notes/link.md").symlink_to(outside / "secret.md")

    responses = [
        api.get("/api/files", params={"path": "notes/link.md"}),
        api.get("/api/files", params={"path": "notes/linkdir/secret.md"}),
        api.put(
            "/api/files",
            json={"path": "notes/link.md", "content": "x"},
            headers={"If-Match": '"x"'},
        ),
        api.post("/api/files", json={"path": "notes/linkdir/new.md", "content": "x"}),
    ]

    assert [r.status_code for r in responses] == [400, 400, 400, 400]
    assert (outside / "secret.md").read_bytes() == b"outside the Workspace\n"
    assert not (outside / "new.md").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_R13_tree_does_not_descend_links(state: AppState, root: Path, outside: Path):
    (root / "notes/linkdir").symlink_to(outside, target_is_directory=True)
    (root / "notes/link.md").symlink_to(outside / "secret.md")
    state.workspace = Workspace.open(root)

    with client_for(state) as api:
        tree = api.get("/api/tree").json()

    assert "notes/linkdir" not in tree["folders"]
    paths = {f["path"] for f in tree["files"]}
    assert "notes/link.md" not in paths
    assert "notes/linkdir/secret.md" not in paths


# R16: error bodies never hold absolute paths.


def test_R16_error_bodies_hold_no_absolute_paths(api: TestClient, root: Path, tmp_path: Path):
    (root / "notes/a.md").write_bytes(b"x\n")
    responses = [
        api.get("/api/files", params={"path": "notes/missing.md"}),
        api.get("/api/files", params={"path": "../x.md"}),
        api.post("/api/files", json={"path": "notes/a.md", "content": "x"}),
        api.put(
            "/api/files", json={"path": "notes/a.md", "content": "x"}, headers={"If-Match": '"x"'}
        ),
        api.get("/api/files", params={"path": "notes"}),
        api.get("/api/nope"),
        api.post("/api/setup/scan", json={"path": str(tmp_path / "nowhere")}),
    ]

    for response in responses:
        assert response.status_code >= 400
        assert str(tmp_path) not in response.text
        assert str(Path(os.path.realpath(tmp_path))) not in response.text


def test_R16_unexpected_errors_hide_their_details(
    state: AppState, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    assert state.workspace is not None

    def boom(rel: str):
        raise RuntimeError(f"failed at {tmp_path}/secret")

    monkeypatch.setattr(state.workspace.store, "read", boom)
    with TestClient(
        create_app(state, watch=False), base_url=ORIGIN, raise_server_exceptions=False
    ) as client:
        client.cookies.set(COOKIE, state.session.secret)
        response = client.get("/api/files?path=a.md", headers={"X-Memex": "1"})

    assert response.status_code == 500
    assert str(tmp_path) not in response.text
    assert response.headers["x-content-type-options"] == "nosniff"


# R18: CSP and nosniff.

EXPECTED_CSP_PARTS = [
    "default-src 'self'",
    "style-src 'self'",
    "img-src 'self' data:",
    "connect-src 'self'",
    "font-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
]


@pytest.mark.parametrize("path", ["/", "/static/index.html", "/relaunch"])
def test_R18_html_carries_the_csp_and_nosniff(page_client: TestClient, path: str):
    response = page_client.get(path)

    assert response.headers["content-type"].startswith("text/html")
    csp = [d.strip() for d in response.headers["content-security-policy"].split(";")]
    for part in EXPECTED_CSP_PARTS:
        assert part in csp
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_R18_script_src_allows_self_and_exactly_the_import_maps_hash(page_client: TestClient):
    # The HTML parser turns CRLF and CR into LF before Chrome hashes an inline script.
    html = page_client.get("/").text.replace("\r\n", "\n").replace("\r", "\n")
    import_map = html.split('<script type="importmap">', 1)[1].split("</script>", 1)[0]
    digest = base64.b64encode(hashlib.sha256(import_map.encode()).digest()).decode()

    csp = page_client.get("/").headers["content-security-policy"]

    assert f"script-src 'self' 'sha256-{digest}'" in csp


@pytest.mark.parametrize("path", ["/api/tree", "/api/nope", "/api/files?path=../x"])
def test_R18_json_carries_nosniff_and_json_type(api: TestClient, path: str):
    response = api.get(path)

    assert response.headers["content-type"] == "application/json"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" not in response.headers


def test_R18_refusals_carry_nosniff(anon: TestClient):
    for response in (anon.get("/api/tree"), anon.get("/", headers={"Host": "evil.example"})):
        assert response.headers["x-content-type-options"] == "nosniff"


def snapshot(root: Path) -> dict[str, bytes | None]:
    return {
        p.relative_to(root).as_posix(): (p.read_bytes() if p.is_file() else None)
        for p in sorted(root.rglob("*"))
    }


# R15: the Workspace root can't be deleted.


@pytest.mark.parametrize("rel", ["", ".", "/"])
def test_R15_deleting_the_workspace_root_is_refused(api: TestClient, root: Path, rel: str):
    before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))

    response = api.delete("/api/files", params={"path": rel})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "bad_path"
    assert sorted(p.relative_to(root).as_posix() for p in root.rglob("*")) == before


def test_R18_import_map_hash_matches_chrome_even_with_crlf(tmp_path: Path):
    # A Windows checkout may give index.html CRLF line endings. The HTML parser turns them
    # into LF before Chrome hashes the inline script, so the hash must be of the LF text.
    import_map = '{"imports": {\r\n  "a": "/static/a.js"\r\n}}'
    index = tmp_path / "index.html"
    index.write_bytes(f'<script type="importmap">{import_map}</script>\r\n'.encode())
    as_parsed = import_map.replace("\r\n", "\n")
    digest = base64.b64encode(hashlib.sha256(as_parsed.encode()).digest()).decode()

    assert f"script-src 'self' 'sha256-{digest}'" in csp_for(index)
