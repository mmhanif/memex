"""Reading Entities: detail and list, with cross-file checks (SPEC §4.1, §4.6, §11.5, §17.2)."""

import datetime as dt
from pathlib import Path

import pytest

from memex.core.entities import entity_detail, list_entities
from memex.core.schema import EntityType
from tests.core.builder import Builder


@pytest.fixture
def b(tmp_path: Path) -> Builder:
    return Builder(tmp_path / "ws")


def test_a_case_clash_flags_both_files_and_references_to_it_as_ambiguous(b: Builder):
    b.note("notes/Alice.md", "x")
    b.person("alice")
    b.todo("2026-11-01-call", owner="alice")

    for rel in ("notes/Alice.md", "people/alice.md"):
        entry = b.ws.cache.get(rel)
        assert entry is not None
        assert entry.ambiguous

    detail = entity_detail(b.ws, "2026-11-01-call")
    assert [(r.field, r.id, r.status) for r in detail.broken] == [("owner", "alice", "ambiguous")]


def test_missing_and_wrong_type_references_and_mentions_are_broken(b: Builder):
    b.person("alice")
    b.project("p", lead="nobody", theme="alice", body="See [[ghost]] and [[alice]].\n")
    detail = entity_detail(b.ws, "p")
    assert {(r.field, r.id, r.status) for r in detail.broken} == {
        ("theme", "alice", "wrong_type"),
        ("lead", "nobody", "missing"),
        ("mention", "ghost", "missing"),
    }
    assert detail.names == {"alice": "Alice"}


def test_a_hand_written_manager_cycle_is_flagged_on_both_persons(b: Builder):
    b.person("alice", manager="bob")
    b.person("bob", manager="alice")
    for id in ("alice", "bob"):
        warnings = [w.message for w in entity_detail(b.ws, id).warnings]
        assert any("manager cycle" in m for m in warnings), id


def test_detail_lists_children_todos_notes_about_it_and_mentions(b: Builder):
    b.person("alice")
    b.theme("platform")
    b.project("data-migration", theme="platform")
    b.deliverable("cutover", project="data-migration")
    b.todo("2026-11-01-call", owner="alice", about="data-migration")
    b.note("notes/kickoff.md", "", title="Kickoff", about=["data-migration"])
    b.note("notes/standup.md", "We discussed [[data-migration]].\n`[[data-migration]]`\n")

    project = entity_detail(b.ws, "data-migration")
    assert [f.id for f in project.children] == ["cutover"]
    assert [f.id for f in project.todos] == ["2026-11-01-call"]
    assert [f.id for f in project.notes] == ["kickoff"]
    assert [f.id for f in project.mentioned_in] == ["standup"]
    assert [f.id for f in entity_detail(b.ws, "platform").children] == ["data-migration"]


def test_list_filters_by_type_status_theme_person_label_and_due(b: Builder):
    b.person("alice")
    b.theme("platform")
    b.project("a", theme="platform", lead="alice", labels=["q4"], due=dt.date(2026, 11, 20))
    b.project("b", status="done", team=["alice"])
    b.project("c", status="blocked")
    b.deliverable("d", project="a")

    def ids(**filters):
        return [f.id for f in list_entities(b.ws, **filters)]

    assert ids(type=EntityType.PROJECT) == ["a", "b", "c"]
    assert ids(type=EntityType.PROJECT, status="blocked") == ["c"]
    assert ids(theme="platform") == ["a"]
    assert ids(project="a") == ["d"]
    assert ids(person="alice") == ["a", "b"]
    assert ids(label="q4") == ["a"]
    assert ids(type=EntityType.PROJECT, due_before=dt.date(2026, 12, 1)) == ["a"]


def test_list_hides_archived_unless_asked(b: Builder):
    b.person("alice")
    b.person("old", archived=dt.date(2026, 1, 1))
    people = [f.id for f in list_entities(b.ws, type=EntityType.PERSON)]
    assert "old" not in people
    assert "old" in [
        f.id for f in list_entities(b.ws, type=EntityType.PERSON, include_archived=True)
    ]
