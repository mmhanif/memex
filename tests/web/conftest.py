import datetime as dt
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from memex.core.clock import FixedClock
from memex.core.workspace import NewMe, apply_setup
from memex.web.app import AppState, create_app
from memex.web.session import COOKIE

PORT = 47615
ORIGIN = f"http://127.0.0.1:{PORT}"
TODAY = dt.date(2026, 11, 12)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    monkeypatch.setenv("MEMEX_HOME", str(home))
    return home


@pytest.fixture
def root(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    apply_setup(root, NewMe("Ada Lovelace"), clock=FixedClock(TODAY), install_dir=tmp_path / "i")
    return root


@pytest.fixture
def state(root: Path, home: Path, tmp_path: Path) -> AppState:
    return AppState.for_workspace(
        root, port=PORT, home=home, clock=FixedClock(TODAY), install_dir=tmp_path / "i"
    )


@pytest.fixture
def anon(state: AppState) -> Iterator[TestClient]:
    """A client on the right host with no cookie and no Memex headers."""
    with TestClient(create_app(state), base_url=ORIGIN, follow_redirects=False) as client:
        yield client


@pytest.fixture
def browser(state: AppState) -> Iterator[TestClient]:
    """A client with the session cookie, as the SPA's page loads would be."""
    with TestClient(create_app(state), base_url=ORIGIN, follow_redirects=False) as client:
        client.cookies.set(COOKIE, state.session.secret)
        yield client


@pytest.fixture
def api(state: AppState) -> Iterator[TestClient]:
    with client_for(state) as client:
        yield client


def client_for(state: AppState) -> TestClient:
    """The SPA's `fetch`: cookie, `X-Memex: 1`, and a same-origin `Origin`."""
    client = TestClient(
        create_app(state),
        base_url=ORIGIN,
        follow_redirects=False,
        headers={"X-Memex": "1", "Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"},
    )
    client.cookies.set(COOKIE, state.session.secret)
    return client
