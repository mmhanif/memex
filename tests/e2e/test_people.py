"""SPEC §11.3: the People page, per "People" in Paper."""

from pathlib import Path

from playwright.sync_api import Page, expect

from memex.web.app import AppState
from tests.e2e.conftest import origin
from tests.e2e.test_editor import put


def person(title: str, **fields: str) -> str:
    lines = "".join(f"{k}: {v}\n" for k, v in fields.items())
    return f"---\ntitle: {title}\n{lines}---\n"


def workspace(root: Path) -> None:
    put(
        root,
        "people/ada-lovelace.md",
        person(
            "Ada Lovelace", kind="[team-member]", role="Head of Platform", manager="grace-hopper"
        ),
    )
    put(
        root,
        "people/grace-hopper.md",
        person("Grace Hopper", kind="[team-member]", role="Director of Engineering"),
    )
    put(
        root,
        "people/alice-smith.md",
        person("Alice Smith", kind="[team-member]", role="Staff Engineer", manager="ada-lovelace"),
    )
    put(
        root,
        "people/sam-patel.md",
        person("Sam Patel", kind="[team-member]", role="Software Engineer", manager="alice-smith"),
    )
    put(
        root,
        "people/theo-brandt.md",
        person("Theo Brandt", kind="[team-member]", role="Product Manager", manager="grace-hopper"),
    )
    put(
        root,
        "people/old-hand.md",
        person("Old Hand", kind="[team-member]", manager="ada-lovelace", archived="2026-01-01"),
    )
    put(
        root,
        "people/priya-shah.md",
        person("Priya Shah", kind="[stakeholder]", organisation="Finance", role="Budget owner"),
    )
    put(root, "projects/p.md", person("P", status="active", stakeholders="[priya-shah]"))
    put(
        root,
        "todos/owed.md",
        person("Owed", owner="alice-smith", requester="ada-lovelace", status="open"),
    )
    put(
        root,
        "todos/promised.md",
        person("Promised", owner="ada-lovelace", requester="alice-smith", status="open"),
    )


def test_people_page_shows_the_org_others_and_stakeholders(app: Page, server: AppState, root: Path):
    workspace(root)
    app.goto(f"{origin(server)}/#/people")
    page = app.locator(".people-page")
    expect(page.locator(".eyebrow")).to_have_text("5 Team Members · 1 Stakeholder")

    org = app.get_by_role("region", name="Org")
    expect(org.locator(".org-person.manager")).to_contain_text("Grace Hopper")
    expect(org.locator(".org-person.manager")).to_contain_text("Manager")
    expect(org.locator(".org-person.me > .block-row")).to_contain_text("Head of Platform · Me")
    alice = org.locator(".org-person.depth-1", has_text="Alice Smith")
    expect(alice.locator(":scope > .block-row")).to_contain_text("1 waiting on them · 1 on me")
    expect(alice.get_by_role("link", name="Sam Patel")).to_be_visible()

    # A Person with reports collapses to a count of them.
    app.get_by_role("button", name="Collapse Alice Smith").click()
    expect(alice.get_by_role("link", name="Sam Patel")).to_be_hidden()
    expect(alice.locator(":scope > .block-row")).to_contain_text("1 report")
    app.get_by_role("button", name="Expand Alice Smith").click()
    expect(alice.get_by_role("link", name="Sam Patel")).to_be_visible()

    others = app.get_by_role("region", name="Other Team Members")
    expect(others).to_contain_text("Theo Brandt")
    expect(others).to_contain_text("Product Manager · reports to Grace Hopper")

    stakeholders = app.get_by_role("region", name="Stakeholders")
    row = stakeholders.get_by_role("row", name="Priya Shah")
    expect(row).to_contain_text("Finance")
    expect(row).to_contain_text("Budget owner")
    expect(row.locator(".tags")).to_have_text("1")


def test_show_archived_brings_archived_people_back(app: Page, server: AppState, root: Path):
    workspace(root)
    app.goto(f"{origin(server)}/#/people")
    org = app.get_by_role("region", name="Org")
    expect(org).to_contain_text("Alice Smith")
    expect(org).not_to_contain_text("Old Hand")
    app.get_by_role("switch", name="Show archived").check()
    expect(org.locator(".org-person.depth-1", has_text="Old Hand")).to_contain_text("archived")


def test_stakeholder_button_opens_a_new_stakeholder(app: Page, server: AppState, root: Path):
    app.goto(f"{origin(server)}/#/people")
    app.get_by_role("button", name="Stakeholder").click()
    expect(app.get_by_role("dialog")).to_be_visible()
