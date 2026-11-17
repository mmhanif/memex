"""Entity lifecycle: Rename id, archive, guided delete, trash and repair (SPEC §5.5, §8)."""

import datetime as dt
from pathlib import Path

import pytest

from memex.core import lifecycle
from memex.core.clock import FixedClock
from memex.core.entities import entity_detail, list_entities, update_fields
from memex.core.errors import Exists, HasReferences, NotFound, UnknownReference, Validation
from memex.core.schema import EntityType
from memex.core.search import status_group
from memex.core.views import people_view
from tests.core.builder import TODAY, Builder


@pytest.fixture
def b(tmp_path: Path) -> Builder:
    return Builder(tmp_path / "ws")


# Rename id (§5.5)


def test_rename_id_rewrites_references_mentions_and_me_and_nothing_else(b: Builder):
    b.person("alice")
    b.person("bob")
    b.config_me("alice")
    b.todo("t1", owner="alice", body="Ask [[alice]] about alice. `[[alice]]` stays.\n")
    b.project("p", team=["alice", "bob"], body="```\n[[alice]]\n```\n")

    preview = lifecycle.rename_id(b.ws, "alice", "alice-smith", dry_run=True)

    assert preview.impact.summary == "updates 4 references in 3 files"
    assert (b.root / "people/alice.md").exists()

    done = lifecycle.rename_id(b.ws, "alice", "alice-smith", dry_run=False)

    assert done.skipped == ()
    assert not (b.root / "people/alice.md").exists()
    assert (b.root / "people/alice-smith.md").exists()
    todo = b.read("todos/t1.md")
    assert "owner: alice-smith\nrequester: ada\n" in todo
    assert todo.endswith("---\nAsk [[alice-smith]] about alice. `[[alice]]` stays.\n")
    project = b.ws.cache.get("projects/p.md")
    assert project is not None and project.fields["team"] == ["alice-smith", "bob"]
    assert b.read("projects/p.md").endswith("```\n[[alice]]\n```\n")
    assert "me: alice-smith" in b.read(".memex/config.yaml")
    me = b.ws.me()
    assert me is not None and me.id == "alice-smith"


def test_a_file_changed_after_the_preview_is_skipped_and_reported(b: Builder):
    b.person("alice")
    b.todo("t1", owner="alice")
    b.todo("t2", owner="alice")
    preview = lifecycle.rename_id(b.ws, "alice", "alice-smith", dry_run=True)
    b.file("todos/t2.md", b.read("todos/t2.md") + "edited outside\n")

    done = lifecycle.rename_id(b.ws, "alice", "alice-smith", dry_run=False, expected=preview.hashes)

    assert [(s.rel, s.code) for s in done.skipped] == [("todos/t2.md", "conflict")]
    assert "owner: alice-smith" in b.read("todos/t1.md")
    assert "owner: alice\n" in b.read("todos/t2.md")
    assert (b.root / "people/alice-smith.md").exists()


# Archive (§8.3)


def test_archiving_a_person_hides_them_from_pickers_but_keeps_them_on_their_todos(b: Builder):
    b.person("alice", title="Alice")
    b.person("carl", title="Carl")
    b.todo("t1", owner="alice")
    b.project("p", status="done", title="Alice handover")
    alice = b.ws.cache.get("people/alice.md")
    assert alice is not None

    lifecycle.archive(b.ws, "alice", alice.hash)

    assert "archived: 2026-11-12\n" in b.read("people/alice.md")
    assert [f.id for f in list_entities(b.ws, EntityType.PERSON)] == ["ada", "carl"]
    assert "alice" not in [p.id for p in people_view(b.ws).others]
    todo = entity_detail(b.ws, "t1")
    assert todo.broken == () and todo.names["alice"] == "Alice"
    archived, done = b.ws.cache.get("people/alice.md"), b.ws.cache.get("projects/p.md")
    assert archived is not None and done is not None
    assert status_group(archived) == status_group(done) == 2


def test_unarchiving_removes_the_date(b: Builder):
    b.person("alice", archived="2026-01-01")
    alice = b.ws.cache.get("people/alice.md")
    assert alice is not None

    lifecycle.unarchive(b.ws, "alice", alice.hash)

    assert "archived" not in b.read("people/alice.md")


def test_me_cant_be_archived(b: Builder):
    me = b.ws.require_me()

    with pytest.raises(Validation, match="Me can't be archived"):
        lifecycle.archive(b.ws, me.id, me.hash)
    with pytest.raises(Validation, match="Me can't be archived"):
        update_fields(b.ws, me.id, me.hash, set={"archived": "2026-11-12"})


def test_archiving_a_person_lists_their_loose_ends(b: Builder):
    b.person("alice")
    b.todo("t1", owner="alice")
    b.todo("t2", owner="alice")
    b.todo("t3", owner="alice", status="done")
    b.project("p1", lead="alice")
    b.project("p2", lead="alice", status="done")
    b.deliverable("d1", project="p1", lead="alice", status="blocked")
    b.person("bob", manager="alice")
    b.person("cy", manager="alice", archived="2026-01-01")

    ends = lifecycle.loose_ends(b.ws, "alice")

    assert [(e.label, [f.id for f in e.items]) for e in ends] == [
        ("Owner of 2 open To-dos", ["t1", "t2"]),
        ("Lead on 2 active Projects or Deliverables", ["d1", "p1"]),
        ("Manager of 1 Person", ["bob"]),
    ]


def test_archiving_a_theme_warns_about_its_unfinished_projects(b: Builder):
    b.theme("platform")
    b.project("p1", theme="platform", status="on-hold")
    b.project("p2", theme="platform", status="cancelled")

    [end] = lifecycle.loose_ends(b.ws, "platform")

    assert end.label == "1 Project not done or cancelled"
    assert [f.id for f in end.items] == ["p1"]


def test_a_project_has_no_loose_ends_to_archive(b: Builder):
    b.project("p1")

    assert lifecycle.loose_ends(b.ws, "p1") == ()


# Delete and trash (§8.4)

STAMP = ".memex/trash/20261112-000000"


def test_deleting_a_person_with_no_references_moves_the_file_to_trash(b: Builder):
    b.person("alice")

    done = lifecycle.delete_entity(b.ws, "alice", "plain", dry_run=False)

    assert done.trash == f"{STAMP}/people/alice.md"
    assert not (b.root / "people/alice.md").exists()
    assert (b.root / STAMP / "people/alice.md").exists()
    assert b.ws.cache.resolve("alice").status == "missing"


def test_a_plain_delete_is_refused_while_something_refers_to_it(b: Builder):
    b.person("alice")
    b.note("notes/n.md", "See [[alice]].\n")

    with pytest.raises(HasReferences) as caught:
        lifecycle.delete_entity(b.ws, "alice", "plain", dry_run=False)

    assert caught.value.referrers == ("notes/n.md",)
    assert (b.root / "people/alice.md").exists()


def test_me_cant_be_deleted(b: Builder):
    with pytest.raises(Validation, match="Me can't be deleted"):
        lifecycle.delete_entity(b.ws, "ada", "plain", dry_run=True)


def test_delete_with_replace_rewrites_every_reference_and_mention(b: Builder):
    b.person("alice")
    b.person("bob", title="Bob")
    b.todo("t1", owner="alice", body="Ask [[alice]].\n")
    b.project("p", lead="alice", team=["alice", "bob"])

    preview = lifecycle.delete_entity(b.ws, "alice", "replace", "bob", dry_run=True)
    assert preview.impact.summary == "updates 4 references in 2 files"
    done = lifecycle.delete_entity(b.ws, "alice", "replace", "bob", dry_run=False)

    assert done.skipped == () and done.trash == f"{STAMP}/people/alice.md"
    todo = b.ws.cache.get("todos/t1.md")
    project = b.ws.cache.get("projects/p.md")
    assert todo is not None and project is not None
    assert todo.fields["owner"] == "bob" and todo.body == "Ask [[bob]].\n"
    assert project.fields["lead"] == "bob" and project.fields["team"] == ["bob"]


def test_replace_needs_an_entity_of_the_same_type(b: Builder):
    b.person("alice")
    b.project("p", lead="alice")

    with pytest.raises(Validation, match="another Person"):
        lifecycle.delete_entity(b.ws, "alice", "replace", "p", dry_run=True)


def test_delete_with_remove_clears_fields_drops_list_entries_and_unlinks_mentions(b: Builder):
    b.person("alice", title="Alice Smith")
    b.person("bob")
    b.project("p", lead="alice", team=["alice", "bob"], body="Ask [[alice]] or `[[alice]]`.\n")
    b.note("notes/n.md", "Met [[alice]].\n", people=["alice"])

    done = lifecycle.delete_entity(b.ws, "alice", "remove", dry_run=False)

    assert done.trash is not None
    project = b.ws.cache.get("projects/p.md")
    assert project is not None
    assert "lead" not in project.fields and project.fields["team"] == ["bob"]
    assert project.body == "Ask Alice Smith or `[[alice]]`.\n"
    assert b.read("notes/n.md") == "---\n---\nMet Alice Smith.\n"


def test_remove_is_refused_when_a_todo_names_the_person_as_owner(b: Builder):
    b.person("alice")
    b.todo("t1", owner="alice")

    preview = lifecycle.delete_entity(b.ws, "alice", "remove", dry_run=True)
    assert [(x.rel, x.field) for x in preview.impact.blocked] == [("todos/t1.md", "owner")]
    with pytest.raises(Validation, match="Remove is blocked"):
        lifecycle.delete_entity(b.ws, "alice", "remove", dry_run=False)

    assert (b.root / "people/alice.md").exists()
    assert "owner: alice" in b.read("todos/t1.md")


def test_trash_lists_each_delete_newest_first_and_restore_puts_it_back(b: Builder):
    b.person("alice", title="Alice")
    b.note("notes/trip/a.md", "# A\n")
    b.note("notes/trip/b.md", "# B\n")
    lifecycle.delete_entity(b.ws, "alice", dry_run=False)
    b.clock = b.ws.clock = FixedClock(TODAY, dt.datetime(2026, 11, 12, 9, 0))
    b.ws.trash("notes/trip")

    entries = lifecycle.list_trash(b.ws)

    assert [(e.entry, e.path, e.files, e.deleted) for e in entries] == [
        (
            "20261112-090000",
            "notes/trip",
            ("notes/trip/a.md", "notes/trip/b.md"),
            dt.datetime(2026, 11, 12, 9, 0),
        ),
        (
            "20261112-000000",
            "people/alice.md",
            ("people/alice.md",),
            dt.datetime(2026, 11, 12, 0, 0),
        ),
    ]

    lifecycle.restore(b.ws, "20261112-000000")

    assert b.ws.cache.resolve("alice").status == "found"
    assert [e.entry for e in lifecycle.list_trash(b.ws)] == ["20261112-090000"]


def test_restore_fails_cleanly_when_the_id_has_since_been_reused(b: Builder):
    b.person("alice")
    lifecycle.delete_entity(b.ws, "alice", dry_run=False)
    b.note("notes/alice.md", "# Someone else\n")

    with pytest.raises(Exists, match="alice"):
        lifecycle.restore(b.ws, "20261112-000000")

    assert (b.root / STAMP / "people/alice.md").exists()
    assert not (b.root / "people/alice.md").exists()


def test_restore_fails_cleanly_when_the_path_is_taken(b: Builder):
    b.note("notes/x/a.md", "# A\n")
    b.file("notes/x/pic.png", "old")
    b.ws.trash("notes/x")
    b.file("notes/x/pic.png", "new")

    with pytest.raises(Exists, match=r"notes/x/pic\.png"):
        lifecycle.restore(b.ws, "20261112-000000")

    assert b.read("notes/x/pic.png") == "new"
    assert not (b.root / "notes/x/a.md").exists()


def test_restore_refuses_names_outside_the_trash(b: Builder):
    with pytest.raises(NotFound):
        lifecycle.restore(b.ws, "../config.yaml")


# Broken references and repair (§8.5)


def test_broken_references_are_grouped_by_missing_id_with_ambiguous_ones_marked(b: Builder):
    b.todo("t1", owner="zed")
    b.project("p", team=["zed"], body="Ask [[zed]].\n")
    b.note("notes/Alice.md", "# A\n")
    b.person("alice")
    b.todo("t2", owner="alice")

    groups = lifecycle.broken_references(b.ws)

    assert [(g.id, g.status, [(u.rel, u.field) for u in g.uses]) for g in groups] == [
        ("alice", "ambiguous", [("todos/t2.md", "owner")]),
        (
            "zed",
            "missing",
            [("projects/p.md", "team"), ("projects/p.md", "mention"), ("todos/t1.md", "owner")],
        ),
    ]


def test_create_makes_the_entity_the_references_imply(b: Builder):
    b.todo("t1", owner="zed")
    b.project("p", team=["zed"])
    [group] = lifecycle.broken_references(b.ws)
    assert group.create_types == (EntityType.PERSON,)

    done = lifecycle.repair(b.ws, "zed", "create")

    assert done.rel == "people/zed.md"
    assert b.ws.cache.resolve("zed").status == "found"
    assert lifecycle.broken_references(b.ws) == []


def test_create_is_disabled_when_the_references_disagree_about_the_type(b: Builder):
    b.deliverable("d", project="zed")
    b.todo("t1", owner="zed")
    [group] = lifecycle.broken_references(b.ws)
    assert group.create_types == ()

    with pytest.raises(Validation, match="disagree"):
        lifecycle.repair(b.ws, "zed", "create")


def test_repair_replace_rewrites_every_occurrence(b: Builder):
    b.person("zoe")
    b.todo("t1", owner="zed", body="[[zed]]\n")
    b.config_me("zed")

    done = lifecycle.repair(b.ws, "zed", "replace", "zoe", dry_run=False)

    assert done.impact.summary == "updates 3 references in 2 files"
    assert lifecycle.broken_references(b.ws) == []
    me = b.ws.me()
    assert me is not None and me.id == "zoe"


def test_repair_replace_needs_the_right_type(b: Builder):
    b.project("p")
    b.todo("t1", owner="zed")

    with pytest.raises(UnknownReference):
        lifecycle.repair(b.ws, "zed", "replace", "p", dry_run=False)


def test_repair_remove_follows_the_delete_rules(b: Builder):
    b.project("p", team=["zed"], body="See [[zed]].\n")
    b.todo("t1", owner="zed")

    with pytest.raises(Validation, match="Remove is blocked"):
        lifecycle.repair(b.ws, "zed", "remove", dry_run=False)
    b.file("todos/t1.md", "---\ntitle: T1\nowner: ada\nrequester: ada\nstatus: open\n---\n")
    lifecycle.repair(b.ws, "zed", "remove", dry_run=False)

    project = b.ws.cache.get("projects/p.md")
    assert project is not None and "team" not in project.fields and project.body == "See zed.\n"
