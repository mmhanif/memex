"""SPEC §6.2, §6.3, §11.4, §11.6, §16.7 journeys 4 and 6: To-dos and People."""

from pathlib import Path

from playwright.sync_api import Page, expect

from memex.web.app import AppState
from tests.e2e.conftest import origin
from tests.e2e.test_editor import put, wait_for_disk

ALICE = "---\ntitle: Alice Smith\nkind: [team-member]\nmanager: ada-lovelace\n---\nAbout Alice\n"


def test_quick_add_on_the_todos_page_creates_a_todo_in_mine(
    app: Page, server: AppState, root: Path
):
    app.goto(f"{origin(server)}/#/todos/mine")
    box = app.get_by_label("Quick-add To-do")
    box.fill("Buy milk due:2026-12-01")
    expect(app.locator(".quick-add-preview")).to_contain_text("Buy milk")
    box.press("Enter")

    expect(app.locator(".todo", has_text="Buy milk")).to_contain_text("due 2026-12-01")
    text = (root / "todos/2026-11-12-buy-milk.md").read_text("utf-8")
    assert "owner: ada-lovelace" in text


def test_quick_add_shows_token_errors_and_creates_nothing(app: Page, server: AppState, root: Path):
    app.goto(f"{origin(server)}/#/todos/mine")
    box = app.get_by_label("Quick-add To-do")
    box.fill("Review @zz")
    expect(app.locator(".quick-add-preview")).to_contain_text("No Person matches @zz")
    box.press("Enter")
    expect(app.get_by_role("alert")).to_contain_text("No Person matches @zz")
    assert list((root / "todos").iterdir()) == []


def test_ticking_a_todo_marks_its_file_done(app: Page, server: AppState, root: Path):
    rel = "todos/call.md"
    put(
        root,
        rel,
        "---\ntitle: Call vendor\nowner: ada-lovelace\nrequester: ada-lovelace\n"
        "status: open\n---\n",
    )
    app.goto(f"{origin(server)}/#/todos/mine")
    app.get_by_label("Done: Call vendor").check()
    wait_for_disk(
        root / rel,
        "---\ntitle: Call vendor\nowner: ada-lovelace\nrequester: ada-lovelace\n"
        "status: done\ncompleted: 2026-11-12\n---\n",
    )


def test_person_view_quick_add_waiting_on_alice(app: Page, server: AppState, root: Path):
    put(root, "people/alice-smith.md", ALICE)
    app.goto(f"{origin(server)}/#/e/alice-smith")
    expect(app).to_have_url(f"{origin(server)}/#/people/alice-smith")

    app.get_by_label("Add a To-do waiting on Alice Smith").fill("Draft plan")
    app.get_by_label("Add a To-do waiting on Alice Smith").press("Enter")

    column = app.get_by_role("region", name="Waiting on Alice Smith")
    expect(column.locator(".todo", has_text="Draft plan")).to_be_visible()
    text = (root / "todos/2026-11-12-draft-plan.md").read_text("utf-8")
    assert "owner: alice-smith" in text
    assert "requester: ada-lovelace" in text


def test_person_view_tag_to_writes_the_tag_on_the_item(app: Page, server: AppState, root: Path):
    put(root, "people/alice-smith.md", ALICE)
    put(root, "projects/p.md", "---\ntitle: Data migration\nstatus: active\n---\n")
    app.goto(f"{origin(server)}/#/people/alice-smith")

    app.get_by_label("Tag Alice Smith to…").select_option("p")
    app.get_by_role("button", name="Tag", exact=True).click()

    wait_for_disk(
        root / "projects/p.md",
        "---\ntitle: Data migration\nstatus: active\nteam: [alice-smith]\n---\n",
    )
    tagged = app.get_by_role("region", name="Tagged on")
    expect(tagged).to_contain_text("Data migration")


def test_dashboard_and_people_page_show_directs(app: Page, server: AppState, root: Path):
    put(root, "people/alice-smith.md", ALICE)
    put(
        root,
        "todos/t.md",
        "---\ntitle: Send deck\nowner: alice-smith\nrequester: ada-lovelace\nstatus: open\n---\n",
    )
    app.goto(f"{origin(server)}/#/home")
    expect(app.get_by_role("region", name="Waiting on them")).to_contain_text("Send deck")
    expect(app.get_by_role("region", name="Directs")).to_contain_text("Alice Smith")

    app.goto(f"{origin(server)}/#/people")
    expect(app.locator(".org-tree")).to_contain_text("Alice Smith")
