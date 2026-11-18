"""SPEC §9 Acceptance and §6.4: the Ctrl-K palette and the search page."""

from pathlib import Path

from playwright.sync_api import Page, expect

from memex.web.app import AppState
from tests.e2e.conftest import origin
from tests.e2e.test_editor import put

PROJECT = "---\ntitle: Data migration\nstatus: active\n---\nMove the warehouse.\n"


def test_ctrl_k_finds_a_project_and_enter_opens_its_page(app: Page, server: AppState, root: Path):
    put(root, "projects/data-migration.md", PROJECT)
    app.keyboard.press("Control+k")
    box = app.get_by_label("Search or run a command")
    box.fill("dmig")
    expect(app.get_by_role("option", name="Data migration")).to_be_visible()

    box.press("Enter")

    expect(app).to_have_url(f"{origin(server)}/#/e/data-migration")
    expect(app.get_by_role("dialog", name="Command palette")).to_have_count(0)


def test_plus_in_ctrl_k_previews_and_creates_a_todo(app: Page, server: AppState):
    app.keyboard.press("Control+k")
    box = app.get_by_label("Search or run a command")
    box.fill("+Buy milk due:2026-12-01")
    expect(app.get_by_role("option", name="Buy milk")).to_be_visible()

    box.press("Enter")

    app.goto(f"{origin(server)}/#/todos/mine")
    expect(app.get_by_role("link", name="Buy milk")).to_be_visible()


def test_see_all_opens_the_search_page_with_chips_and_counts(
    app: Page, server: AppState, root: Path
):
    put(root, "projects/data-migration.md", PROJECT)
    put(root, "notes/standup.md", "# Standup\n\nThe warehouse move slipped.\n")
    app.keyboard.press("Control+k")
    app.get_by_label("Search or run a command").fill("warehouse")
    app.get_by_role("option", name="See all results for 'warehouse'").click()

    expect(app.locator(".result")).to_have_count(2)
    app.get_by_role("button", name="Note 1").click()

    expect(app.locator(".result")).to_have_count(1)
    expect(app.locator(".filter-chip", has_text="type:note")).to_be_visible()
    expect(app.locator(".result mark", has_text="warehouse")).to_be_visible()


def test_two_type_chips_widen_one_filter(app: Page, server: AppState, root: Path):
    put(root, "projects/data-migration.md", PROJECT)
    put(root, "notes/standup.md", "# Standup\n\nThe warehouse move slipped.\n")
    app.goto(f"{origin(server)}/#/search?q=warehouse")
    expect(app.locator(".result")).to_have_count(2)

    app.get_by_label("Add Type filter").select_option("note")
    expect(app.locator(".result")).to_have_count(1)
    app.get_by_label("Add Type filter").select_option("project")

    expect(app.locator(".filter-chip", has_text="type:note,project")).to_be_visible()
    expect(app.locator(".result")).to_have_count(2)


CUTOVER = (
    "---\ntitle: Cutover runbook\nproject: data-migration\nstatus: active\n"
    "lead: ada-lovelace\ndue: 2026-11-15\n---\nRollback tested before the cutover window.\n"
)
DRY_RUN = (
    "---\ntitle: Book the cutover dry-run\nowner: ada-lovelace\nrequester: ada-lovelace\n"
    "status: done\ncompleted: 2026-11-06\n---\n"
)


def test_palette_rows_bold_the_query_and_name_the_type(app: Page, server: AppState, root: Path):
    put(root, "projects/data-migration.md", PROJECT)
    put(root, "deliverables/cutover-runbook.md", CUTOVER)
    app.keyboard.press("Control+k")
    app.get_by_label("Search or run a command").fill("cutover")

    row = app.get_by_role("option", name="Cutover runbook")
    expect(row.locator("mark")).to_have_text("Cutover")
    expect(row).to_contain_text("Deliverable · Data migration")
    expect(row).to_have_attribute("aria-selected", "true")
    dialog = app.get_by_role("dialog", name="Command palette")
    expect(dialog.locator(".palette-keys")).to_contain_text("new tab")

    app.keyboard.press("Escape")
    expect(dialog).to_have_count(0)


def test_search_page_counts_by_type_and_demotes_done_work(app: Page, server: AppState, root: Path):
    put(root, "projects/data-migration.md", PROJECT)
    put(root, "deliverables/cutover-runbook.md", CUTOVER)
    put(root, "todos/2026-11-01-book-the-cutover-dry-run.md", DRY_RUN)
    put(root, "notes/steering.md", "---\ntitle: Steering\ndate: 2026-11-16\n---\nThe cutover.\n")
    app.goto(f"{origin(server)}/#/search?q=cutover")

    expect(app.get_by_role("heading", name="3 results for \u2018cutover\u2019")).to_be_visible()
    runbook = app.locator(".result", has_text="Cutover runbook")
    expect(runbook).to_contain_text("Data migration · lead Me · due 15 Nov")
    steering = app.locator(".result", has_text="Steering")
    expect(steering).to_contain_text("notes/ · Mon 16 Nov")
    expect(steering.locator(".result-snippet mark")).to_have_text("cutover")
    done = app.locator(".result", has_text="Book the cutover dry-run")
    expect(done).to_have_class("result finished")
    expect(done.locator(".result-status")).to_have_text("Done")
    expect(done).to_contain_text("Me → Me · completed 6 Nov")

    app.get_by_role("button", name="To-do 1").click()
    expect(app.locator(".result")).to_have_count(1)
    expect(app.get_by_role("button", name="Note 1")).to_be_visible()
    app.get_by_role("button", name="All 3").click()
    expect(app.locator(".result")).to_have_count(3)
    expect(app.locator(".filter-chip")).to_have_count(0)
