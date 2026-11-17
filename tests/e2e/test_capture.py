"""SPEC §6.4: inline To-do capture from a Note, and the live To-do row it leaves."""

from pathlib import Path

from playwright.sync_api import Page, expect

from memex.web.app import AppState
from tests.e2e.conftest import origin
from tests.e2e.test_editor import put, wait_for_disk
from tests.e2e.test_people_todos import ALICE

NOTE = "notes/standup.md"
TODO = "todos/2026-11-12-draft-plan.md"


def test_create_todos_from_a_note_then_tick_the_live_row(app: Page, server: AppState, root: Path):
    put(root, "people/alice-smith.md", ALICE)
    body = "- [ ] Draft plan @alice\n  For Q1\n- [ ] Review @zz\n"
    put(root, NOTE, f"---\ntitle: Standup\n---\n{body}")
    app.goto(f"{origin(server)}/#/e/standup")

    app.get_by_role("button", name="Create 2 To-dos").click()
    dialog = app.get_by_role("dialog", name="Create To-dos from Standup")
    expect(dialog.locator(".capture-row.has-errors")).to_contain_text("No Person matches @zz")
    expect(dialog.get_by_role("button", name="Create 2 To-dos")).to_be_disabled()
    dialog.get_by_label("Create: Review").uncheck()
    dialog.get_by_role("button", name="Create 1 To-do").click()
    expect(dialog).to_be_hidden()

    wait_for_disk(
        root / NOTE,
        "---\ntitle: Standup\n---\n- [ ] [[2026-11-12-draft-plan]]\n- [ ] Review @zz\n",
    )
    todo = (root / TODO).read_text("utf-8")
    assert "owner: alice-smith" in todo and "source: standup" in todo
    assert todo.endswith("---\nFor Q1\n")

    row = app.locator(".markdown .todo-ref")
    expect(row).to_contain_text("Draft plan")
    expect(row).to_contain_text("Alice Smith")
    row.get_by_label("Done: Draft plan").check()
    expect(app.locator(".markdown .todo-ref.finished")).to_be_visible()
    assert "status: done" in (root / TODO).read_text("utf-8")
    assert (root / NOTE).read_text("utf-8").count("- [ ] [[2026-11-12-draft-plan]]") == 1
