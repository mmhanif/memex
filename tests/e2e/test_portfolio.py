"""SPEC §11.3 and §11 Acceptance: the Portfolio board and outline."""

from pathlib import Path

from playwright.sync_api import Page, expect

from memex.web.app import AppState
from tests.e2e.conftest import origin
from tests.e2e.test_editor import put, wait_for_disk

PROJECT = "---\ntitle: Data migration\ntheme: platform\nstatus: active\n---\n"


def portfolio(app: Page, server: AppState, view: str) -> None:
    """The Portfolio on the e2e clock's day, Thursday 12 November 2026, in the browser too."""
    app.clock.set_fixed_time("2026-11-12T10:00:00")
    app.goto(f"{origin(server)}/#/portfolio/{view}")
    app.reload()


def test_clicking_a_status_on_a_board_card_moves_it(app: Page, server: AppState, root: Path):
    put(root, "themes/platform.md", "---\ntitle: Platform\n---\n")
    put(root, "projects/data-migration.md", PROJECT)
    app.goto(f"{origin(server)}/#/portfolio/board")
    active = app.get_by_role("region", name="active")
    expect(active.locator(".card", has_text="Data migration")).to_be_visible()

    app.get_by_role("button", name="Status of Data migration").click()
    menu = app.get_by_role("menu", name="Status of Data migration")
    expect(menu.get_by_role("menuitemradio", name="Active")).to_have_attribute(
        "aria-checked", "true"
    )
    expect(menu.get_by_role("menuitemradio")).to_have_count(6)  # Cancelled too: it hides the card
    menu.get_by_role("menuitemradio", name="Blocked").click()

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

    app.get_by_role("button", name="Edit Due of Data migration").click()
    app.get_by_label("Due of Data migration", exact=True).fill("2026-12-01")
    wait_for_disk(
        root / "projects/data-migration.md",
        PROJECT.replace("status: active\n", "status: active\ndue: 2026-12-01\n"),
    )


def test_board_columns_and_cards_show_status_lead_due_and_late_deliverables(
    app: Page, server: AppState, root: Path
):
    put(root, "themes/platform.md", "---\ntitle: Platform\n---\n")
    put(root, "people/alice-smith.md", "---\ntitle: Alice Smith\nkind: [team-member]\n---\n")
    put(
        root,
        "projects/data-migration.md",
        "---\ntitle: Data migration\ntheme: platform\nstatus: active\nlead: alice-smith\n"
        "due: 2026-11-16\n---\n",
    )
    put(root, "projects/loose.md", "---\ntitle: Loose end\nstatus: done\ndue: 2026-12-01\n---\n")
    put(
        root,
        "deliverables/cutover.md",
        "---\ntitle: Cutover\nproject: data-migration\nstatus: active\ndue: 2026-11-10\n---\n",
    )
    put(
        root,
        "deliverables/export.md",
        "---\ntitle: Export\nproject: data-migration\nstatus: blocked\n---\n",
    )
    portfolio(app, server, "board")

    expect(app.locator(".portfolio-head .eyebrow")).to_have_text(
        "2 Projects · 0 blocked · 1 due this week"
    )
    expect(app.locator(".board-column h2")).to_have_text(
        ["Not started 0", "Active 1", "On hold 0", "Blocked 0", "Done 1"]
    )
    card = app.locator(".board-card", has_text="Data migration")
    expect(card.locator(".card-parent")).to_have_text("Platform")
    expect(card.locator(".card-attention li")).to_have_text(["Cutover 2d late", "Export blocked"])
    expect(card.locator(".card-due")).to_have_text("Mon 16 Nov")
    expect(card.locator(".card-due.soon")).to_have_count(1)
    expect(card.locator(".avatar")).to_have_text("AS")
    expect(app.locator(".board-card.finished", has_text="Loose end")).to_be_visible()


def test_no_theme_chip_filters_to_work_without_a_theme(app: Page, server: AppState, root: Path):
    put(root, "themes/platform.md", "---\ntitle: Platform\n---\n")
    put(root, "projects/data-migration.md", PROJECT)
    put(root, "projects/loose.md", "---\ntitle: Loose end\nstatus: active\n---\n")
    app.goto(f"{origin(server)}/#/portfolio/board")
    all_chip = app.get_by_role("button", name="All", exact=True)
    expect(all_chip).to_have_attribute("aria-pressed", "true")

    app.get_by_role("button", name="No theme").click()

    expect(app.locator(".card", has_text="Data migration")).to_have_count(0)
    expect(app.locator(".card", has_text="Loose end")).to_be_visible()
    expect(app).to_have_url(f"{origin(server)}/#/portfolio/board?themes=-")
    all_chip.click()
    expect(app.locator(".card", has_text="Data migration")).to_be_visible()


def test_outline_shows_cells_until_one_is_clicked_to_edit(app: Page, server: AppState, root: Path):
    put(root, "themes/platform.md", "---\ntitle: Platform\n---\n")
    put(
        root,
        "deliverables/cutover.md",
        "---\ntitle: Cutover\nproject: data-migration\nstatus: blocked\ndue: 2026-11-10\n---\n",
    )
    put(root, "projects/data-migration.md", PROJECT)
    portfolio(app, server, "outline")

    theme = app.get_by_role("row", name="Platform")
    expect(theme).to_contain_text("Theme · 1 Project")
    row = app.get_by_role("row", name="Cutover")
    expect(row.locator(".cell-due")).to_have_text("10 Nov2 days late")
    expect(row.get_by_role("button", name="Status of Cutover")).to_have_text("Blocked")

    # Status edits through the same menu as the board.
    row.get_by_role("button", name="Status of Cutover").click()
    app.get_by_role("menuitemradio", name="Active").click()
    expect(row.get_by_role("button", name="Status of Cutover")).to_have_text("Active")

    # Collapsing a Project counts its Deliverables instead.
    app.get_by_role("button", name="Collapse Data migration").click()
    expect(app.get_by_role("row", name="Cutover")).to_have_count(0)
    expect(app.get_by_role("row", name="Data migration")).to_contain_text("1 Deliverable")


def test_outline_edits_a_themes_lead_in_place(app: Page, server: AppState, root: Path):
    theme = "---\ntitle: Platform\n---\n"
    put(root, "themes/platform.md", theme)
    put(root, "people/alice-smith.md", "---\ntitle: Alice Smith\n---\n")
    put(root, "projects/data-migration.md", PROJECT)
    portfolio(app, server, "outline")

    row = app.get_by_role("row", name="Platform")
    expect(row).to_contain_text("Theme · 1 Project")
    row.get_by_role("button", name="Edit Lead of Platform").click()
    app.get_by_label("Lead of Platform", exact=True).select_option(label="Alice Smith")
    wait_for_disk(root / "themes/platform.md", "---\ntitle: Platform\nlead: alice-smith\n---\n")
