"""SPEC §9: one search engine over the parse cache."""

import datetime as dt
from pathlib import Path

import pytest

from memex.core.cache import CachedFile
from memex.core.search import context_of, search
from tests.core.builder import Builder


@pytest.fixture
def b(tmp_path: Path) -> Builder:
    return Builder(tmp_path / "ws")


def cached(b: Builder, rel: str) -> CachedFile:
    found = b.ws.cache.get(rel)
    assert found is not None
    return found


def ids(b: Builder, query: str, **options) -> list[str]:
    return [h.id for h in search(b.ws, query, **options).hits]


def test_a_fuzzy_name_match_ranks_above_a_body_only_match(b: Builder):
    b.note("notes/standup.md", "We said dmig a lot.\n")
    b.project("data-migration", title="Data migration")
    result = search(b.ws, "dmig")
    assert [(h.id, h.tier) for h in result.hits] == [("data-migration", 3), ("standup", 6)]


def test_a_done_exact_match_is_still_returned_below_an_active_one(b: Builder):
    b.project("roadmap", title="Roadmap", status="done")
    b.deliverable("roadmap-2", project="roadmap", title="Roadmap", status="active")
    result = search(b.ws, "roadmap")
    assert [(h.id, h.tier) for h in result.hits] == [("roadmap-2", 1), ("roadmap", 1)]


def test_a_quoted_phrase_matches_exactly_and_words_match_by_prefix(b: Builder):
    b.note("notes/a.md", "The revised deck is out.\n")
    b.note("notes/b.md", "We revised the deck.\n")
    b.note("notes/c.md", "Unrevised decks.\n")
    assert ids(b, '"revised deck"') == ["a"]
    assert sorted(ids(b, "revis dec")) == ["a", "b"]


def test_accents_and_case_are_ignored(b: Builder):
    b.person("jose", title="José Álvarez")
    assert ids(b, "jose") == ["jose"]
    assert ids(b, "ALVA") == ["jose"]


def test_a_glossary_alias_is_found(b: Builder):
    b.entity("glossary", "uptime-target", aliases=["SLO"])
    result = search(b.ws, "slo")
    assert [(h.id, h.tier) for h in result.hits] == [("uptime-target", 4)]


def test_labels_and_person_fields_rank_above_the_body(b: Builder):
    b.person("bea", title="Bea", organisation="Contoso")
    b.note("notes/n.md", "Met Contoso people.\n")
    assert [(h.id, h.tier) for h in search(b.ws, "contos").hits] == [("bea", 5), ("n", 6)]


def test_a_body_hit_carries_a_snippet_with_the_match_marked(b: Builder):
    b.note("notes/n.md", "# Title\n\nWe talked about the Café budget.\n")
    [hit] = search(b.ws, "cafe").hits
    [snippet] = hit.snippets
    assert snippet.text == "We talked about the Café budget."
    start, end = snippet.highlights[0]
    assert snippet.text[start:end] == "Café"


def test_type_status_and_person_filters_combine(b: Builder):
    b.person("alice")
    b.project("a", status="active", lead="alice")
    b.project("b", status="blocked", team=["alice"])
    b.project("c", status="done", lead="alice")
    b.project("d", status="active", body="Ask [[alice]].\n")
    b.deliverable("e", project="a", status="active", lead="alice")
    b.todo("2026-11-01-call", owner="alice")
    result = search(b.ws, "type:project status:active,blocked @alice")
    assert sorted(h.id for h in result.hits) == ["a", "b"]
    assert result.errors == ()
    assert [(f.kind, f.values) for f in result.filters] == [
        ("type", ("project",)),
        ("status", ("active", "blocked")),
        ("person", ("alice",)),
    ]


def test_due_this_week_runs_through_sunday(tmp_path: Path):
    wednesday = Builder(tmp_path / "ws", today=dt.date(2026, 11, 11))
    wednesday.project("sunday", due=dt.date(2026, 11, 15))
    wednesday.project("monday", due=dt.date(2026, 11, 16))
    wednesday.project("undated")
    assert ids(wednesday, "due:this-week") == ["sunday"]
    assert ids(wednesday, "type:project due:none") == ["undated"]
    assert ids(wednesday, "due>2026-11-15") == ["monday"]
    assert ids(wednesday, "due<2026-11-16") == ["sunday"]


def test_an_unknown_person_is_a_token_error_not_unfiltered_results(b: Builder):
    b.project("a")
    result = search(b.ws, "@nobody")
    assert result.hits == ()
    assert [(e.token, e.message) for e in result.errors] == [
        ("@nobody", "No Person matches @nobody")
    ]


def test_bad_filter_values_are_token_errors(b: Builder):
    result = search(b.ws, "type:widget status:busy due:soon due<2026-13-01")
    assert [e.token for e in result.errors] == [
        "type:widget",
        "status:busy",
        "due:soon",
        "due<2026-13-01",
    ]


def test_label_filter_and_text_together(b: Builder):
    b.project("plan-a", labels=["q4"])
    b.project("plan-b")
    assert ids(b, "plan label:Q4") == ["plan-a"]


def test_hide_completed_is_overridden_by_an_explicit_status(b: Builder):
    b.project("plan-a")
    b.project("plan-b", status="done")
    assert ids(b, "plan", hide_completed=True) == ["plan-a"]
    assert ids(b, "plan status:done", hide_completed=True) == ["plan-b"]


def test_archived_items_rank_with_done_work_and_can_be_left_out(b: Builder):
    b.person("alice-old", title="Alice Old", archived=dt.date(2026, 1, 1))
    b.person("alice-new", title="Alice New")
    assert ids(b, "alice") == ["alice-new", "alice-old"]
    assert ids(b, "alice", include_archived=False) == ["alice-new"]


def test_counts_by_type_cover_every_hit_not_just_the_page(b: Builder):
    for n in range(3):
        b.project(f"plan-{n}")
    b.note("notes/plan.md", "x\n")
    result = search(b.ws, "plan", limit=1)
    assert len(result.hits) == 1
    assert result.total == 4
    assert result.counts == {"project": 3, "note": 1}


BOOKMARKS = """# Links

- [Wiki](https://w.example) team wiki #ref #eng
- [Wiki search tips](https://w.example/tips) #ref
- https://bare.example/wiki
Some prose about the wiki.
"""


def test_each_bookmark_line_is_its_own_result(b: Builder):
    b.file("bookmarks.md", BOOKMARKS)
    result = search(b.ws, "wiki")
    assert [(h.type, h.bookmark and h.bookmark.line) for h in result.hits] == [
        ("bookmark", 3),
        ("bookmark", 4),
        ("bookmark", 5),
    ]
    first = result.hits[0]
    assert first.bookmark is not None
    assert (first.bookmark.title, first.tier) == ("Wiki", 6)

    def lines(query: str) -> list[int | None]:
        return [h.bookmark and h.bookmark.line for h in search(b.ws, query).hits]

    assert lines("label:eng") == [3]
    assert lines("type:bookmark tips") == [4]


def test_context_lines_name_the_theme_project_parties_or_folder_with_me_as_me(b: Builder):
    b.person("alice", title="Alice")
    b.theme("platform", title="Platform")
    b.project("data-migration", title="Data migration", theme="platform")
    b.deliverable("cutover", project="data-migration")
    b.todo("2026-11-01-call", owner="alice")
    b.note("notes/1on1/2026-11-01.md", "x\n")
    assert context_of(b.ws, cached(b, "projects/data-migration.md")) == "Platform"
    assert context_of(b.ws, cached(b, "deliverables/cutover.md")) == "Data migration"
    assert context_of(b.ws, cached(b, "todos/2026-11-01-call.md")) == "Alice → Me"
    assert context_of(b.ws, cached(b, "notes/1on1/2026-11-01.md")) == "notes/1on1"
    assert context_of(b.ws, cached(b, "themes/platform.md")) == ""


def test_search_follows_edits_and_deletes(b: Builder):
    b.note("notes/a.md", "alpha words\n")
    b.note("notes/b.md", "beta words\n")
    assert sorted(ids(b, "words")) == ["a", "b"]

    b.note("notes/a.md", "gamma now\n")
    (b.root / "notes/b.md").unlink()
    b.ws.changed("notes/b.md")
    b.note("notes/c.md", "delta\n")  # may take b's place in the index

    assert ids(b, "words") == []
    assert ids(b, "alpha") == []
    assert ids(b, "gamma") == ["a"]
    assert ids(b, "beta") == []
    assert ids(b, "delta") == ["c"]


def test_punctuated_terms_match_as_written(b: Builder):
    b.project("q3-plan", title="Q3 plan")
    b.note("notes/n.md", "Ask o'neil about the q3-plan.\n")
    b.note("notes/m.md", "q3 is busy; plan later.\n")
    assert sorted(ids(b, "q3-pl")) == ["n", "q3-plan"]
    assert ids(b, "o'nei") == ["n"]


def test_types_narrow_like_a_type_filter(b: Builder):
    b.project("plan-a")
    b.note("notes/plan.md", "x\n")
    b.file("bookmarks.md", "- [Plan wiki](https://p.example)\n")
    assert sorted(h.type for h in search(b.ws, "plan", types=["note", "bookmark"]).hits) == [
        "bookmark",
        "note",
    ]
