"""Quick-add: parse and create (SPEC §6.3)."""

import datetime as dt
from pathlib import Path

import pytest

from memex.core.errors import MeNotSet, UnknownReference, Validation
from memex.core.quickadd import parse_quick_add, quick_add
from tests.core.builder import Builder


@pytest.fixture
def b(tmp_path: Path) -> Builder:
    b = Builder(tmp_path / "ws")
    b.person("alice-smith", title="Alice Smith")
    b.person("bob-jones", title="Bob Jones")
    return b


def test_owner_requester_and_due_tokens_are_parsed_and_resolved(b: Builder):
    parsed = parse_quick_add(b.ws, "Send deck @ali from @bo due:2026-11-20")
    assert parsed.errors == ()
    assert (parsed.title, parsed.owner, parsed.requester, parsed.due) == (
        "Send deck",
        "alice-smith",
        "bob-jones",
        dt.date(2026, 11, 20),
    )


def test_without_tokens_owner_and_requester_are_me(b: Builder):
    parsed = parse_quick_add(b.ws, "Call   vendor ")
    assert (parsed.title, parsed.owner, parsed.requester, parsed.due) == (
        "Call vendor",
        "ada",
        "ada",
        None,
    )


def test_an_unmatched_owner_is_an_error_and_nothing_is_created(b: Builder):
    parsed = parse_quick_add(b.ws, "@zz review")
    [error] = parsed.errors
    assert (error.field, error.token) == ("owner", "@zz")
    with pytest.raises(UnknownReference):
        quick_add(b.ws, "@zz review")
    assert list((b.root / "todos").iterdir()) == []


def test_an_owner_matching_two_persons_equally_lists_both(b: Builder):
    b.person("alan-po", title="Alan Po")
    [error] = parse_quick_add(b.ws, "Review @al").errors
    assert error.token == "@al"
    assert error.candidates == ("alan-po", "alice-smith")


def test_an_exact_id_beats_a_prefix_and_archived_persons_never_match(b: Builder):
    b.person("al", title="Al")
    b.person("alfred", title="Alfred", archived=dt.date(2026, 1, 1))
    assert parse_quick_add(b.ws, "x @al").owner == "al"
    assert parse_quick_add(b.ws, "x @alf").errors[0].message == "No Person matches @alf"


def test_names_match_ignoring_case_and_accents_and_fuzzily(b: Builder):
    b.person("jose-nunez", title="José Núñez")
    assert parse_quick_add(b.ws, "x @JOSE").owner == "jose-nunez"
    assert parse_quick_add(b.ws, "x @nunez").owner == "jose-nunez"
    assert parse_quick_add(b.ws, "x @bjns").owner == "bob-jones"


def test_tokens_may_come_in_any_order(b: Builder):
    parsed = parse_quick_add(b.ws, "due:2026-12-01 from @alice Send @bob deck")
    assert (parsed.title, parsed.owner, parsed.requester) == (
        "Send deck",
        "bob-jones",
        "alice-smith",
    )


@pytest.mark.parametrize(
    ("text", "token"),
    [
        ("x @alice @bob", "@bob"),
        ("x from @alice from @bob", "from @bob"),
        ("x due:2026-12-01 due:2026-12-02", "due:2026-12-02"),
        ("x due:2026-02-30", "due:2026-02-30"),
        ("x due:tomorrow", "due:tomorrow"),
    ],
)
def test_repeated_tokens_and_bad_dates_are_errors(b: Builder, text: str, token: str):
    assert [e.token for e in parse_quick_add(b.ws, text).errors] == [token]


def test_an_empty_title_is_an_error(b: Builder):
    [error] = parse_quick_add(b.ws, "@alice due:2026-12-01").errors
    assert error.token is None
    assert "title" in error.message


def test_context_defaults_apply_unless_a_token_overrides_them(b: Builder):
    waiting_on_alice = {"owner": "alice-smith", "requester": "ada"}
    parsed = parse_quick_add(b.ws, "Draft plan", waiting_on_alice)
    assert (parsed.owner, parsed.requester) == ("alice-smith", "ada")
    parsed = parse_quick_add(b.ws, "Draft plan @bob", waiting_on_alice)
    assert (parsed.owner, parsed.requester) == ("bob-jones", "ada")


def test_quick_add_creates_a_dated_todo_file(b: Builder):
    saved = quick_add(b.ws, "Send revised deck @alice due:2026-11-20")
    assert saved.rel == "todos/2026-11-12-send-revised-deck.md"
    text = b.read(saved.rel)
    for line in (
        "title: Send revised deck",
        "owner: alice-smith",
        "requester: ada",
        "status: open",
        "due: 2026-11-20",
        "created: 2026-11-12",
    ):
        assert line in text


def test_a_bad_date_is_refused_with_validation(b: Builder):
    with pytest.raises(Validation):
        quick_add(b.ws, "x due:2026-02-30")


def test_quick_add_without_an_owner_fails_when_me_is_not_set(b: Builder):
    b.file(".memex/config.yaml", "format: 1\nme: ghost\n")
    assert parse_quick_add(b.ws, "Call vendor").owner is None
    with pytest.raises(MeNotSet):
        quick_add(b.ws, "Call vendor")
