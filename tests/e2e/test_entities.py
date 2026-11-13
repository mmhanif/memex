"""SPEC §7, §11.5, §16.7: creating Entities and the Entity page against a real server."""

from pathlib import Path

from playwright.sync_api import Page, expect

from memex.web.app import AppState
from tests.e2e.conftest import origin
from tests.e2e.test_editor import put, wait_for_disk


def test_create_a_project_from_the_new_form_and_see_it_on_its_page(
    app: Page, server: AppState, root: Path
):
    app.get_by_role("button", name="New…").click()
    app.get_by_role("menuitem", name="Project").click()
    dialog = app.get_by_role("dialog", name="New Project")
    expect(dialog.get_by_label("Template")).to_have_value("project/project")
    dialog.get_by_label("Title").fill("Data migration")
    dialog.get_by_label("Status *").select_option("active")
    dialog.get_by_role("button", name="Create").click()

    expect(app).to_have_url(f"{origin(server)}/#/e/data-migration")
    expect(app.get_by_label("Title")).to_have_value("Data migration")
    expect(app.locator(".entity-body h2", has_text="Goal")).to_be_visible()
    text = (root / "projects/data-migration.md").read_text("utf-8")
    assert "status: active" in text
    assert "created: 2026-11-12" in text


def test_edit_a_project_body_and_it_auto_saves(app: Page, server: AppState, root: Path):
    rel = "projects/data-migration.md"
    put(root, rel, "---\ntitle: Data migration\nstatus: active\n---\nOld\n")
    app.goto(f"{origin(server)}/#/e/data-migration")

    app.get_by_role("button", name="Edit").click()
    app.get_by_label("Body text").fill("New text\n")

    expect(app.locator(".save-status")).to_have_text("Saved", timeout=5000)
    wait_for_disk(root / rel, "---\ntitle: Data migration\nstatus: active\n---\nNew text\n")


def test_a_status_edit_on_the_properties_card_is_written_to_disk(
    app: Page, server: AppState, root: Path
):
    rel = "projects/data-migration.md"
    put(root, rel, "---\ntitle: Data migration\nstatus: active\n---\nBody\n")
    app.goto(f"{origin(server)}/#/e/data-migration")

    app.get_by_label("Status").select_option("blocked")

    wait_for_disk(root / rel, "---\ntitle: Data migration\nstatus: blocked\n---\nBody\n")


def test_mentions_link_to_their_entity_and_broken_ones_are_flagged(
    app: Page, server: AppState, root: Path
):
    put(root, "notes/standup.md", "We met [[ada-lovelace]] and [[ghost]].\n")
    app.goto(f"{origin(server)}/#/e/standup")

    expect(app.locator(".markdown a.mention", has_text="Ada Lovelace")).to_have_attribute(
        "href", "#/e/ada-lovelace"
    )
    expect(app.locator(".markdown a.mention.broken")).to_have_text("ghost")
    expect(app.locator(".banner", has_text="Broken references")).to_contain_text("ghost")
