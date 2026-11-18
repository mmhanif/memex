"""SPEC §3.6, §7.4: the Settings page against a real server."""

import re
import time
from collections.abc import Callable
from pathlib import Path

from playwright.sync_api import Page, expect

from memex.core.config import load_app_config
from memex.web.app import AppState
from tests.e2e.conftest import origin


def templates(app: Page):
    return app.get_by_role("table", name="Templates")


def meeting_row(app: Page):
    return templates(app).locator("tr", has_text="note/meeting")


def eventually(check: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 5
    while not check():
        assert time.monotonic() < deadline
        time.sleep(0.05)


def test_hide_and_show_a_built_in_template(app: Page, server: AppState, root: Path):
    app.goto(f"{origin(server)}/#/settings")
    meeting_row(app).get_by_role("button", name="Hide").click()

    expect(meeting_row(app)).to_contain_text("hidden")
    config = root / ".memex/config.yaml"
    eventually(lambda: "note/meeting" in config.read_text("utf-8"))

    meeting_row(app).get_by_role("button", name="Show").click()
    expect(meeting_row(app)).not_to_contain_text("hidden")


def test_customise_copies_the_built_in_and_opens_it(app: Page, server: AppState, root: Path):
    app.goto(f"{origin(server)}/#/settings")
    meeting_row(app).get_by_role("button", name="Customise").click()

    expect(app.locator(".editor-path")).to_have_text(".memex/templates/note/meeting.md")
    expect(app.get_by_label("File text")).to_have_value(re.compile("## Agenda"))
    assert (root / ".memex/templates/note/meeting.md").exists()

    app.goto(f"{origin(server)}/#/settings")
    expect(meeting_row(app)).to_contain_text("replaces the built-in")
    expect(meeting_row(app).get_by_role("link", name="Edit raw")).to_be_visible()


def test_a_broken_custom_template_is_marked_with_its_error(app: Page, server: AppState, root: Path):
    folder = root / ".memex/templates/theme"
    folder.mkdir(parents=True)
    (folder / "quarterly.md").write_text("---\ntemplate: [\n---\n", "utf-8")

    app.goto(f"{origin(server)}/#/settings")
    row = templates(app).locator("tr", has_text="theme/quarterly")
    expect(row).to_contain_text("broken")
    expect(row).to_contain_text("Left out of pickers until fixed")


def test_show_all_reveals_the_blank_templates_that_are_not_defaults(app: Page, server: AppState):
    app.goto(f"{origin(server)}/#/settings")
    project_blank = templates(app).locator("tr", has_text="Project").filter(has_text="Blank")
    expect(meeting_row(app)).to_be_visible()
    expect(project_blank).to_have_count(0)

    app.get_by_role("button", name="Show all").click()

    expect(project_blank).to_have_count(1)
    expect(project_blank).to_contain_text("can't be hidden")


def test_ignore_globs_and_polling_save_to_the_workspace_config(
    app: Page, server: AppState, root: Path
):
    config = root / ".memex/config.yaml"
    app.goto(f"{origin(server)}/#/settings")

    add = app.get_by_label("Add an ignore glob")
    add.fill("Archive/**")
    add.press("Enter")
    expect(app.get_by_role("button", name="Remove Archive/**")).to_be_visible()
    eventually(lambda: "Archive/**" in config.read_text("utf-8"))

    app.get_by_role("button", name="Remove Archive/**").click()
    eventually(lambda: "Archive/**" not in config.read_text("utf-8"))

    app.get_by_role("switch", name="Polling").check()
    eventually(lambda: "polling: true" in config.read_text("utf-8"))
    expect(app.locator(".relaunch-bar")).to_contain_text(
        "Saved. 1 change takes effect after a relaunch"
    )


def test_a_new_port_waits_for_a_relaunch(app: Page, server: AppState, tmp_path: Path):
    app.goto(f"{origin(server)}/#/settings")

    port = app.get_by_label("Port")
    port.fill("47620")
    port.press("Enter")

    expect(app.get_by_text("was 47615")).to_be_visible()
    expect(app.get_by_text("relaunch needed")).to_be_visible()
    expect(app.locator(".relaunch-bar")).to_contain_text("1 change takes effect after a relaunch")
    expect(app.get_by_role("button", name="Quit Memex")).to_be_visible()
    eventually(lambda: load_app_config(tmp_path / "home").port == 47620)


def test_about_shows_version_address_and_logs(app: Page, server: AppState, tmp_path: Path):
    app.goto(f"{origin(server)}/#/settings")

    about = app.get_by_role("region", name="About")
    expect(about).to_contain_text(f"127.0.0.1:{server.port}")
    expect(about).to_contain_text(str(tmp_path / "home" / "logs"))
    expect(app.locator(".eyebrow")).to_contain_text("Workspace format 1")


def test_pick_me(app: Page, server: AppState, root: Path):
    (root / "people/grace-hopper.md").write_text("---\ntitle: Grace Hopper\n---\n", "utf-8")
    assert server.workspace is not None
    server.workspace.changed("people/grace-hopper.md")
    app.goto(f"{origin(server)}/#/settings")

    me = app.get_by_role("combobox", name="Me")
    expect(me).to_have_value("Ada Lovelace")
    me.click()
    me.fill("grace")
    app.get_by_role("option", name=re.compile("Grace Hopper")).click()

    config = root / ".memex/config.yaml"
    eventually(lambda: "me: grace-hopper" in config.read_text("utf-8"))
    expect(me).to_have_value("Grace Hopper")
