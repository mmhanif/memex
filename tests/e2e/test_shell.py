"""SPEC §11.2: the shell's sidebar and top bar."""

from pathlib import Path

from playwright.sync_api import Page, expect

from memex.web.app import AppState
from tests.e2e.conftest import origin
from tests.e2e.test_editor import put

NAV = ["Home", "Portfolio", "People", "To-dos", "Glossary", "Bookmarks", "Files", "Settings"]


def test_sidebar_highlights_the_section_of_the_current_route(
    app: Page, server: AppState, root: Path
):
    put(root, "people/grace.md", "---\ntitle: Grace Hopper\ntype: person\n---\n")
    nav = app.get_by_role("navigation", name="Sections")
    for label in NAV:
        expect(nav.get_by_role("link", name=label, exact=True)).to_have_text(label)

    app.goto(f"{origin(server)}/#/f/people/grace.md")
    expect(nav.get_by_role("link", name="Files", exact=True)).to_have_attribute(
        "aria-current", "page"
    )

    app.goto(f"{origin(server)}/#/people/grace")
    expect(nav.get_by_role("link", name="People", exact=True)).to_have_attribute(
        "aria-current", "page"
    )
    expect(nav.get_by_role("link", name="Files", exact=True)).not_to_have_attribute(
        "aria-current", "page"
    )


def test_sidebar_lists_the_first_ten_bookmarks_then_links_to_all(
    app: Page, server: AppState, root: Path
):
    sidebar = app.get_by_role("navigation", name="Sections")
    expect(sidebar.get_by_text("No Bookmarks yet")).to_be_visible()

    lines = "".join(f"- [Site {n}](https://s{n}.example)\n" for n in range(1, 12))
    put(root, "bookmarks.md", f"# Work\n- https://bare.example\n{lines}")
    bookmarked = sidebar.get_by_role("list", name="Bookmarked")
    expect(bookmarked.get_by_role("link")).to_have_count(11)  # 10 Bookmarks + All Bookmarks
    first = bookmarked.get_by_role("link", name="Site 1", exact=True)
    expect(first).to_have_attribute("href", "https://s1.example")
    expect(first).to_have_attribute("target", "_blank")
    expect(first).to_have_attribute("rel", "noopener noreferrer")
    expect(bookmarked.get_by_role("link", name="https://bare.example")).to_be_visible()
    expect(bookmarked.get_by_role("link", name="Site 9", exact=True)).to_be_visible()
    expect(bookmarked.get_by_role("link", name="Site 10", exact=True)).to_have_count(0)
    expect(bookmarked.get_by_role("link", name="All Bookmarks →")).to_have_attribute(
        "href", "#/bookmarks"
    )


def test_recent_lists_opened_pages_newest_first_like_the_palette(
    app: Page, server: AppState, root: Path
):
    put(root, "projects/data-migration.md", "---\ntitle: Data migration\nstatus: active\n---\n")
    put(root, "people/grace.md", "---\ntitle: Grace Hopper\ntype: person\n---\n")
    sidebar = app.get_by_role("navigation", name="Sections")
    expect(sidebar.get_by_text("Nothing opened yet")).to_be_visible()

    app.goto(f"{origin(server)}/#/e/data-migration")
    expect(app.get_by_label("Title")).to_have_value("Data migration")
    app.goto(f"{origin(server)}/#/people/grace")
    recent = sidebar.get_by_role("list", name="Recent").get_by_role("link")
    expect(recent).to_have_text(["Grace Hopper", "Data migration"])
    expect(recent.first).to_have_attribute("href", "#/people/grace")

    app.keyboard.press("Control+k")
    rows = app.get_by_role("listbox", name="Results").get_by_role("option")
    expect(rows.nth(0)).to_contain_text("Grace Hopper")
    expect(rows.nth(1)).to_contain_text("Data migration")


def test_new_menu_lives_in_the_sidebar_not_the_top_bar(app: Page):
    expect(app.get_by_role("banner").get_by_role("button", name="New…")).to_have_count(0)

    sidebar = app.get_by_role("navigation", name="Sections")
    sidebar.get_by_role("button", name="New…").click()
    sidebar.get_by_role("menuitem", name="Project").click()
    expect(app.get_by_role("dialog", name="New Project")).to_be_visible()
