"""Smoke-test an installed `memex` (SPEC §16.9 package job). Dev only; stdlib only.

Starts it against a fresh temp home with no Workspace (so it serves Setup), signs in
with the printed code, fetches `/` and one vendored file, then quits it.

    python scripts/smoke.py PATH/TO/memex[.exe]
"""

import http.client
import os
import re
import subprocess
import sys
import tempfile
import threading

URL = re.compile(r"http://127\.0\.0\.1:(\d+)/auth\?code=(\S+)")
VENDORED = "/static/vendor/preact/dist/preact.mjs"


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: smoke.py MEMEX", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as home:
        env = {**os.environ, "MEMEX_HOME": home, "PYTHONUNBUFFERED": "1"}
        proc = subprocess.Popen(
            [argv[0], "--no-browser", "--port", "27615"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
        )
        try:
            port, code = _wait_for_url(proc)
            cookie = _sign_in(port, code)
            for path in ("/", VENDORED):
                status, _ = _get(port, path, cookie)
                print(f"GET {path}: {status}")
                if status != 200:
                    return 1
            _post(port, "/api/quit", cookie)
            returncode = proc.wait(30)
            print(f"memex exited {returncode}")
            return returncode
        finally:
            if proc.poll() is None:
                proc.kill()


def _wait_for_url(proc: subprocess.Popen[str]) -> tuple[int, str]:
    found: list[tuple[int, str]] = []
    ready = threading.Event()

    def read() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="")
            if not found and (match := URL.search(line)):
                found.append((int(match.group(1)), match.group(2)))
                ready.set()
        ready.set()

    threading.Thread(target=read, daemon=True).start()
    if not ready.wait(60) or not found:
        raise SystemExit("memex didn't print its URL")
    return found[0]


def _sign_in(port: int, code: str) -> str:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", f"/auth?code={code}")
    response = conn.getresponse()
    response.read()
    if response.status != 303:
        raise SystemExit(f"/auth: {response.status}")
    return (response.getheader("set-cookie") or "").split(";", 1)[0]


def _get(port: int, path: str, cookie: str) -> tuple[int, bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", path, headers={"Cookie": cookie})
    response = conn.getresponse()
    return response.status, response.read()


def _post(port: int, path: str, cookie: str) -> None:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {
        "Cookie": cookie,
        "X-Memex": "1",
        "Origin": f"http://127.0.0.1:{port}",
        "Content-Type": "application/json",
    }
    conn.request("POST", path, body="{}", headers=headers)
    conn.getresponse().read()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
