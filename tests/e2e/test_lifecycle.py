"""SPEC §5.5, §8, §16.7 journey 7: Rename id, delete and trash against a real server."""

from pathlib import Path

from playwright.sync_api import Page, expect

from memex.web.app import AppState
from tests.e2e.conftest import origin
from tests.e2e.test_editor import put, wait_for_disk


def test_rename_id_from_the_entity_page_previews_then_lands_on_the_new_route(
    app: Page, server: AppState, root: Path
):
    put(root, "projects/dmig.md", "---\ntitle: Data migration\nstatus: active\n---\n")
    put(root, "notes/sync.md", "---\nabout: [dmig]\n---\nSee [[dmig]].\n")
    app.goto(f"{origin(server)}/#/e/dmig")

    app.get_by_role("button", name="Actions").click()
    app.get_by_role("menuitem", name="Rename id…").click()
    dialog = app.get_by_role("dialog", name="Rename id of Data migration")
    dialog.get_by_label("New Id").fill("data-migration")
    dialog.get_by_role("button", name="Preview").click()
    expect(dialog).to_contain_text("This updates 2 references in 1 file")
    dialog.get_by_role("button", name="Rename").click()

    expect(app).to_have_url(f"{origin(server)}/#/e/data-migration")
    expect(app.get_by_label("Title")).to_have_value("Data migration")
    assert (root / "projects/data-migration.md").exists()
    wait_for_disk(
        root / "notes/sync.md", "---\nabout: [data-migration]\n---\nSee [[data-migration]].\n"
    )


def test_delete_with_replace_then_restore_from_trash(app: Page, server: AppState, root: Path):
    put(root, "themes/old.md", "---\ntitle: Old theme\n---\n")
    put(root, "themes/new.md", "---\ntitle: New theme\n---\n")
    put(root, "projects/p.md", "---\ntitle: P\nstatus: active\ntheme: old\n---\n")
    app.goto(f"{origin(server)}/#/e/old")

    app.get_by_role("button", name="Actions").click()
    app.get_by_role("menuitem", name="Delete…").click()
    dialog = app.get_by_role("dialog", name="Delete Old theme")
    expect(dialog).to_contain_text("This updates 1 reference in 1 file")
    dialog.get_by_label("Replacement").select_option("new")
    dialog.get_by_role("button", name="Delete").click()

    expect(app).to_have_url(f"{origin(server)}/#/home")
    wait_for_disk(root / "projects/p.md", "---\ntitle: P\nstatus: active\ntheme: new\n---\n")
    assert not (root / "themes/old.md").exists()

    app.goto(f"{origin(server)}/#/trash")
    app.get_by_role("group", name="themes/old.md").get_by_role("button", name="Restore").click()
    expect(app.get_by_text("The trash is empty.")).to_be_visible()
    assert (root / "themes/old.md").exists()


def test_an_entity_pages_broken_reference_is_repaired_inline_after_a_preview(
    app: Page, server: AppState, root: Path
):
    put(root, "projects/p.md", "---\ntitle: P\nstatus: active\nteam: [zed]\n---\nAsk [[zed]].\n")
    app.goto(f"{origin(server)}/#/e/p")

    group = app.get_by_role("article", name="Broken reference zed")
    group.get_by_role("button", name="Remove").click()
    expect(group).to_contain_text("This updates 2 references in 1 file")
    group.get_by_role("button", name="Remove", exact=True).click()

    wait_for_disk(root / "projects/p.md", "---\ntitle: P\nstatus: active\n---\nAsk zed.\n")


def test_archive_from_the_entity_page_then_unarchive(app: Page, server: AppState, root: Path):
    put(root, "themes/old.md", "---\ntitle: Old theme\n---\n")
    put(root, "projects/p.md", "---\ntitle: P\nstatus: active\ntheme: old\n---\n")
    app.goto(f"{origin(server)}/#/e/old")

    app.get_by_role("button", name="Actions").click()
    app.get_by_role("menuitem", name="Archive…").click()
    dialog = app.get_by_role("dialog", name="Archive Old theme")
    expect(dialog).to_contain_text("1 Project not done or cancelled")
    dialog.get_by_role("button", name="Archive").click()

    expect(app.get_by_text("Archived on 2026-11-12")).to_be_visible()
    app.get_by_role("button", name="Unarchive").click()
    expect(app.get_by_text("Archived on")).to_have_count(0)
    wait_for_disk(root / "themes/old.md", "---\ntitle: Old theme\n---\n")


def test_the_actions_menu_closes_on_escape_and_on_a_click_elsewhere(
    app: Page, server: AppState, root: Path
):
    put(root, "projects/dmig.md", "---\ntitle: Data migration\nstatus: active\n---\n")
    app.goto(f"{origin(server)}/#/e/dmig")
    actions = app.get_by_role("button", name="Actions")
    menu = app.get_by_role("menu")

    actions.click()
    expect(menu).to_be_visible()
    app.keyboard.press("Escape")  # focus is still on the button, not in the menu
    expect(menu).to_be_hidden()

    actions.click()
    expect(menu).to_be_visible()
    app.get_by_label("Title").click()
    expect(menu).to_be_hidden()
