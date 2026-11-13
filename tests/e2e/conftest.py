"""Playwright journeys against a real server and a temp Workspace (SPEC §16.7)."""

import datetime as dt
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import Page, Request
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from memex.core.clock import FixedClock
from memex.core.workspace import NewMe, apply_setup
from memex.web.app import AppState
from tests.live import live_server

TODAY = dt.date(2026, 11, 12)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "tests/e2e/" in item.nodeid:
            item.add_marker(pytest.mark.e2e)


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("MEMEX_HOME", str(tmp_path / "home"))
    root = tmp_path / "ws"
    root.mkdir()
    apply_setup(root, NewMe("Ada Lovelace"), clock=FixedClock(TODAY), install_dir=tmp_path / "i")
    return root


@pytest.fixture
def server(root: Path, tmp_path: Path) -> Iterator[AppState]:
    def make(port: int) -> AppState:
        return AppState.for_workspace(
            root,
            port=port,
            home=tmp_path / "home",
            clock=FixedClock(TODAY),
            install_dir=tmp_path / "i",
        )

    with live_server(make) as state:
        yield state


def origin(state: AppState) -> str:
    return f"http://127.0.0.1:{state.port}"


class Requests:
    """What the page asked for, and which of those the CSP stopped before the network."""

    def __init__(self, page: Page) -> None:
        self.urls: list[str] = []
        self.blocked_by_csp: list[str] = []
        page.on("request", lambda r: self.urls.append(r.url))
        page.on("requestfailed", self._failed)

    def _failed(self, request: Request) -> None:
        if request.failure == "csp":
            self.blocked_by_csp.append(request.url)

    def outbound(self) -> list[str]:
        """Requests that left for anywhere but 127.0.0.1."""
        return [
            u
            for u in self.urls
            if urlsplit(u).hostname != "127.0.0.1" and u not in self.blocked_by_csp
        ]


@pytest.fixture
def requests_made(page: Page) -> Requests:
    return Requests(page)


@pytest.fixture(autouse=True)
def air_gap(requests_made: Requests) -> Iterator[None]:
    """Every request the page makes goes to 127.0.0.1 (§16.5; also covers R19)."""
    yield
    assert requests_made.outbound() == []


@pytest.fixture
def app(page: Page, server: AppState) -> Page:
    """The SPA, signed in with a fresh launch code (R6)."""
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{origin(server)}/auth?code={server.session.issue_code()}")
    try:
        page.wait_for_selector(".shell", timeout=10_000)
    except PlaywrightTimeout:
        pytest.fail(f"the app didn't start; browser errors: {errors}")
    return page
