"""R17 and R19: what a Note renders to in the browser (SPEC §11.1, §12)."""

from pathlib import Path

from playwright.sync_api import Dialog, Page, expect

from memex.web.app import AppState
from tests.e2e.conftest import Requests, origin

XSS_CORPUS = """---
title: <img src=x onerror=alert(1)>
---
# foo

<script>alert(1)</script>

<img src=x onerror=alert(1)>

[x](javascript:alert(1))

[y](JaVaScRiPt:alert(1))

<svg onload=alert(1)></svg>

<iframe src="javascript:alert(1)"></iframe>

<a href="data:text/html,<script>alert(1)</script>">d</a>

[z](data:text/html,<script>alert(1)</script>)

[png](data:image/png;base64,iVBORw0KGgo=)

<a id="foo" name="foo">clobber</a>

- [ ] open task
- [x] done task

[safe](https://example.com/page)
"""


def test_R17_the_xss_corpus_renders_inert(app: Page, server: AppState, root: Path):
    (root / "notes/xss.md").write_text(XSS_CORPUS, "utf-8")
    dialogs: list[str] = []

    def record(dialog: Dialog) -> None:
        dialogs.append(dialog.message)
        dialog.dismiss()

    app.on("dialog", record)
    app.goto(f"{origin(server)}/#/f/notes/xss.md")
    preview = app.locator(".preview")
    expect(preview).to_contain_text("open task")

    found = preview.evaluate(
        """el => {
            const all = [...el.querySelectorAll("*")];
            return {
                scripts: el.querySelectorAll("script, iframe, svg, object, embed").length,
                handlers: all.flatMap(n => [...n.attributes].map(a => a.name))
                    .filter(name => name.startsWith("on")),
                badUrls: all.flatMap(n => ["href", "src"].map(a => n.getAttribute(a)))
                    .filter(v => v && /^\\s*(javascript|data:text)/i.test(v)),
                dataLinks: [...el.querySelectorAll("a[href^='data:']")].length,
                frontmatterImages: el.querySelectorAll(".frontmatter img").length,
            };
        }"""
    )
    assert found == {
        "scripts": 0,
        "handlers": [],
        "badUrls": [],
        "dataLinks": 0,
        "frontmatterImages": 0,
    }
    assert app.evaluate("typeof window.foo") == "undefined"
    assert dialogs == []
    external = preview.get_by_role("link", name="safe")
    expect(external).to_have_attribute("target", "_blank")
    expect(external).to_have_attribute("rel", "noopener noreferrer")
    expect(preview.locator("input[type=checkbox]")).to_have_count(2)


def test_R19_a_remote_image_makes_no_outbound_request(
    app: Page, server: AppState, root: Path, requests_made: Requests
):
    (root / "notes/pic.md").write_text("![](https://example.com/p.png)\n", "utf-8")

    app.goto(f"{origin(server)}/#/f/notes/pic.md")
    expect(app.locator(".preview img")).to_have_count(1)
    app.wait_for_timeout(500)

    assert requests_made.blocked_by_csp == ["https://example.com/p.png"]
    assert requests_made.outbound() == []
