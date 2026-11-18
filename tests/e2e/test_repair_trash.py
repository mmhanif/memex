"""SPEC §8.4, §8.5: the Broken references and Trash pages, per their Paper designs."""

from pathlib import Path

from playwright.sync_api import Page, expect

from memex.core import lifecycle
from memex.web.app import AppState
from tests.e2e.conftest import origin
from tests.e2e.test_editor import put

Q1 = "---\ntitle: Q1 Capacity\nstatus: active\ntheme: platform-ops\n---\n"
OFF = (
    "Create is off because the references imply different types. Replace or Remove one side first."
)
P = "---\ntitle: P\nstatus: active\n---\nSee [[old-plan]] and [[old-plan]].\n"


def test_broken_references_shows_each_group_with_its_occurrences(
    app: Page, server: AppState, root: Path
):
    put(
        root,
        "projects/data-migration.md",
        "---\ntitle: Data Migration\nstatus: active\nstakeholders: [marco-ruiz]\n---\n",
    )
    put(root, "notes/call.md", "# Vendor call\n\nLedgerCo's lead [[marco-ruiz]] will send it.\n")
    put(root, "projects/q1.md", Q1)
    put(root, "projects/idp.md", "---\ntitle: IdP\nstatus: active\nlead: platform-ops\n---\n")
    app.goto(f"{origin(server)}/#/broken")

    expect(app.locator(".repair-head .eyebrow")).to_have_text("2 Ids · 4 references")
    marco = app.get_by_role("article", name="Broken reference marco-ruiz")
    expect(marco.locator(".broken-badge")).to_have_text("missing")
    expect(marco.locator(".broken-meta")).to_have_text("implies Person · 2 refs")
    expect(marco.get_by_role("button", name="Create Person")).to_be_enabled()
    row = marco.locator(".broken-use", has_text="Data Migration")
    expect(row.locator(".use-path")).to_have_text("projects/data-migration.md")
    expect(row.locator(".field-chip")).to_have_text("stakeholders")
    call = marco.locator(".broken-use", has_text="Vendor call")
    expect(call.locator(".field-chip")).to_have_text("Mention")
    snippet = call.locator(".use-snippet")
    expect(snippet).to_have_text("LedgerCo's lead [[marco-ruiz]] will send it.")

    ops = app.get_by_role("article", name="Broken reference platform-ops")
    expect(ops.locator(".broken-meta")).to_have_text("Person or Theme? · 2 refs")
    expect(ops.locator(".broken-use", has_text="Q1 Capacity").locator(".field-chip")).to_have_text(
        "theme → Theme"
    )
    create = ops.get_by_role("button", name="Create…")
    expect(create).to_be_disabled()
    expect(create).to_have_accessible_description(OFF)

    marco.get_by_role("button", name="Create Person").click()
    expect(marco).to_have_count(0)
    assert (root / "people/marco-ruiz.md").exists()


def test_an_ambiguous_id_is_fixed_by_renaming_one_file_that_claims_it(
    app: Page, server: AppState, root: Path
):
    put(root, "projects/runbook.md", "---\ntitle: Runbook\nstatus: active\n---\n")
    put(root, "reading/Runbook.md", "# Runbook reading\n")
    put(root, "notes/n.md", "See [[runbook]].\n")
    app.goto(f"{origin(server)}/#/broken")

    group = app.get_by_role("article", name="Broken reference runbook")
    expect(group.locator(".broken-badge")).to_have_text("ambiguous")
    expect(group.locator(".broken-meta")).to_have_text("2 files claim it · 1 ref")
    expect(group.locator(".claimed .use-path")).to_have_text(
        "projects/runbook.md · reading/Runbook.md"
    )
    expect(group.get_by_role("button", name="Create Person")).to_have_count(0)

    group.get_by_role("button", name="Rename id…").click()
    group.get_by_label("File to rename").select_option("reading/Runbook.md")
    group.get_by_label("New Id").fill("runbook-reading")
    group.get_by_role("button", name="Rename", exact=True).click()

    expect(app.get_by_text("No Broken References.")).to_be_visible()
    assert (root / "reading/runbook-reading.md").exists()


def test_trash_groups_by_stamp_and_says_what_each_delete_did(
    app: Page, server: AppState, root: Path
):
    app.clock.set_fixed_time("2026-11-12T10:00:00")
    put(root, "notes/old-plan.md", "# Old cutover plan\n")
    put(root, "notes/runbook.md", "# Cutover Runbook\n")
    put(root, "projects/p.md", P)
    put(root, "glossary/slo.md", "---\ntitle: Service level objective\n---\n")
    ws = server.workspace
    assert ws is not None
    for rel in ("notes/old-plan.md", "notes/runbook.md", "projects/p.md", "glossary/slo.md"):
        ws.changed(rel)  # before the watcher gets there
    lifecycle.delete_entity(ws, "old-plan", "replace", "runbook", dry_run=False)
    lifecycle.delete_entity(ws, "slo", dry_run=False)
    put(root, "notes/SLO.md", "---\ntitle: SLO\n---\n")
    ws.changed("notes/SLO.md")
    app.goto(f"{origin(server)}/#/trash")

    eyebrow = app.locator(".repair-head .eyebrow")
    expect(eyebrow).to_have_text("2 files · never emptied automatically")
    group = app.locator(".trash-group")
    expect(group.locator(".trash-when .block-text")).to_have_text("Thu 12 Nov, 00:00")
    expect(group.locator(".trash-stamp")).to_have_text("20261112-000000-2/ · 20261112-000000/")

    plan = app.get_by_role("group", name="notes/old-plan.md")
    expect(plan.locator(".trash-title")).to_have_text("Old cutover plan")
    expect(plan.locator(".trash-note")).to_have_text(
        "Note · 2 references were replaced with Cutover Runbook (not restored)"
    )
    expect(plan.get_by_role("button", name="Restore")).to_be_enabled()

    slo = app.get_by_role("group", name="glossary/slo.md")
    expect(slo.locator(".trash-note")).to_contain_text(
        "Can't restore: Id slo is taken by SLO (notes/SLO.md)."
    )
    expect(slo.get_by_role("button", name="Restore")).to_be_disabled()

    plan.get_by_role("button", name="Restore").click()
    expect(plan).to_have_count(0)
    assert (root / "notes/old-plan.md").exists()
