"""Templates (SPEC §7 Acceptance)."""

from pathlib import Path

import pytest

from memex.core.config import with_keys
from memex.core.entities import create_entity
from memex.core.errors import Exists, MeNotSet, NotFound, UnknownReference, Validation
from memex.core.schema import EntityType
from memex.core.templates import customise_template, templates_for
from tests.core.builder import Builder


@pytest.fixture
def b(tmp_path: Path) -> Builder:
    return Builder(tmp_path / "ws")


def custom(b: Builder, key: str, text: str) -> Path:
    path = b.root / ".memex/templates" / f"{key}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def names(b: Builder, entity_type: EntityType | None) -> list[str]:
    found = templates_for(b.root, entity_type, b.ws.config.hidden_templates)
    return [t.name for t in found.usable]


def hide(b: Builder, *keys: str) -> None:
    rel = ".memex/config.yaml"
    text = (b.root / rel).read_text()
    b.file(rel, with_keys(text, {"hidden_templates": list(keys)}))


def test_built_in_note_templates_with_blank_as_the_default(b: Builder):
    found = templates_for(b.root, None)
    assert [t.name for t in found.templates] == ["blank", "meeting", "one-on-one"]
    assert found.default.name == "blank"
    assert [t.display_name for t in found.templates] == ["Blank", "Meeting", "1:1"]


def test_a_custom_template_replaces_the_built_in_and_deleting_it_restores_it(b: Builder):
    path = custom(b, "note/meeting", "---\ntemplate: {name: Standup}\n---\n## Yesterday\n")
    [meeting] = [t for t in templates_for(b.root, None).templates if t.name == "meeting"]
    assert (meeting.source, meeting.display_name, meeting.body) == (
        "custom",
        "Standup",
        "## Yesterday\n",
    )

    path.unlink()
    [meeting] = [t for t in templates_for(b.root, None).templates if t.name == "meeting"]
    assert (meeting.source, meeting.display_name) == ("builtin", "Meeting")


def test_a_custom_template_with_a_new_name_adds_a_variant(b: Builder):
    custom(b, "project/migration", "---\ntemplate: {name: Migration}\n---\n## Cutover\n")
    assert names(b, EntityType.PROJECT) == ["blank", "migration", "project"]


def test_hidden_templates_are_left_out_but_blank_cant_be_hidden(b: Builder):
    hide(b, "note/one-on-one", "note/blank")
    assert names(b, None) == ["blank", "meeting"]


def test_placeholders_are_filled_and_the_template_block_is_dropped(b: Builder):
    custom(
        b,
        "note/meeting",
        "---\ntemplate: {name: Meeting}\ndate: '{{date}}'\npeople: ['{{me}}']\n"
        "topic: '{{title}} {{foo}}'\n---\n# {{title}} on {{date}} with {{me}} {{foo}}\n",
    )
    created = create_entity(b.ws, None, {"title": "Platform sync"}, template="meeting")

    assert created.rel == "notes/2026-11-12-platform-sync.md"
    assert b.read(created.rel) == (
        "---\ntitle: Platform sync\ndate: 2026-11-12\npeople: [ada]\n"
        "topic: Platform sync {{foo}}\ncreated: 2026-11-12\n---\n"
        "# Platform sync on 2026-11-12 with ada {{foo}}\n"
    )


def test_the_built_in_meeting_note_lands_in_notes_with_a_dated_id(b: Builder):
    created = create_entity(b.ws, None, {"title": "Platform sync"}, template="meeting")
    assert created.rel == "notes/2026-11-12-platform-sync.md"
    assert "## Agenda" in b.read(created.rel)


def test_template_values_are_defaults_that_the_callers_fields_override(b: Builder):
    custom(b, "project/project", "---\ntemplate: {default: true}\nstatus: active\n---\n")
    first = create_entity(b.ws, EntityType.PROJECT, {"title": "A"})
    second = create_entity(b.ws, EntityType.PROJECT, {"title": "B", "status": "on-hold"})
    assert "status: active" in b.read(first.rel)
    assert "status: on-hold" in b.read(second.rel)


def test_title_and_required_references_never_come_from_a_template(b: Builder):
    b.entity("projects", "y", status="active")
    b.entity("projects", "z", status="active")
    custom(
        b,
        "deliverable/deliverable",
        "---\ntemplate: {default: true}\ntitle: X\nproject: y\ncreated: 2001-01-01\n---\n",
    )
    with pytest.raises(Validation) as e:
        create_entity(b.ws, EntityType.DELIVERABLE, {"title": "Cutover"})
    assert [p.field for p in e.value.field_errors] == ["project"]

    created = create_entity(b.ws, EntityType.DELIVERABLE, {"title": "Cutover", "project": "z"})
    text = b.read(created.rel)
    assert "title: Cutover\nproject: z\n" in text
    assert "created: 2026-11-12" in text


def test_a_broken_custom_template_is_reported_and_its_built_in_is_not_offered(b: Builder):
    custom(b, "note/meeting", "---\ntemplate: [unclosed\n---\n")
    found = templates_for(b.root, None)
    [meeting] = [t for t in found.templates if t.name == "meeting"]
    assert meeting.error is not None
    assert [t.name for t in found.usable] == ["blank", "one-on-one"]
    with pytest.raises(Validation):
        create_entity(b.ws, None, {"title": "x"}, template="meeting")


def test_two_default_claims_pick_the_alphabetically_first_with_a_warning(b: Builder):
    custom(b, "note/zeta", "---\ntemplate: {default: true}\n---\nZ\n")
    custom(b, "note/alpha", "---\ntemplate: {default: true}\n---\nA\n")
    found = templates_for(b.root, None)
    assert found.default.name == "alpha"
    assert found.warnings and "note/alpha" in found.warnings[0]


def test_a_template_reference_error_names_the_template(b: Builder):
    custom(b, "note/meeting", "---\ntemplate: {name: M}\npeople: [nobody]\n---\n")
    with pytest.raises(UnknownReference) as e:
        create_entity(b.ws, None, {"title": "x"}, template="meeting")
    assert "note/meeting" in e.value.message


def test_the_person_template_defaults_kind_to_team_member(b: Builder):
    person = create_entity(b.ws, EntityType.PERSON, {"title": "Bob Jones"})
    stakeholder = create_entity(b.ws, EntityType.PERSON, {"title": "Carol"}, template="stakeholder")
    assert "kind: [team-member]" in b.read(person.rel)
    assert "kind: [stakeholder]" in b.read(stakeholder.rel)
    assert "## Running notes" in b.read(stakeholder.rel)


def test_customise_copies_a_built_in_into_the_workspace(b: Builder):
    rel = customise_template(b.ws, None, "meeting")
    assert rel == ".memex/templates/note/meeting.md"
    assert "## Agenda" in b.read(rel)
    [meeting] = [t for t in templates_for(b.root, None).templates if t.name == "meeting"]
    assert (meeting.source, meeting.overrides) == ("custom", True)
    with pytest.raises(Exists):
        customise_template(b.ws, None, "meeting")
    with pytest.raises(NotFound):
        customise_template(b.ws, None, "nope")


def test_badly_named_custom_templates_are_reported_not_dropped(b: Builder):
    custom(b, "note/My_Meeting", "---\n---\n")
    custom(b, "note/blank", "---\n---\n")
    errors = {t.name: t.error for t in templates_for(b.root, None).templates if t.error}
    assert set(errors) == {"My_Meeting", "blank"}
    assert [t.name for t in templates_for(b.root, None).usable] == [
        "blank",
        "meeting",
        "one-on-one",
    ]


def test_a_template_using_me_needs_me_set(b: Builder):
    text = (b.root / ".memex/config.yaml").read_text()
    b.file(".memex/config.yaml", with_keys(text, {"me": "nobody"}))
    with pytest.raises(MeNotSet):
        create_entity(b.ws, None, {"title": "Sync"}, template="meeting")
    assert create_entity(b.ws, None, {"title": "Sync"}).rel == "notes/sync.md"
