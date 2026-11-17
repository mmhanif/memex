"""SPEC §10: the Bookmarks and Glossary pages."""

from pathlib import Path

from playwright.sync_api import Page, expect

from memex.web.app import AppState
from tests.e2e.conftest import origin
from tests.e2e.test_editor import put


def test_add_a_bookmark_then_filter_by_its_label(app: Page, server: AppState, root: Path):
    put(root, "bookmarks.md", "# Work\n- [Jira](https://j.example) #eng\n")
    app.goto(f"{origin(server)}/#/bookmarks")
    expect(app.get_by_role("link", name="Jira")).to_be_visible()
    expect(app.get_by_text("Work", exact=True)).to_be_visible()

    form = app.get_by_role("form", name="Add a Bookmark")
    form.get_by_label("URL").fill("https://w.example")
    form.get_by_label("Title").fill("Wiki")
    form.get_by_label("Note").fill("team wiki")
    form.get_by_label("Labels").fill("ref")
    form.get_by_role("button", name="Add").click()

    wiki = app.get_by_role("link", name="Wiki")
    expect(wiki).to_have_attribute("target", "_blank")
    expect(wiki).to_have_attribute("rel", "noopener noreferrer")
    assert (
        (root / "bookmarks.md").read_text().endswith("- [Wiki](https://w.example) team wiki #ref\n")
    )

    app.get_by_role("group", name="Label filter").get_by_role("button", name="#ref").click()
    expect(app.get_by_role("link", name="Wiki")).to_be_visible()
    expect(app.get_by_role("link", name="Jira")).to_have_count(0)


def test_glossary_lists_terms_with_aliases_and_definitions(app: Page, server: AppState, root: Path):
    put(root, "glossary/slo.md", "---\ntitle: SLO\naliases: [SLOs]\n---\nThe **uptime** target.\n")
    app.goto(f"{origin(server)}/#/glossary")

    expect(app.get_by_role("heading", name="S", exact=True)).to_be_visible()
    expect(app.get_by_role("link", name="SLO", exact=True)).to_have_attribute("href", "#/e/slo")
    expect(app.get_by_text("Also: SLOs")).to_be_visible()
    expect(app.locator(".glossary-group strong", has_text="uptime")).to_be_visible()
