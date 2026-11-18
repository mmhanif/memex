"""SPEC §10: the Bookmarks and Glossary pages."""

import re
from pathlib import Path

from playwright.sync_api import Page, expect

from memex.web.app import AppState
from tests.e2e.conftest import origin
from tests.e2e.test_editor import put


def test_add_a_bookmark_then_filter_by_its_label(app: Page, server: AppState, root: Path):
    put(root, "bookmarks.md", "# Work\n- [Jira](https://j.example) #eng\n")
    app.goto(f"{origin(server)}/#/bookmarks")
    view = app.get_by_role("main")  # the sidebar lists Bookmarks too
    expect(view.get_by_role("link", name="Jira")).to_be_visible()
    expect(app.get_by_text("Work", exact=True)).to_be_visible()

    form = app.get_by_role("form", name="Add a Bookmark")
    form.get_by_label("URL").fill("https://w.example")
    form.get_by_label("Title").fill("Wiki")
    form.get_by_label("Note").fill("team wiki")
    form.get_by_label("Labels").fill("ref")
    form.get_by_role("button", name="Add").click()

    wiki = view.get_by_role("link", name="Wiki")
    expect(wiki).to_have_attribute("target", "_blank")
    expect(wiki).to_have_attribute("rel", "noopener noreferrer")
    assert (
        (root / "bookmarks.md").read_text().endswith("- [Wiki](https://w.example) team wiki #ref\n")
    )

    app.get_by_role("group", name="Label filter").get_by_role("button", name="#ref").click()
    expect(view.get_by_role("link", name="Wiki")).to_be_visible()
    expect(view.get_by_role("link", name="Jira")).to_have_count(0)


def test_glossary_lists_terms_with_aliases_and_definitions(app: Page, server: AppState, root: Path):
    put(root, "glossary/slo.md", "---\ntitle: SLO\naliases: [SLOs]\n---\nThe **uptime** target.\n")
    app.goto(f"{origin(server)}/#/glossary")

    expect(app.get_by_role("heading", name="S", exact=True)).to_be_visible()
    expect(app.get_by_role("link", name="SLO", exact=True)).to_have_attribute("href", "#/e/slo")
    expect(app.get_by_text("aka SLOs")).to_be_visible()
    expect(app.locator(".glossary-group strong", has_text="uptime")).to_be_visible()


def test_glossary_redesign_strip_eyebrow_refs_and_new_term(app: Page, server: AppState, root: Path):
    put(root, "projects/data-migration.md", "---\ntitle: Data Migration\nstatus: active\n---\n")
    put(
        root,
        "glossary/cutover.md",
        "---\ntitle: Cutover\naliases: [go-live, switchover]\n---\n"
        "The window owned by [[data-migration]].\n",
    )
    put(root, "glossary/toil.md", "---\ntitle: Toil\n---\nRepetitive work.\n")
    app.goto(f"{origin(server)}/#/glossary")
    view = app.get_by_role("main")

    expect(view.get_by_text("2 Terms · 2 aliases")).to_be_visible()
    expect(view.get_by_text("aka go-live · switchover")).to_be_visible()
    expect(view.get_by_role("link", name="Data Migration")).to_have_attribute(
        "href", "#/e/data-migration"
    )

    # The A-Z strip: every letter, the ones with Terms jump, the rest are faded text.
    letters = view.get_by_role("navigation", name="Letters")
    expect(letters.get_by_role("link")).to_have_text(["C", "T"])
    expect(letters.get_by_text("A", exact=True)).to_have_attribute("aria-disabled", "true")
    expect(letters.locator("> *")).to_have_count(26)

    # Letter groups are outline heading blocks; each Term is a block under its letter.
    expect(view.locator(".block-heading h2", has_text="T")).to_be_visible()
    expect(view.locator("#glossary-T .block-children .block")).to_have_count(1)

    view.get_by_role("button", name="Term").click()
    expect(app.get_by_role("dialog")).to_contain_text("Glossary Term")


def test_bookmarks_redesign_sections_counts_and_domains(app: Page, server: AppState, root: Path):
    put(
        root,
        "bookmarks.md",
        "# Ops\n- [Grafana](https://grafana.internal/d/x) SLO panels #ops #slo\n"
        "- [Rota](https://pagerduty.example/r) #ops\n"
        "## Vendors\nAsk Theo before sharing.\n- https://status.ledgerco.example\n",
    )
    app.goto(f"{origin(server)}/#/bookmarks")
    view = app.get_by_role("main")

    expect(view.get_by_text("3 Bookmarks")).to_be_visible()
    chips = view.get_by_role("group", name="Label filter").get_by_role("button")
    expect(chips).to_have_text(["All3", "#ops2", "#slo1"])
    expect(chips.first).to_have_attribute("aria-pressed", "true")

    ops = view.locator(".block-heading", has=app.get_by_role("heading", name="Ops"))
    expect(ops.get_by_role("link", name="Grafana")).to_be_visible()
    expect(ops.get_by_text("grafana.internal", exact=True)).to_be_visible()
    vendors = view.locator(".block-heading", has=app.get_by_role("heading", name="Vendors"))
    expect(vendors.get_by_text("Ask Theo before sharing.")).to_be_visible()
    bare = vendors.get_by_role("link", name="https://status.ledgerco.example")
    expect(bare).to_have_class(re.compile(r"\bmono\b"))

    form = view.get_by_role("form", name="Add a Bookmark")
    expect(form).to_have_class(re.compile(r"\bwell\b"))
