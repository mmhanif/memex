"""SPEC §7.4: Settings → Templates against a real server."""

import re
import time
from pathlib import Path

from playwright.sync_api import Page, expect

from memex.web.app import AppState
from tests.e2e.conftest import origin


def meeting_row(app: Page):
    group = app.get_by_label("Note Templates")
    return group.locator("tr", has_text="note/meeting")


def test_hide_and_show_a_built_in_template(app: Page, server: AppState, root: Path):
    app.goto(f"{origin(server)}/#/settings")
    meeting_row(app).get_by_role("button", name="Hide").click()

    expect(meeting_row(app)).to_contain_text("hidden")
    config = root / ".memex/config.yaml"
    deadline = time.monotonic() + 5
    while "note/meeting" not in config.read_text("utf-8"):
        assert time.monotonic() < deadline
        time.sleep(0.05)

    meeting_row(app).get_by_role("button", name="Show").click()
    expect(meeting_row(app)).not_to_contain_text("hidden")


def test_customise_copies_the_built_in_and_opens_it(app: Page, server: AppState, root: Path):
    app.goto(f"{origin(server)}/#/settings")
    meeting_row(app).get_by_role("button", name="Customise").click()

    expect(app.locator(".editor-path")).to_have_text(".memex/templates/note/meeting.md")
    expect(app.get_by_label("File text")).to_have_value(re.compile("## Agenda"))
    assert (root / ".memex/templates/note/meeting.md").exists()

    app.goto(f"{origin(server)}/#/settings")
    expect(meeting_row(app)).to_contain_text("Custom, replaces the built-in")
