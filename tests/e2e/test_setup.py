"""SPEC §3.4: the first-run Setup page, in a real browser."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from memex.core.clock import FixedClock
from memex.core.config import Location, load_app_config
from memex.web.app import AppState
from tests.e2e.conftest import TODAY, origin
from tests.live import live_server


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    monkeypatch.setenv("MEMEX_HOME", str(home))
    return home


@pytest.fixture
def fresh(home: Path, tmp_path: Path) -> Iterator[AppState]:
    """A server with no Workspace yet: first run."""

    def make(port: int) -> AppState:
        return AppState.from_location(
            Location(path=None, ready=False),
            port=port,
            home=home,
            clock=FixedClock(TODAY),
            install_dir=tmp_path / "i",
        )

    with live_server(make) as state:
        yield state


@pytest.fixture
def setup_page(page: Page, fresh: AppState) -> Page:
    page.goto(f"{origin(fresh)}/auth?code={fresh.session.issue_code()}")
    expect(page.get_by_role("heading", name="Set up Memex")).to_be_visible()
    return page


def test_setup_makes_a_new_workspace_and_opens_the_dashboard(
    setup_page: Page, fresh: AppState, home: Path, tmp_path: Path
):
    page = setup_page
    folder = tmp_path / "Memex"
    expect(page.get_by_label("Folder")).to_have_value(str(Path("~/Documents/Memex").expanduser()))

    page.get_by_label("Folder").fill(str(folder))
    page.get_by_role("button", name="Check folder").click()
    expect(page.get_by_text("0 Notes, 0 Persons")).to_be_visible()
    page.get_by_label("Your name").fill("Ada Lovelace")
    page.get_by_role("button", name="Set up Memex").click()

    expect(page.locator(".shell")).to_be_visible()
    expect(page.get_by_text("get started", exact=False).first).to_be_visible()
    assert (folder / ".memex/config.yaml").is_file()
    assert (folder / "people/ada-lovelace.md").is_file()
    assert load_app_config(home).workspace == folder


def test_setup_adopts_a_folder_and_picks_an_existing_person_as_me(
    setup_page: Page, fresh: AppState, tmp_path: Path
):
    page = setup_page
    folder = tmp_path / "existing"
    (folder / "people").mkdir(parents=True)
    grace = b"---\ntitle: Grace Hopper\nkind: [stakeholder]\n---\n"
    (folder / "people/grace-hopper.md").write_bytes(grace)
    (folder / "standup.md").write_bytes(b"# Standup\r\n")

    page.get_by_label("Folder").fill(str(folder))
    page.get_by_role("button", name="Check folder").click()
    expect(page.get_by_text("1 Note, 1 Person")).to_be_visible()
    assert not (folder / ".memex").exists()  # checking writes nothing
    page.get_by_label("I'm one of these").check()
    page.get_by_label("Person").select_option("grace-hopper")
    page.get_by_role("button", name="Set up Memex").click()

    expect(page.locator(".shell")).to_be_visible()
    assert fresh.workspace is not None
    assert fresh.workspace.config.me == "grace-hopper"
    assert (folder / "people/grace-hopper.md").read_bytes() == grace
    assert (folder / "standup.md").read_bytes() == b"# Standup\r\n"


def test_a_refused_folder_shows_why_and_writes_nothing(
    setup_page: Page, fresh: AppState, tmp_path: Path
):
    page = setup_page
    inside_install = tmp_path / "i" / "ws"

    page.get_by_label("Folder").fill(str(inside_install))
    page.get_by_role("button", name="Check folder").click()

    expect(page.get_by_role("alert")).to_contain_text("install folder")
    expect(page.get_by_label("Your name")).to_have_count(0)
    assert fresh.workspace is None


def test_checking_a_folder_ticks_its_step_and_says_what_setup_will_add(
    setup_page: Page, tmp_path: Path
):
    page = setup_page
    folder = tmp_path / "existing"
    folder.mkdir()
    (folder / "standup.md").write_bytes(b"# Standup\n")
    expect(page.get_by_role("img", name="Done")).to_have_count(0)

    page.get_by_label("Folder").fill(str(folder))
    page.get_by_role("button", name="Check folder").click()

    expect(page.get_by_role("img", name="Done")).to_be_visible()
    expect(page.get_by_role("status")).to_contain_text("Nothing has been written yet")
    expect(page.get_by_role("group", name="Who are you?")).to_be_visible()
    expect(page.locator(".setup-adds")).to_contain_text(".memex/config.yaml")
    expect(page.locator(".setup-adds")).to_contain_text("bookmarks.md")
    page.get_by_role("button", name="Change folder").click()
    expect(page.get_by_role("img", name="Done")).to_have_count(0)


def test_a_refusal_marks_the_folder_field_and_clears_when_it_changes(
    setup_page: Page, tmp_path: Path
):
    page = setup_page
    field = page.get_by_label("Folder")

    field.fill(str(tmp_path / "i" / "ws"))
    page.get_by_role("button", name="Check folder").click()

    expect(field).to_have_attribute("aria-invalid", "true")
    expect(page.get_by_role("alert")).to_contain_text("install folder")
    field.fill(str(tmp_path / "elsewhere"))
    expect(page.get_by_role("alert")).to_have_count(0)
    expect(field).not_to_have_attribute("aria-invalid", "true")
