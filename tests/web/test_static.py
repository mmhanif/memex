"""The vendored front end (SPEC §11.1, §13.6): every pinned file is present, and the
import map only points at files that ship."""

import json
import re
import tomllib

import pytest
from fastapi.testclient import TestClient

from memex.web.state import STATIC

VENDOR = STATIC / "vendor"


def manifest_files() -> set[str]:
    manifest = tomllib.loads((VENDOR / "VERSIONS").read_text("utf-8"))
    return {f"{name}/{rel}" for name, pkg in manifest["packages"].items() for rel in pkg["files"]}


def test_every_file_listed_in_versions_is_vendored():
    missing = sorted(f for f in manifest_files() if not (VENDOR / f).is_file())

    assert missing == []


def test_the_import_map_points_only_at_vendored_files():
    index = (STATIC / "index.html").read_text("utf-8")
    match = re.search(r'<script type="importmap">(.*?)</script>', index, re.DOTALL)
    assert match is not None
    targets = json.loads(match.group(1))["imports"].values()

    assert {t.removeprefix("/static/vendor/") for t in targets} <= manifest_files()


def test_every_icon_the_css_uses_is_vendored():
    css = (STATIC / "css/app.css").read_text("utf-8")
    used = set(re.findall(r'url\("/static/vendor/([^"]+)"\)', css))

    assert used
    assert used <= manifest_files()


def test_static_files_are_served_with_types_chrome_accepts(
    page_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    # Python's mimetypes reads the Windows registry, which can map .js to text/plain;
    # Chrome then refuses the module (nosniff), and the app never starts. Act like that.
    monkeypatch.setattr("starlette.responses.guess_type", lambda *a, **k: ("text/plain", None))
    expected = {
        "/": "text/html",
        "/relaunch": "text/html",
        "/static/app/main.js": "text/javascript",
        "/static/vendor/preact/dist/preact.mjs": "text/javascript",
        "/static/css/app.css": "text/css",
        "/static/vendor/lucide-static/icons/house.svg": "image/svg+xml",
    }

    served = {
        path: page_client.get(path).headers["content-type"].split(";")[0] for path in expected
    }

    assert served == expected
