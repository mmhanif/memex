"""SPEC §13.4: the server side of the already-running hand-off."""

import hashlib
import hmac
import secrets

import pytest
from fastapi.testclient import TestClient

from memex.web.app import AppState
from tests.web.conftest import PORT


def mac(key: bytes, label: bytes, nonce: str) -> str:
    return hmac.new(key, label + bytes.fromhex(nonce), hashlib.sha256).hexdigest()


def test_hello_proves_the_key_and_names_the_workspace(anon: TestClient, state: AppState):
    nonce = secrets.token_hex(32)

    response = anon.post("/launcher/hello", json={"nonce": nonce})

    assert response.status_code == 200
    assert state.workspace is not None
    assert response.json() == {
        "mac": mac(state.launcher_key, b"server", nonce),
        "workspace": str(state.workspace.root),
    }


def test_open_with_a_valid_mac_issues_a_working_code(anon: TestClient, state: AppState):
    nonce = secrets.token_hex(32)

    response = anon.post(
        "/launcher/open", json={"nonce": nonce, "mac": mac(state.launcher_key, b"open", nonce)}
    )

    assert response.status_code == 200
    code = response.json()["code"]
    assert anon.get(f"/auth?code={code}").status_code == 303


def test_open_with_a_bad_mac_is_401(anon: TestClient, state: AppState):
    nonce = secrets.token_hex(32)

    responses = [
        anon.post("/launcher/open", json={"nonce": nonce, "mac": "00" * 32}),
        # The server's own hello MAC must not be usable to open.
        anon.post(
            "/launcher/open",
            json={"nonce": nonce, "mac": mac(state.launcher_key, b"server", nonce)},
        ),
        anon.post("/launcher/open", json={"nonce": nonce, "mac": mac(b"k" * 32, b"open", nonce)}),
    ]

    assert [r.status_code for r in responses] == [401, 401, 401]
    assert all("code" not in r.json() for r in responses)


def test_open_mac_cannot_be_replayed(anon: TestClient, state: AppState):
    nonce = secrets.token_hex(32)
    body = {"nonce": nonce, "mac": mac(state.launcher_key, b"open", nonce)}

    first = anon.post("/launcher/open", json=body)
    second = anon.post("/launcher/open", json=body)

    assert first.status_code == 200
    assert second.status_code == 401


@pytest.mark.parametrize("nonce", ["", "zz", "ab" * 8, "ab" * 300])
def test_bad_nonces_are_422(anon: TestClient, nonce: str):
    response = anon.post("/launcher/hello", json={"nonce": nonce})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation"


def test_launcher_routes_still_need_the_right_host(anon: TestClient):
    response = anon.post(
        "/launcher/hello", json={"nonce": "ab" * 32}, headers={"Host": f"evil.example:{PORT}"}
    )

    assert response.status_code == 421


def test_launcher_routes_need_json(anon: TestClient):
    response = anon.post(
        "/launcher/hello", content=b"nonce=ab", headers={"Content-Type": "text/plain"}
    )

    assert response.status_code == 415


def test_odd_length_nonce_is_422_not_500(anon: TestClient):
    response = anon.post("/launcher/hello", json={"nonce": "a" * 33})

    assert response.status_code == 422


def test_R07_launcher_key_and_secret_are_not_in_the_state_repr(state: AppState):
    text = repr(state)

    assert state.launcher_key.hex() not in text
    assert repr(state.launcher_key) not in text
    assert state.session.secret not in text
