"""SPEC §13.3-§13.5: the real `memex` launcher."""

import secrets
import stat
import sys
from collections.abc import Callable
from dataclasses import replace
from importlib import metadata
from pathlib import Path
from urllib.parse import quote

import pytest

from memex.core.config import load_app_config
from memex.launcher.net import PORT_ATTEMPTS, bind_loopback
from memex.launcher.runfile import RUN_FILE, read_run_file, write_run_file
from tests.launcher.conftest import URL, Memex, make_workspace, request, run_memex

Launch = Callable[..., Memex]


def test_busy_port_starts_on_the_next_and_warns(launch: Launch, ws: Path, free_run: int):
    with bind_loopback(free_run):
        memex = launch("--workspace", str(ws), "--port", str(free_run))

    assert memex.port == free_run + 1
    assert "bookmarks" in memex.output.lower()


def test_second_launch_hands_off_and_its_code_works_once(
    launch: Launch, home: Path, ws: Path, free_run: int
):
    first = launch("--workspace", str(ws), "--port", str(free_run))

    second = run_memex(home, "--no-browser", "--port", str(free_run))

    assert second.returncode == 0, second.stderr
    assert "Memex is already running" in second.stdout
    match = URL.search(second.stdout)
    assert match is not None
    assert int(match.group(1)) == first.port
    code = match.group(2)
    assert request(first.port, "GET", f"/auth?code={code}")[0] == 303
    assert request(first.port, "GET", f"/auth?code={code}")[0] == 401


def test_second_launch_on_another_workspace_refuses(
    launch: Launch, home: Path, ws: Path, tmp_path: Path, free_run: int
):
    launch("--workspace", str(ws), "--port", str(free_run))
    other = make_workspace(tmp_path / "other")

    second = run_memex(home, "--no-browser", "--workspace", str(other), "--port", str(free_run))

    assert second.returncode != 0
    assert f"already running on {ws}" in second.stderr
    assert URL.search(second.stdout + second.stderr) is None
    # The refused Workspace isn't remembered either.
    assert load_app_config(home).workspace == ws


def test_wrong_key_in_run_json_means_a_stranger(
    launch: Launch, home: Path, ws: Path, free_run: int
):
    first = launch("--workspace", str(ws), "--port", str(free_run))
    info = read_run_file(home)
    assert info is not None
    write_run_file(home, replace(info, key=secrets.token_bytes(32)))

    second = launch("--port", str(free_run))

    assert second.port == first.port + 1, second.output
    assert "bookmarks" in second.output.lower()


def test_all_ports_busy_is_a_clear_error(home: Path, ws: Path, free_run: int):
    held = [bind_loopback(p) for p in range(free_run, free_run + PORT_ATTEMPTS)]
    try:
        result = run_memex(home, "--no-browser", "--workspace", str(ws), "--port", str(free_run))
    finally:
        for sock in held:
            sock.close()

    assert result.returncode != 0
    assert f"{free_run}-{free_run + PORT_ATTEMPTS - 1} are all in use" in result.stderr


def test_quit_stops_the_process_and_removes_run_json(
    launch: Launch, home: Path, ws: Path, free_run: int
):
    memex = launch("--workspace", str(ws), "--port", str(free_run))
    assert (home / RUN_FILE).is_file()

    assert memex.quit() == 0
    assert not (home / RUN_FILE).exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_run_json_is_private(launch: Launch, home: Path, ws: Path, free_run: int):
    launch("--workspace", str(ws), "--port", str(free_run))

    assert stat.S_IMODE((home / RUN_FILE).stat().st_mode) == 0o600


def test_log_has_no_note_content_or_secret(launch: Launch, home: Path, ws: Path, free_run: int):
    memex = launch("--workspace", str(ws), "--port", str(free_run))
    body = "Confidential-body-text about the reorg"
    status, created = memex.api(
        "POST", "/api/entities", {"type": "note", "fields": {"title": "Reorg plans"}, "body": body}
    )
    assert status in (200, 201), created
    note = created["id"]
    _, read = memex.api("GET", f"/api/entities/{note}")
    edited = "Confidential-edit-text, second draft"
    put = f"/api/entities/{note}/body"
    status, saved = memex.api("PUT", put, {"body": edited}, {"If-Match": f'"{read["hash"]}"'})
    assert status == 200, saved
    assert memex.api("PUT", put, {"body": edited + " again"})[0] != 200  # no If-Match
    memex.api("GET", "/api/entities/no-such-id")
    memex.api("GET", f"/api/search?q={quote('Confidential')}")
    info = read_run_file(home)
    assert info is not None
    assert memex.cookie is not None
    session = memex.cookie.split("=", 1)[1]
    memex.quit()

    log = (home / "logs" / "memex.log").read_text("utf-8")

    assert "starting on 127.0.0.1" in log  # the file is in use
    for secret in ("Confidential", session, info.key.hex(), memex.code, str(ws)):
        assert secret not in log


def test_version(home: Path):
    result = run_memex(home, "--version")

    assert result.returncode == 0
    assert result.stdout.strip() == f"memex {metadata.version('memex')}"
