"""Entities: schema, lenient read, strict write, create and update (SPEC §4, §8.1, §8.2)."""

from pathlib import Path

import pytest

from memex.core.entities import append_body, create_entity, find, replace_body, update_fields
from memex.core.errors import AmbiguousId, BadPath, Conflict, UnknownReference, Validation
from memex.core.schema import WORK_STATUSES, EntityType
from tests.core.builder import Builder


@pytest.fixture
def b(tmp_path: Path) -> Builder:
    return Builder(tmp_path / "ws")


def test_bad_status_loads_is_listed_and_carries_a_validation_warning(b: Builder):
    b.project("data-migration", status="wip")

    entry = b.ws.cache.get("projects/data-migration.md")

    assert entry is not None
    [warning] = [w for w in entry.warnings if w.kind == "validation"]
    assert "status" in warning.message
    assert "not-started, active, on-hold, blocked, done, cancelled" in warning.message


def test_creating_a_project_without_a_template_choice_uses_the_default_template(b: Builder):
    created = create_entity(b.ws, EntityType.PROJECT, {"title": "Data migration"})

    assert created.id == "data-migration"
    assert created.rel == "projects/data-migration.md"
    text = b.read(created.rel)
    assert text == (
        "---\ntitle: Data migration\nstatus: not-started\ncreated: 2026-11-12\n---\n"
        "## Goal\n\n## Scope\n\n## Risks\n\n## Decisions\n"
    )
    entry = b.ws.cache.get(created.rel)
    assert entry is not None
    assert entry.hash == created.hash


def test_a_todo_gets_a_date_prefixed_id_and_requester_defaults_to_me(b: Builder):
    b.person("alice-smith")

    created = create_entity(
        b.ws, EntityType.TODO, {"title": "Send revised deck", "owner": "alice-smith"}
    )

    assert created.id == "2026-11-12-send-revised-deck"
    entry = b.ws.cache.get(created.rel)
    assert entry is not None
    assert dict(entry.fields) | {"created": None} == {
        "title": "Send revised deck",
        "owner": "alice-smith",
        "requester": "ada",
        "status": "open",
        "created": None,
    }


def test_a_second_entity_with_the_same_title_gets_a_suffixed_id(b: Builder):
    first = create_entity(b.ws, EntityType.PROJECT, {"title": "Data migration"})
    second = create_entity(b.ws, EntityType.PROJECT, {"title": "Data migration"})
    assert (first.id, second.id) == ("data-migration", "data-migration-2")


def test_a_deliverable_needs_a_project(b: Builder):
    b.person("alice-smith")
    with pytest.raises(Validation) as missing:
        create_entity(b.ws, EntityType.DELIVERABLE, {"title": "Cutover plan"})
    assert [p.field for p in missing.value.field_errors] == ["project"]

    with pytest.raises(UnknownReference) as wrong_type:
        create_entity(
            b.ws, EntityType.DELIVERABLE, {"title": "Cutover plan", "project": "alice-smith"}
        )
    assert wrong_type.value.field == "project"
    assert not (b.root / "deliverables/cutover-plan.md").exists()


def test_an_unknown_reference_suggests_close_ids(b: Builder):
    b.person("alice-smith")
    with pytest.raises(UnknownReference) as e:
        create_entity(b.ws, EntityType.TODO, {"title": "x", "owner": "alise-smith"})
    assert e.value.suggestions == ("alice-smith",)


def test_bad_enums_and_dates_are_rejected_listing_the_allowed_values(b: Builder):
    with pytest.raises(Validation) as e:
        create_entity(
            b.ws, EntityType.PROJECT, {"title": "X", "status": "wip", "due": "2026-02-30"}
        )
    by_field = {p.field: p for p in e.value.field_errors}
    assert by_field["status"].allowed == WORK_STATUSES
    assert "YYYY-MM-DD" in by_field["due"].message


def test_a_person_needs_at_least_one_kind(b: Builder):
    with pytest.raises(Validation) as e:
        create_entity(b.ws, EntityType.PERSON, {"title": "Bob", "kind": []}, template="blank")
    assert [p.field for p in e.value.field_errors] == ["kind"]


def test_done_sets_completed_and_reopening_removes_it(b: Builder):
    b.person("alice-smith")
    rel = b.todo("2026-11-01-call", owner="alice-smith")
    entry = b.ws.cache.get(rel)
    assert entry is not None

    done = update_fields(b.ws, entry.id, entry.hash, set={"status": "done"})
    assert "status: done\n" in b.read(rel)
    assert "completed: 2026-11-12\n" in b.read(rel)

    update_fields(b.ws, entry.id, done.hash, set={"status": "open"})
    assert "completed" not in b.read(rel)
    assert "status: open" in b.read(rel)


def test_editing_the_title_never_renames_the_file(b: Builder):
    created = create_entity(b.ws, EntityType.PROJECT, {"title": "Data migration"})
    update_fields(b.ws, created.id, created.hash, set={"title": "Platform move"})
    assert "title: Platform move" in b.read("projects/data-migration.md")


def test_field_updates_are_hash_checked(b: Builder):
    created = create_entity(b.ws, EntityType.PROJECT, {"title": "Data migration"})
    update_fields(b.ws, created.id, created.hash, set={"status": "active"})
    with pytest.raises(Conflict):
        update_fields(b.ws, created.id, created.hash, set={"status": "done"})


def test_created_and_completed_cant_be_written(b: Builder):
    created = create_entity(b.ws, EntityType.PROJECT, {"title": "Data migration"})
    with pytest.raises(Validation):
        update_fields(b.ws, created.id, created.hash, set={"created": "2020-01-01"})
    with pytest.raises(Validation):
        create_entity(b.ws, EntityType.PROJECT, {"title": "Y", "created": "2020-01-01"})


def test_unsetting_a_required_field_is_rejected(b: Builder):
    created = create_entity(b.ws, EntityType.PROJECT, {"title": "Data migration"})
    with pytest.raises(Validation):
        update_fields(b.ws, created.id, created.hash, unset=["status"])


def test_an_update_leaves_outside_problems_in_other_fields_alone(b: Builder):
    rel = b.project("data-migration", due="soon")
    entry = b.ws.cache.get(rel)
    assert entry is not None
    update_fields(b.ws, entry.id, entry.hash, set={"status": "blocked"})
    assert "due: soon" in b.read(rel)


def test_a_manager_cycle_is_rejected_on_write(b: Builder):
    b.person("alice", manager="bob")
    rel = b.person("bob")
    bob = b.ws.cache.get(rel)
    assert bob is not None
    with pytest.raises(Validation) as e:
        update_fields(b.ws, "bob", bob.hash, set={"manager": "alice"})
    assert "cycle" in e.value.message
    with pytest.raises(Validation):
        update_fields(b.ws, "bob", bob.hash, set={"manager": "bob"})


def test_new_lists_are_written_in_flow_style(b: Builder):
    b.person("alice")
    b.person("bob")
    created = create_entity(b.ws, EntityType.THEME, {"title": "Platform", "team": ["alice", "bob"]})
    assert "team: [alice, bob]\n" in b.read(created.rel)


def test_body_replace_keeps_the_frontmatter_and_is_hash_checked(b: Builder):
    created = create_entity(b.ws, EntityType.PROJECT, {"title": "Data migration"})
    replace_body(b.ws, created.id, "New body\n", created.hash)
    assert b.read(created.rel) == (
        "---\ntitle: Data migration\nstatus: not-started\ncreated: 2026-11-12\n---\nNew body\n"
    )
    with pytest.raises(Conflict) as e:
        replace_body(b.ws, created.id, "Stale\n", created.hash)
    assert e.value.current.text == "New body\n"


def test_append_adds_to_the_end_of_the_body(b: Builder):
    rel = b.note("notes/log.md", "first")
    append_body(b.ws, "log", "second\n")
    assert b.read(rel) == "first\nsecond\n"


def test_an_ambiguous_id_names_no_file(b: Builder):
    b.note("notes/Alice.md", "x")
    b.person("alice")
    with pytest.raises(AmbiguousId):
        find(b.ws, "alice")
    with pytest.raises(UnknownReference):
        create_entity(b.ws, EntityType.TODO, {"title": "x", "owner": "alice"})


def test_a_note_can_be_created_in_another_folder(b: Builder):
    created = create_entity(b.ws, None, {"title": "Retro"}, folder="meetings/2026")
    assert created.rel == "meetings/2026/retro.md"
    assert b.ws.cache.get(created.rel) is not None
    assert create_entity(b.ws, None, {"title": "Top"}, folder="").rel == "top.md"


@pytest.mark.parametrize("folder", ["projects", ".memex", "notes/../..", "people"])
def test_a_note_cant_be_created_in_a_type_or_hidden_folder(b: Builder, folder: str):
    with pytest.raises((BadPath, Validation)):
        create_entity(b.ws, None, {"title": "Retro"}, folder=folder)


def test_only_notes_take_a_folder(b: Builder):
    with pytest.raises(Validation):
        create_entity(b.ws, EntityType.PROJECT, {"title": "X"}, folder="notes")
