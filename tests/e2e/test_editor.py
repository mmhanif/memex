"""SPEC §5.7, §11, §16.7 journeys 2, 3 and 8: the Files editor against a real server."""

import time
from pathlib import Path

from playwright.sync_api import Page, expect

from memex.web.app import AppState
from tests.e2e.conftest import origin


def put(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, "utf-8")


def wait_for_disk(path: Path, text: str, timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    while path.read_text("utf-8") != text:
        assert time.monotonic() < deadline, f"disk still has {path.read_text('utf-8')!r}"
        time.sleep(0.05)


def open_file(app: Page, server: AppState, rel: str) -> None:
    app.goto(f"{origin(server)}/#/f/{rel}")
    expect(app.locator(".save-status")).to_have_text("Saved")


def test_edit_and_auto_save(app: Page, server: AppState, root: Path):
    put(root, "notes/a.md", "# A\n")
    open_file(app, server, "notes/a.md")

    app.get_by_label("File text").fill("# A\n\nNew text\n")

    expect(app.locator(".save-status")).to_have_text("Saved", timeout=5000)
    wait_for_disk(root / "notes/a.md", "# A\n\nNew text\n")
    expect(app.locator(".preview")).to_contain_text("New text")


def test_outside_edit_while_dirty_shows_the_conflict_banner_and_keep_mine_wins(
    app: Page, server: AppState, root: Path
):
    put(root, "notes/a.md", "# A\n")
    open_file(app, server, "notes/a.md")

    put(root, "notes/a.md", "# Outside\n")
    app.get_by_label("File text").fill("# Mine\n")

    banner = app.locator(".banner.conflict")
    expect(banner).to_contain_text("changed on disk", timeout=5000)
    time.sleep(1.5)  # auto-save is paused: the outside edit stays
    assert (root / "notes/a.md").read_text("utf-8") == "# Outside\n"

    banner.get_by_role("button", name="Compare").click()
    expect(app.locator(".diff")).to_contain_text("# Outside")
    expect(app.locator(".diff")).to_contain_text("# Mine")

    banner.get_by_role("button", name="Keep mine").click()

    expect(app.locator(".save-status")).to_have_text("Saved")
    expect(banner).to_have_count(0)
    wait_for_disk(root / "notes/a.md", "# Mine\n")


def test_reload_discards_my_edits(app: Page, server: AppState, root: Path):
    put(root, "notes/a.md", "# A\n")
    open_file(app, server, "notes/a.md")
    put(root, "notes/a.md", "# Outside\n")
    app.get_by_label("File text").fill("# Mine\n")
    banner = app.locator(".banner.conflict")
    expect(banner).to_be_visible(timeout=5000)

    banner.get_by_role("button", name="Reload").click()

    expect(app.get_by_label("File text")).to_have_value("# Outside\n")
    expect(app.locator(".save-status")).to_have_text("Saved")
    assert (root / "notes/a.md").read_text("utf-8") == "# Outside\n"


def test_outside_edit_while_clean_reloads_in_place(app: Page, server: AppState, root: Path):
    put(root, "notes/a.md", "# A\n\nline two\n")
    open_file(app, server, "notes/a.md")
    text = app.get_by_label("File text")
    text.focus()
    text.evaluate("el => el.setSelectionRange(4, 4)")

    put(root, "notes/a.md", "# A\n\nline two, edited outside\n")

    expect(app.get_by_role("status").filter(has_text="Updated from disk")).to_be_visible(
        timeout=5000
    )
    expect(text).to_have_value("# A\n\nline two, edited outside\n")
    assert text.evaluate("el => el.selectionStart") == 4
    expect(app.locator(".banner.conflict")).to_have_count(0)


def test_own_saves_are_not_mistaken_for_outside_edits(app: Page, server: AppState, root: Path):
    put(root, "notes/a.md", "# A\n")
    open_file(app, server, "notes/a.md")

    app.get_by_label("File text").fill("# A\nmore\n")
    wait_for_disk(root / "notes/a.md", "# A\nmore\n")
    time.sleep(1.5)  # let the watcher's echo arrive

    expect(app.locator(".banner")).to_have_count(0)
    expect(app.locator(".save-status")).to_have_text("Saved")


def test_file_deleted_outside_keeps_my_text_and_recreate_saves_it(
    app: Page, server: AppState, root: Path
):
    put(root, "notes/a.md", "# A\n")
    open_file(app, server, "notes/a.md")

    (root / "notes/a.md").unlink()

    banner = app.locator(".banner.conflict")
    expect(banner).to_contain_text("deleted or moved", timeout=5000)
    expect(app.get_by_label("File text")).to_have_value("# A\n")
    banner.get_by_role("button", name="Recreate").click()

    expect(app.locator(".save-status")).to_have_text("Saved")
    assert (root / "notes/a.md").read_text("utf-8") == "# A\n"


def test_new_file_from_the_files_page(app: Page, server: AppState, root: Path):
    app.goto(f"{origin(server)}/#/files")
    app.get_by_role("treeitem").filter(has_text="notes").first.get_by_role("button").click()

    app.get_by_role("button", name="File").click()
    app.get_by_label("Note title").fill("Ideas")
    app.get_by_role("button", name="Create").click()

    expect(app.locator(".editor-path")).to_have_text("notes/ideas.md")
    assert (root / "notes/ideas.md").read_text("utf-8") == (
        "---\ntitle: Ideas\ncreated: 2026-11-12\n---\n"
    )


def test_new_file_here_uses_a_template_in_any_folder(app: Page, server: AppState, root: Path):
    (root / "meetings").mkdir()
    app.goto(f"{origin(server)}/#/files")
    app.get_by_role("treeitem").filter(has_text="meetings").first.get_by_role("button").click()

    app.get_by_role("button", name="File").click()
    app.get_by_label("Note title").fill("Platform sync")
    app.get_by_label("Template").select_option("meeting")
    app.get_by_role("button", name="Create").click()

    expect(app.locator(".editor-path")).to_have_text("meetings/2026-11-12-platform-sync.md")
    text = (root / "meetings/2026-11-12-platform-sync.md").read_text("utf-8")
    assert "## Agenda" in text


def test_launch_code_sets_the_cookie_once(page: Page, server: AppState):
    code = server.session.issue_code()

    page.goto(f"{origin(server)}/auth?code={code}")
    expect(page.locator(".rail")).to_be_visible()

    reused = page.request.get(f"{origin(server)}/auth?code={code}", max_redirects=0)
    assert reused.status == 401
