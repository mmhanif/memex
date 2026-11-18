"""SPEC §7, §11.5, §16.7: creating Entities and the Entity page against a real server."""

from pathlib import Path

from playwright.sync_api import Page, expect

from memex.web.app import AppState
from tests.e2e.conftest import origin
from tests.e2e.test_editor import put, wait_for_disk
from tests.e2e.test_people_todos import ALICE


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
    bar = app.locator(".validation-bar", has_text="1 Broken Reference")
    expect(bar).to_contain_text("mention points to ghost")


def test_a_project_page_has_an_eyebrow_and_an_actions_menu_that_opens_the_file(
    app: Page, server: AppState, root: Path
):
    put(root, "themes/platform.md", "---\ntitle: Platform Reliability\n---\n")
    project = "---\ntitle: Data migration\nstatus: active\ntheme: platform\n---\n"
    put(root, "projects/dmig.md", project)
    app.goto(f"{origin(server)}/#/e/dmig")

    expect(app.locator(".entity-head .eyebrow")).to_have_text("Project · Platform Reliability")
    app.get_by_role("button", name="Actions").click()
    items = app.get_by_role("menu").get_by_role("menuitem")
    expect(items).to_have_text(["Rename id… dmig", "Open file .md", "Delete… to Trash"])
    items.filter(has_text="Open file").click()

    expect(app).to_have_url(f"{origin(server)}/#/f/projects/dmig.md")


def test_a_notes_body_is_an_outline_whose_blocks_collapse(app: Page, server: AppState, root: Path):
    body = "## Notes\n\n- Dry run\n  - Sign-off\n  - Rollback\n- Stretch\n"
    put(root, "notes/sync.md", f"---\ntitle: Sync\ndate: 2026-11-12\n---\n{body}")
    app.goto(f"{origin(server)}/#/e/sync")

    expect(app.locator(".entity-head .eyebrow")).to_have_text("Note · Thu 12 Nov 2026")
    section = app.locator(".entity-body .block", has=app.get_by_role("heading", name="Notes"))
    expect(section.locator(".block-children")).to_contain_text("Stretch")

    app.get_by_role("button", name="Collapse Dry run").click()
    expect(app.get_by_text("Sign-off")).to_be_hidden()
    expect(app.locator(".entity-body li.collapsed")).to_contain_text("Dry run")
    app.get_by_role("button", name="Expand Dry run").click()
    expect(app.get_by_text("Sign-off")).to_be_visible()

    app.get_by_role("button", name="Collapse Notes").click()
    expect(app.get_by_text("Stretch")).to_be_hidden()


def test_a_late_live_todo_row_shows_its_owner_and_due_in_rust(
    app: Page, server: AppState, root: Path
):
    put(root, "people/alice-smith.md", ALICE)
    todo = (
        "---\ntitle: Send deck\nowner: alice-smith\nrequester: ada-lovelace\nstatus: open\n"
        "due: 2026-01-05\n---\n"
    )
    put(root, "todos/send-deck.md", todo)
    put(root, "notes/sync.md", "---\ntitle: Sync\n---\n- [ ] [[send-deck]]\n")
    app.goto(f"{origin(server)}/#/e/sync")

    row = app.locator(".markdown .todo-ref")
    expect(row.locator(".party")).to_have_text("Alice Smith")
    expect(row.locator(".due.late")).to_have_text("due Mon 5 Jan")


def test_mentioned_in_shows_the_line_that_mentions_this_entity(
    app: Page, server: AppState, root: Path
):
    put(root, "projects/dmig.md", "---\ntitle: Data migration\nstatus: active\n---\n")
    put(root, "notes/steering.md", "---\ntitle: Steering\n---\n- Walk through [[dmig]] numbers\n")
    app.goto(f"{origin(server)}/#/e/dmig")

    section = app.get_by_role("region", name="Mentioned in")
    expect(section.locator(".section-header")).to_have_text("Mentioned in 1")
    card = section.locator(".ref-card")
    expect(card.get_by_role("link", name="Steering")).to_have_attribute("href", "#/e/steering")
    expect(card).to_contain_text("Walk through Data migration numbers")


def test_todos_about_a_project_tick_from_its_page(app: Page, server: AppState, root: Path):
    put(root, "projects/dmig.md", "---\ntitle: Data migration\nstatus: active\n---\n")
    rel = "todos/call.md"
    todo = (
        "title: Call vendor\nowner: ada-lovelace\nrequester: ada-lovelace\nstatus: open\n"
        "about: dmig"
    )
    put(root, rel, f"---\n{todo}\n---\n")
    app.goto(f"{origin(server)}/#/e/dmig")

    section = app.get_by_role("region", name="To-dos about this")
    expect(section.locator(".section-header")).to_contain_text("1 open")
    section.get_by_label("Done: Call vendor").check()

    wait_for_disk(
        root / rel,
        f"---\n{todo.replace('open', 'done')}\ncompleted: 2026-11-12\n---\n",
    )
