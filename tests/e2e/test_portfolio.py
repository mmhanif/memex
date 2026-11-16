"""SPEC §11.3 and §11 Acceptance: the Portfolio board and outline."""

from pathlib import Path

from playwright.sync_api import Page, expect

from memex.web.app import AppState
from tests.e2e.conftest import origin
from tests.e2e.test_editor import put, wait_for_disk

PROJECT = "---\ntitle: Data migration\ntheme: platform\nstatus: active\n---\n"


def test_clicking_a_status_on_a_board_card_moves_it(app: Page, server: AppState, root: Path):
    put(root, "themes/platform.md", "---\ntitle: Platform\n---\n")
    put(root, "projects/data-migration.md", PROJECT)
    app.goto(f"{origin(server)}/#/portfolio/board")
    active = app.get_by_role("region", name="active")
    expect(active.locator(".card", has_text="Data migration")).to_be_visible()

    app.get_by_label("Status of Data migration").select_option("blocked")

    blocked = app.get_by_role("region", name="blocked")
    expect(blocked.locator(".card", has_text="Data migration")).to_be_visible()
    expect(active.locator(".card", has_text="Data migration")).to_have_count(0)
    wait_for_disk(root / "projects/data-migration.md", PROJECT.replace("active", "blocked"))


def test_theme_chips_filter_the_board(app: Page, server: AppState, root: Path):
    put(root, "themes/platform.md", "---\ntitle: Platform\n---\n")
    put(root, "projects/data-migration.md", PROJECT)
    put(root, "projects/loose.md", "---\ntitle: Loose end\nstatus: active\n---\n")
    app.goto(f"{origin(server)}/#/portfolio/board")
    expect(app.locator(".card", has_text="Loose end")).to_be_visible()

    app.get_by_role("button", name="Platform").click()

    expect(app.locator(".card", has_text="Loose end")).to_have_count(0)
    expect(app.locator(".card", has_text="Data migration")).to_be_visible()
    # The filter is in the route, so it survives switching to the outline.
    expect(app).to_have_url(f"{origin(server)}/#/portfolio/board?themes=platform")
    app.get_by_role("link", name="Outline").click()
    expect(app.get_by_role("button", name="Platform")).to_have_attribute("aria-pressed", "true")
    expect(app.get_by_role("row", name="Loose end")).to_have_count(0)


def test_outline_creates_a_deliverable_inline_and_edits_due(
    app: Page, server: AppState, root: Path
):
    put(root, "themes/platform.md", "---\ntitle: Platform\n---\n")
    put(root, "projects/data-migration.md", PROJECT)
    app.goto(f"{origin(server)}/#/portfolio/outline")

    box = app.get_by_label("New Deliverable in Data migration")
    box.fill("Cutover")
    box.press("Enter")

    # The new row's link, not the create row (whose box held "Cutover" until the write).
    expect(app.get_by_role("link", name="Cutover", exact=True)).to_be_visible()
    text = (root / "deliverables/cutover.md").read_text("utf-8")
    assert "project: data-migration" in text

    app.get_by_label("Due of Data migration").fill("2026-12-01")
    wait_for_disk(
        root / "projects/data-migration.md",
        PROJECT.replace("status: active\n", "status: active\ndue: 2026-12-01\n"),
    )
