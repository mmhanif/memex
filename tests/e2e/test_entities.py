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
    expect(dialog.get_by_role("button", name="Template")).to_have_text("★ Project")
    expect(dialog.locator(".template-hint")).to_have_text("Goal · Scope · Risks · Decisions")
    dialog.get_by_label("Title").fill("Data migration")
    expect(dialog.locator(".new-path")).to_have_text("projects/data-migration.md")
    expect(dialog.locator(".body-preview")).to_contain_text("Risks")
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


def test_the_new_menu_offers_template_variants_and_ctrl_enter_creates(
    app: Page, server: AppState, root: Path
):
    app.get_by_role("button", name="New…").click()
    menu = app.get_by_role("menu")
    expect(menu.get_by_role("menuitem")).to_have_text(
        [
            "Note notes/",
            "Note: Meeting 2026-11-12-…",
            "Note: 1:1 2026-11-12-…",
            "Theme",
            "Project",
            "Deliverable needs a Project",
            "Person Team Member",
            "Person: Stakeholder",
            "To-do owner, requester",
            "Glossary Term",
        ]
    )
    menu.get_by_role("menuitem", name="Note: Meeting").click()

    dialog = app.get_by_role("dialog", name="New Note")
    expect(dialog.get_by_role("button", name="Template")).to_have_text("Meeting")
    expect(dialog.locator(".template-hint")).to_have_text("sets Date and Participants")
    dialog.get_by_label("Title").fill("Platform sync")
    expect(dialog.locator(".new-path")).to_have_text("notes/2026-11-12-platform-sync.md")
    expect(dialog.locator(".new-foot")).to_have_text("date-prefixed Id because the Note has a Date")
    dialog.get_by_label("Title").press("Control+Enter")

    expect(app).to_have_url(f"{origin(server)}/#/e/2026-11-12-platform-sync")
    assert "## Agenda" in (root / "notes/2026-11-12-platform-sync.md").read_text("utf-8")


def test_the_template_dropdown_lists_variants_with_their_headings(app: Page, root: Path):
    put(
        root,
        ".memex/templates/note/steering.md",
        "---\ntemplate:\n  name: Steering\n---\n## Asks\n",
    )
    app.get_by_role("button", name="New…").click()
    app.get_by_role("menuitem", name="Note", exact=True).click()
    dialog = app.get_by_role("dialog", name="New Note")
    dialog.get_by_role("button", name="Template").click()

    options = dialog.get_by_role("listbox", name="Templates").get_by_role("option")
    expect(options).to_have_text(
        [
            "★ Blank no fields, empty body",
            "Meeting Agenda · Notes · Actions",
            "1:1 Their topics · My topics · Feedback · Actions",
            "Steering custom .memex/templates/note/steering.md",
        ]
    )
    expect(options.first).to_have_attribute("aria-selected", "true")
    expect(dialog.get_by_role("link", name="Manage Templates")).to_have_attribute(
        "href", "#/settings"
    )
    options.filter(has_text="Steering").click()
    expect(dialog.get_by_role("button", name="Template")).to_have_text("Steering")
    expect(dialog.locator(".body-preview")).to_contain_text("Asks")


def test_person_pickers_highlight_matches_and_hide_archived_people(
    app: Page, server: AppState, root: Path
):
    put(root, "people/alice-smith.md", ALICE.replace("manager:", "role: Staff Engineer\nmanager:"))
    put(
        root,
        "people/alan-old.md",
        "---\ntitle: Alan Old\nkind: [team-member]\narchived: 2026-01-01\n---\n",
    )
    put(root, "people/priya-shah.md", "---\ntitle: Priya Shah\nkind: [stakeholder]\n---\n")
    app.get_by_role("button", name="New…").click()
    app.get_by_role("menuitem", name="Project").click()
    dialog = app.get_by_role("dialog", name="New Project")
    dialog.get_by_label("Title").fill("Ledger")

    dialog.get_by_role("combobox", name="Lead").fill("al")
    matches = dialog.locator(".picker-popover")
    expect(matches.get_by_role("option")).to_have_text(["AS Alice Smith Staff Engineer"])
    expect(matches.locator("mark")).to_have_text(["Al"])
    expect(matches).to_contain_text("1 archived match hidden")
    matches.get_by_role("switch", name="Include archived").check()
    expect(matches.get_by_role("option")).to_have_count(2)
    matches.get_by_role("option", name="Alice Smith").click()
    expect(dialog.get_by_role("combobox", name="Lead")).to_have_value("Alice Smith")

    dialog.get_by_role("combobox", name="Stakeholders").fill("pri")
    dialog.get_by_role("combobox", name="Stakeholders").press("Enter")
    expect(dialog.locator(".picker-chip")).to_have_text(["PS Priya Shah"])

    dialog.get_by_role("button", name="Create").click()
    expect(app).to_have_url(f"{origin(server)}/#/e/ledger")
    text = (root / "projects/ledger.md").read_text("utf-8")
    assert "lead: alice-smith" in text
    assert "stakeholders: [priya-shah]" in text


def test_person_picker_ignores_marks_outside_the_latin_combining_block(
    app: Page, server: AppState, root: Path
):
    # Hebrew niqqud (U+05B0-U+05C7) are combining marks outside U+0300-U+036F (#60).
    david = "\u05d3\u05b8\u05bc\u05d5\u05b4\u05d3"
    put(root, "people/david.md", f"---\ntitle: {david}\nkind: [team-member]\n---\n")
    app.goto(f"{origin(server)}/#/people")
    expect(app.get_by_text(david)).to_be_visible()
    app.get_by_role("button", name="New…").click()
    app.get_by_role("menuitem", name="Project").click()
    dialog = app.get_by_role("dialog", name="New Project")
    expect(dialog.get_by_label("Title")).to_be_focused()

    dialog.get_by_role("combobox", name="Lead").fill("\u05d3\u05d5\u05d3")

    options = dialog.locator(".picker-popover").get_by_role("option")
    expect(options).to_have_count(1)
    expect(options).to_contain_text(david)


def test_a_childs_lead_avatar_is_dark_for_me_and_names_its_person(
    app: Page, server: AppState, root: Path
):
    put(root, "people/alice-smith.md", ALICE)
    put(root, "projects/p.md", "---\ntitle: Data migration\nstatus: active\n---\n")
    for slug, title, lead in [
        ("runbook", "Cutover runbook", "ada-lovelace"),
        ("ledger", "Ledger export", "alice-smith"),
    ]:
        put(
            root,
            f"deliverables/{slug}.md",
            f"---\ntitle: {title}\nproject: p\nstatus: active\nlead: {lead}\n---\n",
        )
    app.goto(f"{origin(server)}/#/e/p")

    mine = app.locator(".child-row", has_text="Cutover runbook").locator(".avatar")
    expect(mine).to_have_text("AL")
    expect(mine).to_have_class("avatar me")
    expect(mine).to_have_attribute("title", "Ada Lovelace")
    expect(mine).to_have_attribute("aria-hidden", "true")
    theirs = app.locator(".child-row", has_text="Ledger export").locator(".avatar")
    expect(theirs).to_have_class("avatar")
    expect(theirs).to_have_attribute("title", "Alice Smith")
