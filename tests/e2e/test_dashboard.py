"""SPEC §11.4, §3.5, §6.4: the Dashboard (Home) as dated outline blocks."""

from pathlib import Path

from playwright.sync_api import Page, expect

from memex.web.app import AppState
from tests.e2e.conftest import origin
from tests.e2e.test_editor import put

ALICE = (
    "---\ntitle: Alice Smith\nkind: [team-member]\nmanager: ada-lovelace\n"
    "role: Staff Engineer\n---\n"
)


def todo(title: str, owner: str, requester: str, due: str | None = None) -> str:
    return (
        f"---\ntitle: {title}\nowner: {owner}\nrequester: {requester}\nstatus: open\n"
        + (f"due: {due}\n" if due else "")
        + "---\n"
    )


def home(app: Page, server: AppState) -> None:
    """Home on the e2e clock's day, Thursday 12 November 2026, in the browser too."""
    app.clock.set_fixed_time("2026-11-12T10:00:00")
    app.goto(f"{origin(server)}/#/home")
    app.reload()


def test_home_is_titled_by_date_with_a_summary_and_relative_lateness(
    app: Page, server: AppState, root: Path
):
    put(root, "people/alice-smith.md", ALICE)
    put(root, "projects/late.md", "---\ntitle: Cutover\nstatus: active\ndue: 2026-11-10\n---\n")
    put(root, "projects/soon.md", "---\ntitle: Baseline\nstatus: active\ndue: 2026-11-16\n---\n")
    put(root, "todos/plan.md", todo("Approve plan", "ada-lovelace", "alice-smith", "2026-11-11"))
    home(app, server)

    expect(app.get_by_role("heading", level=1)).to_have_text("Thursday, 12 November")
    expect(app.locator(".dashboard .eyebrow")).to_have_text("Today · 2 overdue · 1 due this week")
    due = app.get_by_role("region", name="Due within 7 days")
    expect(due.locator(".when")).to_have_text(["2 days late", "1 day late", "Mon 16 Nov"])
    expect(due.locator(".when.late")).to_have_count(2)
    expect(due.locator(".todo-block .block-text")).to_contain_text("Approve plan for @alice-smith")


def test_directs_table_counts_match_the_waiting_lists(app: Page, server: AppState, root: Path):
    put(root, "people/alice-smith.md", ALICE)
    put(root, "todos/a.md", todo("Send deck", "alice-smith", "ada-lovelace"))
    put(root, "todos/b.md", todo("Sign off", "alice-smith", "ada-lovelace"))
    put(root, "todos/c.md", todo("Review rota", "ada-lovelace", "alice-smith"))
    home(app, server)

    them = app.get_by_role("region", name="Waiting on them")
    group = them.locator(".block", has=app.get_by_role("link", name="Alice Smith", exact=True))
    expect(group.locator(".todo-block")).to_have_count(2)
    expect(app.get_by_role("region", name="Waiting on me").locator(".todo-block")).to_have_count(1)

    row = app.get_by_role("region", name="Directs").get_by_role("row", name="Alice Smith")
    expect(row).to_contain_text("Staff Engineer")
    expect(row.get_by_role("cell")).to_have_text(["Alice Smith · Staff Engineer", "2", "1"])


def test_recent_notes_say_how_many_todos_to_create(app: Page, server: AppState, root: Path):
    put(
        root,
        "notes/standup.md",
        "---\ntitle: Standup\ndate: 2026-11-12\n---\n- [ ] One\n- [ ] Two\n",
    )
    home(app, server)
    note = app.get_by_role("region", name="Recent notes").locator(".note-row", has_text="Standup")
    expect(note).to_contain_text("Today")
    expect(note.locator(".to-create")).to_have_text("2 To-dos to create")


def test_without_me_the_me_blocks_are_paused(app: Page, server: AppState, root: Path):
    put(root, ".memex/config.yaml", "format: 1\n")
    put(root, "projects/stuck.md", "---\ntitle: Vendor SSO\nstatus: blocked\n---\n")
    home(app, server)

    for name in ("Waiting on them", "Waiting on me", "Directs"):
        expect(app.get_by_role("region", name=name).locator(".paused")).to_contain_text(
            "Paused until Me is set"
        )
    expect(app.get_by_role("region", name="Due within 7 days").locator(".paused")).to_contain_text(
        "To-dos Me owns"
    )
    blocked = app.get_by_role("region", name="Blocked work")
    expect(blocked.locator(".paused")).to_have_count(0)
    expect(blocked).to_contain_text("Vendor SSO")
