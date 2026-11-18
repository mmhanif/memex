"""SPEC §6.2, §6.3, §11.3: the To-dos page, per "To-dos — Mine" in Paper."""

from pathlib import Path

from playwright.sync_api import Page, expect

from memex.web.app import AppState
from tests.e2e.conftest import origin
from tests.e2e.test_dashboard import ALICE, todo
from tests.e2e.test_editor import put


def todos_page(app: Page, server: AppState, view: str = "mine") -> None:
    """The page on the e2e clock's day, Thursday 12 November 2026, in the browser too."""
    app.clock.set_fixed_time("2026-11-12T10:00:00")
    app.goto(f"{origin(server)}/#/todos/{view}")
    app.reload()


def test_mine_counts_each_view_and_groups_by_due(app: Page, server: AppState, root: Path):
    put(root, "people/alice-smith.md", ALICE)
    put(root, "todos/late.md", todo("Approve plan", "ada-lovelace", "alice-smith", "2026-11-11"))
    put(root, "todos/later.md", todo("Write promo", "ada-lovelace", "ada-lovelace", "2026-12-01"))
    put(root, "todos/undated.md", todo("Unblock staging", "ada-lovelace", "ada-lovelace"))
    put(root, "todos/theirs.md", todo("Send numbers", "alice-smith", "ada-lovelace"))
    todos_page(app, server)

    expect(app.locator(".todos-head .eyebrow")).to_have_text("3 open · 1 overdue")
    views = app.get_by_role("navigation", name="To-do views")
    expect(views.get_by_role("link", name="Mine")).to_have_text("Mine 3")
    expect(views.get_by_role("link", name="Waiting on them")).to_have_text("Waiting on them 1")
    expect(views.get_by_role("link", name="Waiting on me")).to_have_text("Waiting on me 1")
    badge = app.get_by_role("navigation", name="Sections").locator(".side-count")
    expect(badge).to_have_text("3")

    overdue = app.get_by_role("region", name="Overdue")
    expect(overdue).to_contain_text("Approve plan from @alice-smith")
    expect(overdue.locator(".due.late")).to_have_text("due Wed 11 Nov · 1 day late")
    week = app.get_by_role("region", name="This week")
    expect(week).to_contain_text("through Sun 15 Nov")
    expect(week).to_contain_text("Nothing due this week.")
    expect(app.get_by_role("region", name="Later")).to_contain_text("Write promo due Tue 1 Dec")
    expect(app.get_by_role("region", name="No date")).to_contain_text("Unblock staging")


def test_waiting_on_them_groups_by_owner(app: Page, server: AppState, root: Path):
    put(root, "people/alice-smith.md", ALICE)
    put(root, "todos/theirs.md", todo("Send numbers", "alice-smith", "ada-lovelace"))
    todos_page(app, server, "waiting-on-them")

    expect(app.locator(".todos-head .eyebrow")).to_have_text("1 open")
    group = app.get_by_role("region", name="Alice Smith")
    expect(group.get_by_role("link", name="Alice Smith")).to_have_attribute(
        "href", "#/people/alice-smith"
    )
    expect(group.get_by_role("checkbox", name="Done: Send numbers")).to_be_visible()


def test_show_completed_adds_finished_todos(app: Page, server: AppState, root: Path):
    put(root, "todos/open.md", todo("Open one", "ada-lovelace", "ada-lovelace"))
    put(
        root,
        "todos/done.md",
        "---\ntitle: Done one\nowner: ada-lovelace\nrequester: ada-lovelace\n"
        "status: done\ncompleted: 2026-11-11\n---\n",
    )
    todos_page(app, server)
    expect(app.get_by_role("region", name="Completed")).to_have_count(0)

    app.get_by_role("switch", name="Show completed").check()
    done = app.get_by_role("region", name="Completed")
    expect(done.get_by_role("checkbox", name="Done: Done one")).to_be_checked()
    expect(app.locator(".todos-head .eyebrow")).to_have_text("1 open")


def test_quick_add_preview_names_each_field_and_where_it_goes(
    app: Page, server: AppState, root: Path
):
    put(root, "people/alice-smith.md", ALICE)
    app.goto(f"{origin(server)}/#/people/alice-smith")  # wait until the server has seen her
    expect(app.get_by_role("heading", name="Alice Smith", level=1)).to_be_visible()
    todos_page(app, server)
    box = app.get_by_label("Quick-add To-do")
    box.fill("Draft the SLO review doc @alice due:2026-11-27")

    preview = app.locator(".quick-add-preview")
    expect(preview).to_contain_text("title Draft the SLO review doc")
    expect(preview).to_contain_text("owner Alice Smith")
    expect(preview).to_contain_text("from Me")
    expect(preview).to_contain_text("due Fri 27 Nov")
    expect(preview).to_contain_text("goes to Waiting on them")

    box.press("Enter")
    views = app.get_by_role("navigation", name="To-do views")
    expect(views.get_by_role("link", name="Waiting on them")).to_have_text("Waiting on them 1")
    assert (root / "todos/2026-11-12-draft-the-slo-review-doc.md").exists()
