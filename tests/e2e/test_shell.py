"""SPEC §11.2: the shell's sidebar and top bar."""

from pathlib import Path

import pytest
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


def test_sidebar_header_names_the_workspace_folder(app: Page, root: Path):
    header = app.get_by_role("navigation", name="Sections").locator(".side-workspace")
    expect(header).to_contain_text("memex")
    expect(header).to_contain_text(root.name)


def test_todos_row_counts_mes_open_todos(app: Page, root: Path):
    todos = app.get_by_role("navigation", name="Sections").get_by_role("link", name="To-dos")
    expect(todos.locator(".side-count")).to_have_count(0)

    put(root, "todos/one.md", "---\ntitle: One\nowner: ada-lovelace\nstatus: open\n---\n")
    put(root, "todos/two.md", "---\ntitle: Two\nowner: ada-lovelace\nstatus: done\n---\n")

    expect(todos.locator(".side-count")).to_have_text("1", timeout=5000)


def test_without_me_the_badge_hides_and_the_me_banner_offers_pick_or_create(
    app: Page, server: AppState, root: Path
):
    put(root, "todos/one.md", "---\ntitle: One\nowner: ada-lovelace\nstatus: open\n---\n")
    todos = app.get_by_role("navigation", name="Sections").get_by_role("link", name="To-dos")
    expect(todos.locator(".side-count")).to_have_text("1", timeout=5000)

    put(root, ".memex/config.yaml", "format: 1\nme: jordan-lee\n")

    banner = app.locator(".banner-strip .banner", has_text="Me isn't set")
    expect(banner).to_contain_text("me: jordan-lee matches no Person", timeout=5000)
    expect(todos.locator(".side-count")).to_have_count(0)
    banner.get_by_role("button", name="Create Person").click()
    form = app.get_by_role("dialog", name="New Person")
    form.get_by_role("button", name="Cancel").click()
    banner.get_by_role("link", name="Pick a Person").click()
    expect(app).to_have_url(f"{origin(server)}/#/settings")


def test_config_error_banner_gives_the_line_and_opens_the_config(
    app: Page, server: AppState, root: Path
):
    put(root, ".memex/config.yaml", "format: 1\nme: ada-lovelace\nignore: [\n")

    banner = app.locator(".banner-strip .banner", has_text="Workspace config won't parse")
    expect(banner).to_contain_text("(line ", timeout=5000)
    banner.get_by_role("link", name="Open config.yaml").click()
    expect(app.locator(".editor-path")).to_have_text(".memex/config.yaml")


def test_back_and_forward_walk_the_history(app: Page, server: AppState):
    bar = app.get_by_role("banner")
    nav = app.get_by_role("navigation", name="Sections")
    nav.get_by_role("link", name="People", exact=True).click()
    nav.get_by_role("link", name="Glossary", exact=True).click()

    bar.get_by_role("button", name="Back").click()
    expect(app).to_have_url(f"{origin(server)}/#/people")
    bar.get_by_role("button", name="Forward").click()
    expect(app).to_have_url(f"{origin(server)}/#/glossary")


def test_n_opens_the_new_menu_except_while_typing(app: Page, root: Path):
    sidebar = app.get_by_role("navigation", name="Sections")
    app.keyboard.press("n")
    expect(sidebar.get_by_role("menuitem", name="Project")).to_be_visible()
    app.keyboard.press("Escape")
    expect(sidebar.get_by_role("menuitem", name="Project")).to_have_count(0)

    put(root, "notes/a.md", "# A\n")
    app.goto(app.url.split("#")[0] + "#/f/notes/a.md")
    app.get_by_label("File text").press("n")
    expect(sidebar.get_by_role("menuitem", name="Project")).to_have_count(0)


def test_save_status_and_file_banners_live_in_the_shell(app: Page, server: AppState, root: Path):
    bar = app.get_by_role("banner")
    expect(bar.locator(".save-status")).to_have_count(0)  # nothing open to save

    put(root, "notes/a.md", "---\ntitle: Alpha\n---\n# A\n")
    app.goto(f"{origin(server)}/#/f/notes/a.md")
    expect(bar.locator(".save-status")).to_have_text("Saved")
    expect(app.locator(".save-status")).to_have_count(1)

    put(root, "notes/a.md", "---\ntitle: Alpha\n---\n# Outside\n")
    app.get_by_label("File text").fill("# Mine\n")
    banner = app.locator(".banner-strip .banner.conflict")
    expect(banner).to_contain_text("Alpha changed on disk", timeout=5000)
    expect(bar.locator(".save-status")).to_have_text("Not saved")


def test_n_does_nothing_while_a_dialog_is_open(app: Page):
    app.keyboard.press("Control+k")
    palette = app.get_by_role("dialog", name="Command palette")
    expect(palette).to_be_visible()
    app.locator("body").evaluate("el => document.activeElement.blur()")
    app.keyboard.press("n")
    sidebar = app.get_by_role("navigation", name="Sections")
    expect(sidebar.get_by_role("menuitem", name="Project")).to_have_count(0)


LOCKED = {
    "status": 503,
    "content_type": "application/json",
    "body": '{"error": {"code": "locked", "message": "notes/a.md is locked by another program"}}',
}


def test_a_locked_save_pauses_auto_save_until_retry_and_gives_way_to_a_conflict(
    app: Page, server: AppState, root: Path
):
    put(root, "notes/a.md", "---\ntitle: Alpha\n---\n# A\n")
    app.goto(f"{origin(server)}/#/f/notes/a.md")
    expect(app.get_by_role("banner").locator(".save-status")).to_have_text("Saved")
    puts: list[str] = []
    app.on("request", lambda r: puts.append(r.url) if r.method == "PUT" else None)
    app.route(
        "**/api/files",
        lambda r: r.fulfill(**LOCKED) if r.request.method == "PUT" else r.continue_(),
    )

    text = app.get_by_label("File text")
    text.fill("---\ntitle: Alpha\n---\n# Mine\n")
    banner = app.locator(".banner-strip .banner", has_text="Couldn't save Alpha")
    expect(banner).to_contain_text("another program has the file open", timeout=5000)
    expect(banner.locator(".icon-lock")).to_have_count(1)
    attempts = len(puts)
    text.press("End")
    text.type(" more")
    app.wait_for_timeout(1500)  # auto-save is paused: typing doesn't retry
    assert len(puts) == attempts

    put(root, "notes/a.md", "---\ntitle: Alpha\n---\n# Outside\n")
    banner.get_by_role("button", name="Retry").click()  # the PUT is still refused...
    expect(banner).to_be_visible()
    app.unroute("**/api/files")
    app.evaluate("window.dispatchEvent(new Event('focus'))")  # ...then the recheck finds a conflict
    expect(app.locator(".banner-strip .banner.conflict")).to_be_visible(timeout=5000)
    expect(banner).to_have_count(0)


class TestReadOnly:
    @pytest.fixture
    def root(self, root: Path) -> Path:
        config = root / ".memex/config.yaml"
        config.write_text(config.read_text().replace("format: 1", "format: 2"))
        return root

    def test_read_only_banner_names_both_formats_and_the_upgrade(self, app: Page):
        banner = app.locator(".banner-strip .banner.neutral")
        expect(banner).to_contain_text("This Workspace is format 2")
        expect(banner).to_contain_text("understands format 1")
        expect(banner).to_contain_text("pipx upgrade memex")
