"""Bookmarks (SPEC §10.1): parsing `bookmarks.md`, the Bookmarks page, and Add."""

from pathlib import Path

import pytest

from memex.core.bookmarks import Bookmark, add_bookmark, bookmarks_view, parse_bookmarks
from memex.core.errors import Validation
from tests.core.builder import Builder


@pytest.fixture
def b(tmp_path: Path) -> Builder:
    return Builder(tmp_path / "ws")


def test_a_linked_line_gives_title_url_note_and_labels():
    [found] = parse_bookmarks("- [Wiki](https://w.example) team wiki #ref #eng\n")
    assert found == Bookmark(1, "Wiki", "https://w.example", "team wiki", ("ref", "eng"))


def test_a_heading_line_is_not_a_bookmark():
    assert parse_bookmarks("# Work\n\nSome prose\n") == []


def test_a_bare_url_line_is_a_bookmark_with_no_title():
    [found] = parse_bookmarks("- https://x.example handy #tool\n")
    assert found == Bookmark(1, "", "https://x.example", "handy", ("tool",))


def test_the_page_keeps_headings_and_prose_as_text_in_order(b: Builder):
    b.file("bookmarks.md", "# Work\n- [Wiki](https://w.example) #ref\nloose prose\n")
    lines = bookmarks_view(b.ws).lines
    assert [(n.line, n.text, n.bookmark is not None) for n in lines] == [
        (1, "# Work", False),
        (2, "- [Wiki](https://w.example) #ref", True),
        (3, "loose prose", False),
    ]


def test_the_label_filter_keeps_only_bookmarks_with_that_label(b: Builder):
    b.file(
        "bookmarks.md",
        "# Work\n- [Wiki](https://w.example) #Ref\n- [Jira](https://j.example) #eng\n",
    )
    view = bookmarks_view(b.ws, label="ref")
    assert [n.bookmark.title for n in view.lines if n.bookmark] == ["Wiki"]
    assert [n.text for n in view.lines if n.bookmark is None] == []
    assert view.labels == (("eng", 1), ("Ref", 1))


def test_labels_count_their_bookmarks_most_used_first_and_ignore_the_filter(b: Builder):
    b.file(
        "bookmarks.md",
        "- https://a.example #ops #slo\n- https://b.example #Ops\n"
        "- https://c.example #ref\n- https://d.example\nprose #not-a-label\n",
    )
    view = bookmarks_view(b.ws, label="slo")
    assert view.labels == (("ops", 2), ("ref", 1), ("slo", 1))
    assert view.total == 4


def test_a_missing_bookmarks_file_is_an_empty_page(b: Builder):
    (b.root / "bookmarks.md").unlink()
    b.ws.changed("bookmarks.md")
    assert bookmarks_view(b.ws).lines == ()


def test_adding_appends_exactly_one_line_and_keeps_the_rest_byte_for_byte(b: Builder):
    before = b"\xef\xbb\xbf# Work\r\n- [Wiki](https://w.example) #ref\r\n\r\nprose \t\r\n"
    (b.root / "bookmarks.md").write_bytes(before)
    b.ws.changed("bookmarks.md")

    add_bookmark(b.ws, "https://j.example", "Jira", "tickets", ["eng", "#work"])

    after = (b.root / "bookmarks.md").read_bytes()
    assert after == before + b"- [Jira](https://j.example) tickets #eng #work\r\n"


def test_adding_to_a_file_without_a_final_newline_ends_the_last_line_first(b: Builder):
    b.file("bookmarks.md", "- https://a.example")
    add_bookmark(b.ws, "https://b.example")
    assert b.read("bookmarks.md") == "- https://a.example\n- https://b.example\n"


def test_an_added_bookmark_parses_back_to_what_was_added(b: Builder):
    add_bookmark(b.ws, "https://w.example/a?b=1", " Team wiki ", "the  wiki", ["ref"])
    [line] = bookmarks_view(b.ws).lines
    assert line.bookmark == Bookmark(
        1, "Team wiki", "https://w.example/a?b=1", "the wiki", ("ref",)
    )


def test_adding_recreates_a_missing_bookmarks_file(b: Builder):
    (b.root / "bookmarks.md").unlink()
    b.ws.changed("bookmarks.md")
    add_bookmark(b.ws, "https://a.example", "A")
    assert b.read("bookmarks.md") == "- [A](https://a.example)\n"


@pytest.mark.parametrize(
    ("url", "title", "note", "labels", "field"),
    [
        ("", "", "", [], "url"),
        ("javascript:alert(1)", "", "", [], "url"),
        ("https://a.example/x y", "", "", [], "url"),
        ("https://a.example/(x)", "", "", [], "url"),
        ("https://a.example", "a]b", "", [], "title"),
        ("https://a.example", "two\nlines", "", [], "title"),
        ("https://a.example", "", "two\nlines", [], "note"),
        ("https://a.example", "", "see #2", [], "note"),
        ("https://a.example", "", "", ["two words"], "labels"),
        ("https://a.example", "", "", ["a#b"], "labels"),
    ],
)
def test_adding_refuses_what_would_not_parse_back(
    b: Builder, url: str, title: str, note: str, labels: list[str], field: str
):
    with pytest.raises(Validation) as raised:
        add_bookmark(b.ws, url, title, note, labels)
    assert [p.field for p in raised.value.field_errors] == [field]
    assert b.read("bookmarks.md") == ""
