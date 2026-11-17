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
    app.get_by_role("row", name="themes/old.md").get_by_role("button", name="Restore").click()
    expect(app.get_by_text("The trash is empty.")).to_be_visible()
    assert (root / "themes/old.md").exists()
