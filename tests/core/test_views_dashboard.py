"""The Dashboard (SPEC §11.4)."""

import datetime as dt
import os
from pathlib import Path

import pytest

from memex.core.views import dashboard
from tests.core.builder import Builder

# The Builder's today is 2026-11-12, so "within 7 days" is through 2026-11-19.


@pytest.fixture
def b(tmp_path: Path) -> Builder:
    b = Builder(tmp_path / "ws")
    b.person("alice", manager="ada")
    b.person("bob")
    return b


def test_due_within_7_days_has_work_and_my_todos_overdue_first(b: Builder):
    b.project("late", due=dt.date(2026, 11, 1))
    b.deliverable("soon", project="late", due=dt.date(2026, 11, 19))
    b.project("next-month", due=dt.date(2026, 12, 19))
    b.project("finished", status="done", due=dt.date(2026, 11, 13))
    b.project("dropped", status="cancelled", due=dt.date(2026, 11, 13))
    b.todo("mine", owner="ada", requester="bob", due=dt.date(2026, 11, 14))
    b.todo("mine-done", owner="ada", status="done", due=dt.date(2026, 11, 14))
    b.todo("theirs", owner="alice", due=dt.date(2026, 11, 14))
    view = dashboard(b.ws)
    assert [f.id for f in view.due_soon] == ["late", "mine", "soon"]


def test_waiting_cards_blocked_work_and_directs(b: Builder):
    b.todo("on-alice", owner="alice")
    b.todo("on-alice-done", owner="alice", status="done")
    b.todo("on-bob", owner="bob")
    b.todo("alice-waits", owner="ada", requester="alice")
    b.project("stuck", status="blocked")
    b.deliverable("stuck-too", project="stuck", status="blocked")
    b.project("fine")
    view = dashboard(b.ws)
    assert view.waiting_on_them is not None and view.waiting_on_me is not None
    assert [(g.label, [t.id for t in g.todos]) for g in view.waiting_on_them] == [
        ("Alice", ["on-alice"]),
        ("Bob", ["on-bob"]),
    ]
    assert [t.id for t in view.waiting_on_me] == ["alice-waits"]
    assert [f.id for f in view.blocked] == ["stuck", "stuck-too"]
    assert view.directs is not None
    assert [(d.person.id, d.waiting_on_them, d.waiting_on_me) for d in view.directs] == [
        ("alice", 1, 1)
    ]


def test_recent_notes_are_the_10_most_recently_modified(b: Builder):
    for n in range(12):
        rel = b.note(f"notes/n{n:02}.md", f"# Note {n}\n")
        os.utime(b.root / rel, (1_000_000 + n, 1_000_000 + n))
        b.ws.changed(rel)
    view = dashboard(b.ws)
    assert [f.id for f in view.recent_notes] == [f"n{n:02}" for n in range(11, 1, -1)]


def test_get_started_shows_until_an_entity_besides_me_exists(tmp_path: Path):
    b = Builder(tmp_path / "ws")
    b.note("notes/hello.md", "hi\n")
    assert dashboard(b.ws).get_started
    b.theme("platform")
    assert not dashboard(b.ws).get_started


def test_without_me_the_me_cards_are_empty_but_work_cards_remain(b: Builder):
    b.project("stuck", status="blocked", due=dt.date(2026, 11, 13))
    b.file(".memex/config.yaml", "format: 1\n")
    view = dashboard(b.ws)
    assert view.waiting_on_them is None
    assert view.waiting_on_me is None
    assert view.directs is None
    assert [f.id for f in view.blocked] == ["stuck"]
    assert [f.id for f in view.due_soon] == ["stuck"]


def test_notes_with_todos_to_create_are_listed(b: Builder):
    b.note("notes/standup.md", "- [ ] Draft plan\n", title="Standup")
    b.note("notes/done.md", "- [x] Done\n- [ ] [[2026-11-01-old]]\n", title="Done")
    b.todo("2026-11-01-old", owner="ada")
    assert [n.id for n in dashboard(b.ws).capture_notes] == ["standup"]
