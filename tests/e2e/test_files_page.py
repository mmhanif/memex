"""SPEC §11.8, §2: the Files page per "Files — raw editor" in Paper."""

from pathlib import Path

from playwright.sync_api import Page, expect

from memex.web.app import AppState
from tests.e2e.conftest import origin
from tests.e2e.test_editor import open_file, put, wait_for_disk

BROKEN = (
    "---\ntitle: Vendor call\npeople: [a]\nabout: [ledger\nlabels: [x]\n---\n"
    "## Notes\n\n- one\n  - two\n"
)


def folder_row(app: Page, name: str):
    return app.locator(".tree-folder").filter(has_text=name).first


def test_tree_counts_folders_marks_warnings_and_greys_other_files(
    app: Page, server: AppState, root: Path
):
    put(root, "notes/a.md", "# A\n")
    put(root, "notes/sub/b.md", "# B\n")
    put(root, "notes/bad.md", BROKEN)
    put(root, "org-chart.png", "png")

    open_file(app, server, "notes/bad.md")

    # Counts are every file under the folder; folders without the open file start shut.
    expect(folder_row(app, "notes").locator(".count")).to_have_text("3")
    expect(folder_row(app, "people").locator(".count")).to_have_text("1")
    expect(folder_row(app, "people")).to_have_attribute("aria-expanded", "false")
    expect(folder_row(app, "notes")).to_have_attribute("aria-expanded", "true")

    active = app.locator(".tree-file.selected")
    expect(active).to_contain_text("bad.md")
    expect(active.locator(".warning-dot")).to_have_count(1)
    expect(app.locator(".tree-file").filter(has_text="a.md").locator(".warning-dot")).to_have_count(
        0
    )

    other = app.locator(".tree-file.other").filter(has_text="org-chart.png")
    expect(other).to_contain_text("read-only")
    expect(other.locator("a")).to_have_count(0)
    expect(app.locator("a.tree-file").filter(has_text="org-chart.png")).to_have_count(0)


def test_folders_toggle_open_and_shut(app: Page, server: AppState, root: Path):
    put(root, "people/bo.md", "---\nname: Bo\n---\n")
    app.goto(f"{origin(server)}/#/files")

    people = folder_row(app, "people")
    expect(app.locator(".tree-file").filter(has_text="bo.md")).to_have_count(0)
    people.click()
    expect(people).to_have_attribute("aria-expanded", "true")
    expect(app.locator(".tree-file").filter(has_text="bo.md")).to_be_visible()
    people.click()
    expect(app.locator(".tree-file").filter(has_text="bo.md")).to_have_count(0)


def test_file_header_shows_path_type_and_id_and_opens_the_page(
    app: Page, server: AppState, root: Path
):
    put(root, "notes/vendor-call.md", "---\ntitle: Vendor call\n---\nHi\n")
    open_file(app, server, "notes/vendor-call.md")

    head = app.locator(".file-header")
    expect(app.locator(".editor-path")).to_have_text("notes/vendor-call.md")
    expect(head.locator(".file-meta")).to_have_text("Note · Id vendor-call")
    head.get_by_role("link", name="Open page").click()
    expect(app).to_have_url(f"{origin(server)}/#/e/vendor-call")


def test_rename_or_move_from_the_header_follows_the_file(app: Page, server: AppState, root: Path):
    put(root, "notes/a.md", "# A\n")
    (root / "archive").mkdir()
    open_file(app, server, "notes/a.md")

    app.locator(".file-header").get_by_role("button", name="Rename / move").click()
    path = app.get_by_label("New path")
    expect(path).to_have_value("notes/a.md")
    path.fill("archive/a.md")
    path.press("Enter")

    expect(app.locator(".editor-path")).to_have_text("archive/a.md")
    assert (root / "archive/a.md").read_text("utf-8") == "# A\n"
    assert not (root / "notes/a.md").exists()


def test_delete_from_the_header_moves_the_file_to_the_trash(
    app: Page, server: AppState, root: Path
):
    put(root, "notes/a.md", "# A\n")
    open_file(app, server, "notes/a.md")

    app.once("dialog", lambda d: d.accept())
    app.locator(".file-header").get_by_role("button", name="Delete").click()

    expect(app.locator(".files-editor .hint")).to_contain_text("Pick a file")
    assert not (root / "notes/a.md").exists()


def test_frontmatter_that_wont_parse_shows_the_bar_and_marks_the_line(
    app: Page, server: AppState, root: Path
):
    put(root, "notes/bad.md", BROKEN)
    open_file(app, server, "notes/bad.md")

    bar = app.locator(".editor .validation-bar")
    expect(bar).to_contain_text("Frontmatter won't parse")
    expect(bar).to_contain_text("line 5")
    expect(app.locator(".gutter .error")).to_have_text("5")

    bar.get_by_role("button", name="Go to line 5").click()

    text = app.get_by_label("File text")
    expect(text).to_be_focused()
    assert text.evaluate("el => el.selectionStart") == BROKEN.index("labels:")  # where YAML notices


def test_preview_reads_like_the_entity_page(app: Page, server: AppState, root: Path):
    put(root, "notes/bad.md", BROKEN)
    put(root, "notes/good.md", "---\ntitle: Good one\n---\n## Notes\n\n- one\n  - two\n")

    open_file(app, server, "notes/bad.md")
    preview = app.locator(".preview")
    expect(preview.locator(".preview-title")).to_have_text("bad")
    expect(preview).to_contain_text("Properties unavailable")
    expect(preview.locator(".outline .block-heading")).to_contain_text("Notes")
    expect(preview.get_by_role("button", name="Collapse one")).to_be_visible()

    open_file(app, server, "notes/good.md")
    expect(preview.locator(".preview-title")).to_have_text("Good one")
    expect(preview).not_to_contain_text("Properties unavailable")

    app.get_by_label("File text").fill("---\ntitle: Good one\n---\n## Later\n")
    expect(preview.locator(".block-heading")).to_contain_text("Later")
    wait_for_disk(root / "notes/good.md", "---\ntitle: Good one\n---\n## Later\n")


def test_a_selected_folder_can_be_renamed_from_the_tree_head(
    app: Page, server: AppState, root: Path
):
    put(root, "reading/a.md", "# A\n")
    app.goto(f"{origin(server)}/#/files")
    expect(app.get_by_role("button", name="Rename or move folder")).to_have_count(0)

    folder_row(app, "reading").click()
    app.get_by_role("button", name="Rename or move folder").click()
    path = app.get_by_label("New path")
    expect(path).to_have_value("reading")
    path.fill("library")
    path.press("Enter")

    expect(folder_row(app, "library")).to_be_visible()
    assert (root / "library/a.md").read_text("utf-8") == "# A\n"
