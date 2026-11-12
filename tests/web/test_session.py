import hmac

import pytest

from memex.web.session import Session


def test_R07_secret_has_256_bits():
    assert len(bytes.fromhex(Session().secret)) == 32
    assert Session().secret != Session().secret


def test_R06_a_code_redeems_once():
    session = Session()
    code = session.issue_code()

    assert session.redeem(code) is True
    assert session.redeem(code) is False


def test_R06_a_wrong_code_does_not_redeem():
    session = Session()
    session.issue_code()

    assert session.redeem("wrong") is False


def test_R06_codes_and_cookies_compare_in_constant_time(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, str]] = []

    def spy(a, b):
        calls.append((a, b))
        return hmac.compare_digest(a, b)

    monkeypatch.setattr("memex.web.session.compare_digest", spy)
    session = Session()
    code = session.issue_code()

    session.redeem(code)
    session.is_valid_cookie(session.secret)

    assert (code, code) in calls
    assert (session.secret, session.secret) in calls


def test_cookie_check_accepts_only_the_secret():
    session = Session()

    assert session.is_valid_cookie(session.secret)
    assert not session.is_valid_cookie(None)
    assert not session.is_valid_cookie(Session().secret)


def test_non_ascii_codes_and_cookies_are_refused_not_crashed():
    session = Session()
    session.issue_code()

    assert session.redeem("ü") is False
    assert not session.is_valid_cookie("ü")
