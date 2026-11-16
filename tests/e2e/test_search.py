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
