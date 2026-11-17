"""Real `memex` processes against a temp home and Workspace (SPEC §13, §16.2 launcher layer)."""

import http.client
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from memex.core.clock import FixedClock
from memex.core.workspace import NewMe, apply_setup
from memex.launcher.net import PORT_ATTEMPTS, bind_loopback
from tests.web.conftest import TODAY

URL = re.compile(r"http://127\.0\.0\.1:(\d+)/auth\?code=(\S+)")


@pytest.fixture
def free_run() -> Iterator[int]:
    """A starting port with the next PORT_ATTEMPTS ports free (best effort).

    Drawn from below every OS's ephemeral range, like the default 47615: a port there can be
    taken by any outgoing connection, the launcher's own hand-off check included.
    """
    for _ in range(50):
        start = random.randrange(20000, 32000)
        try:
            held = [bind_loopback(p) for p in range(start, start + PORT_ATTEMPTS)]
        except OSError:
            continue
        for s in held:
            s.close()
        yield start
        return
    pytest.skip("no run of free ports")


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path / "home"


def make_workspace(path: Path) -> Path:
    path.mkdir()
    apply_setup(
        path, NewMe("Ada Lovelace"), clock=FixedClock(TODAY), install_dir=path.parent / "install"
    )
    return path


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    return make_workspace(tmp_path / "ws")


def memex_cmd(*args: str) -> list[str]:
    return [sys.executable, "-m", "memex", *args]


def memex_env(home: Path) -> dict[str, str]:
    return {**os.environ, "MEMEX_HOME": str(home), "PYTHONUNBUFFERED": "1"}


def run_memex(home: Path, *args: str, timeout: float = 30) -> subprocess.CompletedProcess[str]:
    """Run a `memex` that's expected to exit by itself."""
    return subprocess.run(
        memex_cmd(*args),
        env=memex_env(home),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )


class Memex:
    """A running `memex --no-browser`: its port, its printed code, and its output so far."""

    def __init__(self, home: Path, *args: str) -> None:
        self.home = home
        self.proc = subprocess.Popen(
            memex_cmd("--no-browser", *args),
            env=memex_env(home),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
        )
        self.lines: list[str] = []
        self._started = threading.Event()
        threading.Thread(target=self._read, daemon=True).start()
        if not self._started.wait(30):
            self.proc.kill()
            raise AssertionError("memex didn't print its URL:\n" + self.output)
        match = next((m for line in self.lines if (m := URL.search(line))), None)
        if match is None:
            raise AssertionError("memex exited without a URL:\n" + self.output)
        self.port, self.code = int(match.group(1)), match.group(2)
        self.cookie: str | None = None

    def _read(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self.lines.append(line)
            if URL.search(line):
                self._started.set()
        self._started.set()  # exited without a URL: fail now, not at the timeout

    @property
    def output(self) -> str:
        return "".join(self.lines)

    def login(self) -> None:
        status, headers, _ = request(self.port, "GET", f"/auth?code={self.code}")
        assert status == 303, status
        self.cookie = headers["set-cookie"].split(";", 1)[0]

    def api(
        self, method: str, path: str, body: object = None, headers: dict[str, str] | None = None
    ) -> tuple[int, dict]:
        if self.cookie is None:
            self.login()
        assert self.cookie is not None
        all_headers = {"Cookie": self.cookie, "X-Memex": "1", **(headers or {})}
        status, _, data = request(self.port, method, path, body, all_headers)
        return status, json.loads(data) if data else {}

    def quit(self, timeout: float = 20) -> int:
        self.api("POST", "/api/quit", {})
        return self.proc.wait(timeout)

    def stop(self) -> None:
        if self.proc.poll() is None:
            try:
                self.quit()
            except Exception:
                self.proc.kill()
                self.proc.wait(10)


def request(
    port: int,
    method: str,
    path: str,
    body: object = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        all_headers = {"Origin": f"http://127.0.0.1:{port}", **(headers or {})}
        payload = None
        if body is not None:
            payload = json.dumps(body).encode()
            all_headers["Content-Type"] = "application/json"
        conn.request(method, path, payload, all_headers)
        response = conn.getresponse()
        return (
            response.status,
            {k.lower(): v for k, v in response.getheaders()},
            response.read(),
        )
    finally:
        conn.close()


@pytest.fixture
def launch(home: Path) -> Iterator[Callable[..., Memex]]:
    """Start `memex` processes; each is quit (or killed) at the end of the test."""
    started: list[Memex] = []

    def start(*args: str) -> Memex:
        memex = Memex(home, *args)
        started.append(memex)
        return memex

    yield start
    for memex in started:
        memex.stop()


def wait_for(predicate, timeout: float = 10) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()
