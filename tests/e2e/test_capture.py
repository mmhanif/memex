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


def test_a_note_with_task_items_shows_the_capture_bar(app: Page, server: AppState, root: Path):
    body = "- [ ] Draft plan\n- [ ] Review\n- [x] Done already\n"
    put(root, NOTE, f"---\ntitle: Standup\n---\n{body}")
    app.goto(f"{origin(server)}/#/e/standup")

    bar = app.locator(".capture-bar")
    expect(bar).to_contain_text("2 task items aren't To-dos yet")
    bar.get_by_role("button", name="Create 2 To-dos").click()
    expect(app.get_by_role("dialog", name="Create To-dos from Standup")).to_be_visible()
    tools = app.locator(".entity-tools")
    expect(tools.get_by_role("button", name="Create 2 To-dos")).to_have_count(0)


def test_the_preview_is_a_table_of_parsed_rows(app: Page, server: AppState, root: Path):
    put(root, "people/alice-smith.md", ALICE)
    put(root, "projects/data-migration.md", "---\ntitle: Data Migration\nstatus: active\n---\n")
    body = "- [ ] Draft plan @alice due:2026-11-20\n  For Q1\n- [ ] Call vendor\n"
    put(root, NOTE, f"---\ntitle: Standup\nabout: data-migration\n---\n{body}")
    app.goto(f"{origin(server)}/#/e/standup")
    app.locator(".capture-bar").get_by_role("button", name="Create 2 To-dos").click()

    dialog = app.get_by_role("dialog", name="Create To-dos from Standup")
    expect(dialog.get_by_role("heading", name="Create 2 To-dos")).to_be_visible()
    expect(dialog).to_contain_text("each gets source: standup")
    expect(dialog).to_contain_text("about pre-filled from the Note's one Project")
    headers = dialog.get_by_role("columnheader")
    expect(headers).to_have_text(["To-do", "Owner", "Requester", "Due", "About"])

    draft = dialog.get_by_role("row").filter(has_text="Draft plan")
    expect(draft.get_by_role("cell")).to_have_text(
        ["", "Draft plan body: For Q1", "AS Alice Smith", "AL Me", "Fri 20 Nov", "Data Migration"]
    )
    call = dialog.get_by_role("row").filter(has_text="Call vendor")
    expect(call.get_by_role("cell")).to_have_text(
        ["", "Call vendor", "AL Me", "AL Me", "—", "Data Migration"]
    )
    expect(dialog).to_contain_text("on confirm each item in the Note becomes - [ ] [[todo-id]]")


def test_an_error_row_blocks_until_its_owner_is_picked(app: Page, server: AppState, root: Path):
    put(root, "people/alice-smith.md", ALICE)
    put(root, NOTE, "---\ntitle: Standup\n---\n- [ ] Draft plan @alice\n- [ ] Review @zz\n")
    app.goto(f"{origin(server)}/#/e/standup")
    app.locator(".capture-bar").get_by_role("button", name="Create 2 To-dos").click()
    dialog = app.get_by_role("dialog", name="Create To-dos from Standup")

    bad = dialog.locator(".capture-row.has-errors")
    expect(bad).to_contain_text("No Person matches @zz — pick an Owner or untick")
    expect(bad.locator(".capture-row-error code")).to_have_text("@zz")
    owner = bad.get_by_role("combobox", name="Owner of Review")
    expect(owner).to_have_attribute("placeholder", "@zz")
    expect(dialog).to_contain_text("Fix or untick 1 row to continue")
    expect(dialog.get_by_role("button", name="Create 2 To-dos")).to_be_disabled()

    owner.fill("ali")
    dialog.get_by_role("option", name="Alice Smith").click()
    expect(dialog.locator(".capture-row.has-errors")).to_have_count(0)
    expect(dialog.get_by_role("button", name="Owner of Review")).to_contain_text("Alice Smith")
    expect(dialog).not_to_contain_text("to continue")
    dialog.get_by_role("button", name="Create 2 To-dos").click()
    expect(dialog).to_be_hidden()
    assert "owner: alice-smith" in (root / "todos/2026-11-12-review.md").read_text("utf-8")


def test_a_cell_opens_its_editor_on_click(app: Page, server: AppState, root: Path):
    put(root, NOTE, "---\ntitle: Standup\n---\n- [ ] Call vendor\n")
    app.goto(f"{origin(server)}/#/e/standup")
    app.locator(".capture-bar").get_by_role("button", name="Create 1 To-do").click()
    dialog = app.get_by_role("dialog", name="Create To-dos from Standup")

    dialog.get_by_role("button", name="Due of Call vendor").click()
    due = dialog.get_by_label("Due of Call vendor")
    expect(due).to_be_focused()
    due.fill("2026-12-01")
    due.blur()
    expect(dialog.get_by_role("button", name="Due of Call vendor")).to_have_text("Tue 1 Dec")
    dialog.get_by_role("button", name="Create 1 To-do").click()
    expect(dialog).to_be_hidden()
    assert "due: 2026-12-01" in (root / "todos/2026-11-12-call-vendor.md").read_text("utf-8")
