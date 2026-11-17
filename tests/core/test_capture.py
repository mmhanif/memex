"""Inline To-do capture (SPEC §6.4)."""

from pathlib import Path

import pytest

from memex.core.capture import RowChoice, confirm, preview
from memex.core.errors import Conflict, MeNotSet, UnknownReference, Validation
from memex.core.store import TRASH
from tests.core.builder import Builder


@pytest.fixture
def b(tmp_path: Path) -> Builder:
    b = Builder(tmp_path / "ws")
    b.person("alice-smith", title="Alice Smith")
    b.person("bob-jones", title="Bob Jones")
    return b


def offered(b: Builder, body: str) -> list[str]:
    b.note("notes/standup.md", body, title="Standup")
    return [row.text for row in preview(b.ws, "standup").rows]


def test_unchecked_items_at_any_indent_and_with_any_bullet_are_offered(b: Builder):
    body = "- [ ] One\n* [ ] Two\n  + [ ] Three\n- plain\n1. [ ] numbered\n"
    assert offered(b, body) == ["One", "Two", "Three"]


def test_done_items_items_in_fenced_code_and_converted_lines_are_not_offered(b: Builder):
    body = (
        "- [x] Done already\n"
        "- [X] Also done\n"
        "```\n- [ ] In code\n```\n"
        "- [ ] [[2026-11-01-old-one]]\n"
        "- [ ] Real one\n"
    )
    assert offered(b, body) == ["Real one"]


def test_items_in_frontmatter_are_not_offered(b: Builder):
    b.file("notes/odd.md", "---\ntitle: Odd\nx: |\n  - [ ] not me\n---\n- [ ] me\n")
    assert [r.text for r in preview(b.ws, "odd").rows] == ["me"]


def test_capture_creates_the_todo_with_source_and_body_and_rewrites_the_item(b: Builder):
    b.note(
        "notes/standup.md",
        "# Standup\n\n- [ ] Draft plan @alice\n  Cover Q1 and Q2\n  - with numbers\n- after\n",
        title="Standup",
    )
    p = preview(b.ws, "standup")
    done = confirm(b.ws, "standup", p.hash, [RowChoice(0)])

    [todo] = done.todos
    assert todo.rel == "todos/2026-11-12-draft-plan.md"
    created = b.ws.cache.get(todo.rel)
    assert created is not None
    assert created.fields["owner"] == "alice-smith"
    assert created.fields["requester"] == "ada"
    assert created.fields["source"] == "standup"
    assert created.fields["status"] == "open"
    assert created.body == "Cover Q1 and Q2\n- with numbers\n"
    assert b.read("notes/standup.md").endswith(
        "# Standup\n\n- [ ] [[2026-11-12-draft-plan]]\n- after\n"
    )
    assert preview(b.ws, "standup").rows == ()


def todo_files(b: Builder) -> list[str]:
    return sorted(p.name for p in (b.root / "todos").iterdir())


def test_a_note_changed_since_the_preview_writes_nothing(b: Builder):
    b.note("notes/standup.md", "- [ ] Draft plan\n", title="Standup")
    p = preview(b.ws, "standup")
    b.note("notes/standup.md", "- [ ] Draft plan\n- [ ] Another\n", title="Standup")
    with pytest.raises(Conflict):
        confirm(b.ws, "standup", p.hash, [RowChoice(0)])
    assert todo_files(b) == []
    assert "Draft plan" in b.read("notes/standup.md")


def test_a_failed_note_rewrite_moves_the_new_todos_to_trash(
    b: Builder, monkeypatch: pytest.MonkeyPatch
):
    b.note("notes/standup.md", "- [ ] One\n- [ ] Two\n", title="Standup")
    p = preview(b.ws, "standup")
    real_write = b.ws.store.write

    def write(rel: str, text: str, expected_hash: str) -> str:
        if rel == "notes/standup.md":  # an outside edit lands between create and rewrite
            (b.root / rel).write_text("- [ ] One\n- [ ] Two\nedited\n")
        return real_write(rel, text, expected_hash)

    monkeypatch.setattr(b.ws.store, "write", write)
    with pytest.raises(Conflict):
        confirm(b.ws, "standup", p.hash, [RowChoice(0), RowChoice(1)])
    assert todo_files(b) == []
    trashed = sorted(p.name for p in (b.root / TRASH).rglob("*.md"))
    assert trashed == ["2026-11-12-one.md", "2026-11-12-two.md"]
    assert b.read("notes/standup.md") == "- [ ] One\n- [ ] Two\nedited\n"


def test_a_row_with_a_parse_error_blocks_until_edited_or_unticked(b: Builder):
    b.note("notes/standup.md", "- [ ] Review @zz\n- [ ] Call vendor\n", title="Standup")
    p = preview(b.ws, "standup")
    [bad, good] = p.rows
    assert [e.token for e in bad.errors] == ["@zz"]
    assert good.errors == ()
    with pytest.raises(UnknownReference):
        confirm(b.ws, "standup", p.hash, [RowChoice(0), RowChoice(1)])
    assert todo_files(b) == []

    done = confirm(b.ws, "standup", p.hash, [RowChoice(0, {"owner": "bob-jones"}), RowChoice(1)])
    assert [t.id for t in done.todos] == ["2026-11-12-review", "2026-11-12-call-vendor"]
    assert b.ws.cache.get(done.todos[0].rel).fields["owner"] == "bob-jones"  # type: ignore[union-attr]


def test_unticked_rows_are_left_as_they_are(b: Builder):
    b.note("notes/standup.md", "- [ ] One\n- [ ] Two\n- [ ] One\n", title="Standup")
    p = preview(b.ws, "standup")
    confirm(b.ws, "standup", p.hash, [RowChoice(2)])
    assert b.read("notes/standup.md").endswith("- [ ] One\n- [ ] Two\n- [ ] [[2026-11-12-one]]\n")


def test_edited_parties_due_and_about_are_used(b: Builder):
    b.project("launch")
    b.note("notes/standup.md", "- [ ] Ship due:2026-12-01\n", title="Standup")
    p = preview(b.ws, "standup")
    edits = {"owner": "alice-smith", "requester": "bob-jones", "due": None, "about": "launch"}
    [todo] = confirm(b.ws, "standup", p.hash, [RowChoice(0, edits)]).todos
    fields = b.ws.cache.get(todo.rel).fields  # type: ignore[union-attr]
    assert (fields["owner"], fields["requester"], fields["about"]) == (
        "alice-smith",
        "bob-jones",
        "launch",
    )
    assert "due" not in fields


def test_about_is_prefilled_only_when_the_note_names_one_project_or_deliverable(b: Builder):
    b.theme("platform")
    b.project("launch")
    b.project("migrate")
    b.note("notes/a.md", "- [ ] x\n", about=["platform", "launch"])
    b.note("notes/b.md", "- [ ] x\n", about=["launch", "migrate"])
    assert preview(b.ws, "a").rows[0].about == "launch"
    assert preview(b.ws, "b").rows[0].about is None


def test_participants_never_set_the_owner(b: Builder):
    b.note("notes/1-1.md", "- [ ] Follow up\n", people=["alice-smith"])
    [row] = preview(b.ws, "1-1").rows
    assert (row.owner, row.requester) == ("ada", "ada")


def test_without_me_a_party_left_to_default_is_me_not_set(b: Builder):
    b.note("notes/standup.md", "- [ ] Call @alice\n", title="Standup")
    b.config_me("nobody")
    p = preview(b.ws, "standup")
    with pytest.raises(MeNotSet):
        confirm(b.ws, "standup", p.hash, [RowChoice(0)])
    done = confirm(b.ws, "standup", p.hash, [RowChoice(0, {"requester": "bob-jones"})])
    assert len(done.todos) == 1


def test_only_notes_capture(b: Builder):
    with pytest.raises(Validation):
        preview(b.ws, "alice-smith")


def test_an_item_that_is_only_a_mention_of_something_besides_a_todo_is_offered(b: Builder):
    assert offered(b, "- [ ] [[alice-smith]]\n") == ["[[alice-smith]]"]


def test_an_unmatched_owner_left_unedited_is_unknown_reference_with_candidates(b: Builder):
    b.person("alan-po", title="Alan Po")
    b.person("alice-po", title="Alice Po")
    b.note("notes/standup.md", "- [ ] Review @al\n", title="Standup")
    p = preview(b.ws, "standup")
    with pytest.raises(UnknownReference) as e:
        confirm(b.ws, "standup", p.hash, [RowChoice(0)])
    assert e.value.suggestions == ("alan-po", "alice-po", "alice-smith")
