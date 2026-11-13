"""Person View (SPEC §11.6) and the People page (§11.3)."""

import datetime as dt
from pathlib import Path

import pytest

from memex.core.errors import NotFound
from memex.core.views import people_view, person_view
from tests.core.builder import Builder


@pytest.fixture
def b(tmp_path: Path) -> Builder:
    b = Builder(tmp_path / "ws")
    b.person("alice", manager="ada")
    b.person("bob", manager="ada")
    return b


def ids(todo_groups) -> list[str]:
    return [t.id for g in todo_groups for t in g.todos]


def test_a_todo_between_two_others_is_on_both_their_person_views(b: Builder):
    b.todo("alice-for-bob", owner="alice", requester="bob")
    alice = person_view(b.ws, "alice")
    bob = person_view(b.ws, "bob")
    assert ids(alice.waiting_on_them) == ["alice-for-bob"]
    assert ids(alice.waiting_on_me) == []
    assert ids(bob.waiting_on_them) == []
    assert ids(bob.waiting_on_me) == ["alice-for-bob"]


def test_the_two_columns_split_by_owner_and_requester(b: Builder):
    b.todo("from-me", owner="alice", due=dt.date(2026, 11, 20))
    b.todo("for-alice", owner="ada", requester="alice")
    b.todo("done", owner="alice", status="done", completed=dt.date(2026, 11, 1))
    view = person_view(b.ws, "alice")
    assert ids(view.waiting_on_them) == ["from-me"]
    assert ids(view.waiting_on_me) == ["for-alice"]
    assert ids(person_view(b.ws, "alice", include_done=True).waiting_on_them) == ["from-me", "done"]


def test_tagged_on_lists_each_work_item_with_its_roles(b: Builder):
    b.theme("platform", stakeholders=["alice"])
    b.project("data-migration", lead="alice", team=["alice", "bob"])
    b.deliverable("cutover", project="data-migration", team=["bob"])
    tagged = [(t.file.id, t.roles) for t in person_view(b.ws, "alice").tagged_on]
    assert tagged == [("data-migration", ("Lead", "Team")), ("platform", ("Stakeholder",))]


def test_header_has_manager_and_directs_and_notes_are_newest_first(b: Builder):
    b.person("carol", manager="alice")
    b.person("dan", manager="alice", archived=dt.date(2026, 1, 1))
    b.note("notes/old.md", title="Old 1:1", date=dt.date(2026, 10, 1), people=["ada", "alice"])
    b.note("notes/new.md", title="New 1:1", date=dt.date(2026, 11, 1), people=["alice"])
    b.note("notes/other.md", title="Other", people=["bob"])
    view = person_view(b.ws, "alice")
    assert view.manager is not None and view.manager.id == "ada"
    assert [p.id for p in view.directs] == ["carol"]
    assert [n.id for n in view.notes] == ["new", "old"]


def test_person_view_of_something_else_is_not_found(b: Builder):
    b.project("data-migration")
    with pytest.raises(NotFound):
        person_view(b.ws, "data-migration")


def tree(node) -> tuple:
    return (node.person.id, [tree(r) for r in node.reports])


def test_people_page_has_the_org_tree_from_me_others_and_stakeholders(b: Builder):
    b.person("boss")
    b.file(
        "people/ada.md",
        "---\ntitle: Ada\nkind: [team-member]\nmanager: boss\n---\n",
    )
    b.person("carol", manager="alice")
    b.person("erin")  # a Team Member not under Me
    b.person("gone", manager="ada", archived=dt.date(2026, 1, 1))
    b.person("sam", title="Sam", kind=["stakeholder"], organisation="Acme", role="CFO")
    b.project("p", stakeholders=["sam"], team=["alice"])
    b.deliverable("d", project="p", lead="sam")

    view = people_view(b.ws)
    assert view.manager is not None and view.manager.id == "boss"
    assert view.me is not None
    assert tree(view.me) == ("ada", [("alice", [("carol", [])]), ("bob", [])])
    assert [p.id for p in view.others] == ["erin"]
    assert [(s.file.id, s.tags) for s in view.stakeholders] == [("sam", 2)]


def test_a_manager_cycle_through_me_is_cut_for_display(b: Builder):
    b.person("carol", manager="alice")
    b.file("people/ada.md", "---\ntitle: Ada\nkind: [team-member]\nmanager: carol\n---\n")
    view = people_view(b.ws)
    assert view.manager is not None and view.manager.id == "carol"
    assert view.me is not None
    assert tree(view.me) == ("ada", [("alice", [("carol", [])]), ("bob", [])])
    assert view.others == ()


def test_without_me_everyone_is_in_others(b: Builder):
    b.file(".memex/config.yaml", "format: 1\n")
    view = people_view(b.ws)
    assert view.me is None
    assert [p.id for p in view.others] == ["ada", "alice", "bob"]
