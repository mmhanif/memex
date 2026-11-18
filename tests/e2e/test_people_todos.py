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
    expect(column.get_by_role("checkbox", name="Done: Draft plan")).to_be_visible()
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


def test_person_view_header_has_an_avatar_and_an_eyebrow(app: Page, server: AppState, root: Path):
    put(root, "people/alice-smith.md", ALICE)
    app.goto(f"{origin(server)}/#/people/alice-smith")

    head = app.locator(".person-view .entity-head")
    expect(head.locator(".avatar")).to_have_text("AS")
    expect(head.locator(".eyebrow")).to_have_text("Person · Team Member · Direct")
    expect(head.get_by_role("button", name="Actions")).to_be_visible()


def test_person_view_quick_add_alice_is_waiting_on_me(app: Page, server: AppState, root: Path):
    put(root, "people/alice-smith.md", ALICE)
    app.goto(f"{origin(server)}/#/people/alice-smith")

    column = app.get_by_role("region", name="Alice Smith is waiting on me")
    expect(column).to_contain_text("@owner from @requester due:YYYY-MM-DD")
    box = column.get_by_label("Add a To-do Alice Smith is waiting on")
    box.fill("Intro to SRE leads due:2026-12-03")
    box.press("Enter")

    row = column.locator(".person-row", has_text="Intro to SRE leads")
    expect(row).to_contain_text("due Thu 3 Dec")
    expect(column.locator(".column-header .count")).to_have_text("1")
    text = (root / "todos/2026-11-12-intro-to-sre-leads.md").read_text("utf-8")
    assert "owner: ada-lovelace" in text
    assert "requester: alice-smith" in text


def test_person_view_tagged_on_rows_show_role_and_lateness(app: Page, server: AppState, root: Path):
    put(root, "people/alice-smith.md", ALICE)
    put(root, "projects/p.md", "---\ntitle: Data migration\nstatus: active\n---\n")
    put(
        root,
        "deliverables/runbook.md",
        "---\ntitle: Cutover runbook\nproject: p\nstatus: active\nlead: alice-smith\n"
        "due: 2026-11-10\n---\n",
    )
    put(
        root,
        "deliverables/ledger.md",
        "---\ntitle: Ledger export\nproject: p\nstatus: blocked\nteam: [alice-smith]\n---\n",
    )
    app.clock.set_fixed_time("2026-11-12T10:00:00")  # the e2e clock's day, in the browser too
    app.goto(f"{origin(server)}/#/people/alice-smith")

    tagged = app.get_by_role("region", name="Tagged on")
    runbook = tagged.locator(".person-row", has_text="Cutover runbook")
    expect(runbook.locator(".person-row-meta")).to_have_text("Deliverable · 2 days late")
    expect(runbook.locator(".person-role")).to_have_text("Lead")
    ledger = tagged.locator(".person-row", has_text="Ledger export")
    expect(ledger.locator(".person-row-meta")).to_have_text("Deliverable · blocked")
    expect(ledger.locator(".person-role")).to_have_text("Team")


def test_person_view_todo_names_the_note_it_came_from(app: Page, server: AppState, root: Path):
    put(root, "people/alice-smith.md", ALICE)
    put(root, "notes/one.md", "---\ntitle: 1:1 with Alice\ndate: 2026-11-10\n---\n")
    put(
        root,
        "todos/deck.md",
        "---\ntitle: Send deck\nowner: alice-smith\nrequester: ada-lovelace\nstatus: open\n"
        "due: 2026-11-20\nsource: one\n---\n",
    )
    app.goto(f"{origin(server)}/#/people/alice-smith")

    row = app.get_by_role("region", name="Waiting on Alice Smith").locator(".person-row")
    expect(row.locator(".person-row-meta")).to_have_text("due Fri 20 Nov · from 1:1 with Alice")
    expect(row.get_by_role("link", name="1:1 with Alice")).to_have_attribute("href", "#/e/one")


def test_person_view_notes_with_them_and_directs(app: Page, server: AppState, root: Path):
    put(root, "people/alice-smith.md", ALICE)
    put(
        root,
        "people/sam-patel.md",
        "---\ntitle: Sam Patel\nkind: [team-member]\nmanager: alice-smith\n---\n",
    )
    put(root, "people/priya-shah.md", "---\ntitle: Priya Shah\nkind: [stakeholder]\n---\n")
    put(
        root,
        "notes/steering.md",
        "---\ntitle: Steering\ndate: 2026-11-03\npeople: [ada-lovelace, alice-smith, priya-shah]\n"
        "labels: [steering]\n---\n",
    )
    app.goto(f"{origin(server)}/#/people/alice-smith")

    expect(app.locator(".properties .prop", has_text="directs")).to_contain_text("Sam Patel")
    notes = app.get_by_role("region", name="Notes with Alice Smith")
    row = notes.locator(".person-note")
    expect(row).to_contain_text("3 Nov")
    expect(row.locator(".note-with")).to_have_text("with Priya Shah")
    expect(row.locator(".note-labels")).to_have_text("#steering")

    notes.get_by_role("button", name="New 1:1").click()
    expect(app.get_by_role("dialog")).to_be_visible()
