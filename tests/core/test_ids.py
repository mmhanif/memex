import datetime as dt

from memex.core.ids import make_id


def test_title_is_ascii_folded_lowercased_and_hyphenated():
    assert make_id("José's Q3 Plan!", taken=set()) == "joses-q3-plan"


def test_long_title_is_cut_to_60_chars_at_a_word_boundary():
    title = "The quarterly infrastructure modernisation programme for the data platform team"
    assert (
        make_id(title, taken=set())
        == "the-quarterly-infrastructure-modernisation-programme-for-the"
    )


def test_cut_backs_off_to_the_last_hyphen_within_60_chars():
    title = "a" * 55 + " bcdefghij"
    assert make_id(title, taken=set()) == "a" * 55


def test_title_without_ascii_letters_or_digits_becomes_untitled():
    assert make_id("日本語 — !!", taken=set()) == "untitled"


def test_taken_id_gets_the_next_free_numeric_suffix():
    assert make_id("Data migration", taken={"data-migration"}) == "data-migration-2"
    assert (
        make_id("Data migration", taken={"data-migration", "data-migration-2"})
        == "data-migration-3"
    )


def test_taken_check_is_case_insensitive():
    assert make_id("Alice", taken={"Alice"}) == "alice-2"


def test_windows_reserved_name_gets_a_suffix():
    assert make_id("CON", taken=set()) == "con-2"
    assert make_id("lpt9", taken=set()) == "lpt9-2"


def test_dated_id_is_prefixed_with_the_date():
    assert (
        make_id("Send revised deck", taken=set(), date=dt.date(2026, 11, 11))
        == "2026-11-11-send-revised-deck"
    )


def test_dated_id_stays_within_60_chars():
    new_id = make_id("word " * 30, taken=set(), date=dt.date(2026, 11, 11))
    assert new_id.startswith("2026-11-11-word-")
    assert len(new_id) <= 60
    assert not new_id.endswith("-")
