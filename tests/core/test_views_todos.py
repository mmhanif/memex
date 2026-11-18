"""To-do views: Mine, Waiting on them, Waiting on me (SPEC §6.2)."""

import datetime as dt
from pathlib import Path

import pytest

from memex.core.errors import MeNotSet, Validation
from memex.core.views import open_todo_count, todo_view
from tests.core.builder import Builder

# The Builder's today is Thursday 2026-11-12, so "this week" runs through Sunday 11-15.


@pytest.fixture
def b(tmp_path: Path) -> Builder:
    b = Builder(tmp_path / "ws")
    b.person("alice")
    b.person("bob")
    return b


def groups(view) -> dict[str, list[str]]:
    return {g.label: [t.id for t in g.todos] for g in view.groups}


def test_mine_groups_by_due_date(b: Builder):
    b.todo("overdue", owner="ada", due=dt.date(2026, 11, 11))
    b.todo("today", owner="ada", due=dt.date(2026, 11, 12))
    b.todo("sunday", owner="ada", due=dt.date(2026, 11, 15))
    b.todo("next-month", owner="ada", due=dt.date(2026, 12, 10))
    b.todo("monday", owner="ada", due=dt.date(2026, 11, 16))
    b.todo("undated", owner="ada")
    assert groups(todo_view(b.ws, "mine")) == {
        "Overdue": ["overdue"],
        "This week": ["today", "sunday"],
        "Later": ["monday", "next-month"],
        "No date": ["undated"],
    }


def test_waiting_on_them_is_grouped_by_owner(b: Builder):
    b.todo("b2", owner="bob", due=dt.date(2026, 11, 20))
    b.todo("a1", owner="alice")
    b.todo("b1", owner="bob", due=dt.date(2026, 11, 13))
    view = todo_view(b.ws, "waiting-on-them")
    assert [(g.label, g.person, [t.id for t in g.todos]) for g in view.groups] == [
        ("Alice", "alice", ["a1"]),
        ("Bob", "bob", ["b1", "b2"]),
    ]


def test_waiting_on_me_is_grouped_by_requester(b: Builder):
    b.todo("for-alice", owner="ada", requester="alice")
    b.todo("for-bob", owner="ada", requester="bob")
    assert groups(todo_view(b.ws, "waiting-on-me")) == {"Alice": ["for-alice"], "Bob": ["for-bob"]}


def test_who_appears_where(b: Builder):
    b.todo("me-both", owner="ada", requester="ada")
    b.todo("alice-for-bob", owner="alice", requester="bob")
    b.todo("upper-case-me", owner="Ada", requester="alice")
    assert groups(todo_view(b.ws, "mine")) == {"No date": ["me-both", "upper-case-me"]}
    assert groups(todo_view(b.ws, "waiting-on-them")) == {}
    assert groups(todo_view(b.ws, "waiting-on-me")) == {"Alice": ["upper-case-me"]}


def test_finished_todos_show_only_with_show_completed(b: Builder):
    b.todo("open", owner="ada")
    b.todo("done", owner="ada", status="done", completed=dt.date(2026, 11, 10))
    b.todo("cancelled", owner="ada", status="cancelled", completed=dt.date(2026, 11, 11))
    b.todo("bad-status", owner="ada", status="wip")
    assert groups(todo_view(b.ws, "mine")) == {"No date": ["bad-status", "open"]}
    assert groups(todo_view(b.ws, "mine", include_done=True)) == {
        "No date": ["bad-status", "open"],
        "Completed": ["cancelled", "done"],
    }


def test_views_need_me_and_a_known_view_name(b: Builder):
    with pytest.raises(Validation):
        todo_view(b.ws, "everything")
    b.file(".memex/config.yaml", "format: 1\n")
    with pytest.raises(MeNotSet):
        todo_view(b.ws, "mine")


def test_groups_merge_ids_written_in_different_case(b: Builder):
    b.todo("one", owner="alice")
    b.todo("two", owner="Alice")
    assert groups(todo_view(b.ws, "waiting-on-them")) == {"Alice": ["one", "two"]}


def test_open_todo_count_is_mes_open_todos_for_the_sidebar_badge(b: Builder):
    b.todo("mine", owner="ada", requester="alice")
    b.todo("Mine-too", owner="Ada")
    b.todo("bad-status", owner="ada", status="wip")
    b.todo("done", owner="ada", status="done")
    b.todo("cancelled", owner="ada", status="cancelled")
    b.todo("alices", owner="alice")
    assert open_todo_count(b.ws) == 3
    b.file(".memex/config.yaml", "format: 1\n")
    assert open_todo_count(b.ws) is None
