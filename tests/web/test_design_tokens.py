"""The design tokens in app.css stay readable in light and dark (issue #39).

Contrast is WCAG 2.x relative luminance. Body-text tokens need AA (4.5:1) on every
surface text sits on; --faint is only for incidental text (counts, placeholders,
"no due date"), so it needs 3:1.
"""

import re

import pytest

from memex.web.state import STATIC

CSS = (STATIC / "css/app.css").read_text("utf-8")

SURFACES = [
    "--page",
    "--well",
    "--selected",
    "--rust-tint",
    "--warn-bg",
    "--info-bg",
    "--conflict-bg",
]
BODY_TEXT = ["--text", "--text-2", "--muted", "--link", "--rust-text", "--green-text"]
PAIRS = (
    [(fg, bg, 4.5) for fg in BODY_TEXT for bg in SURFACES]
    + [("--faint", bg, 3.0) for bg in ("--page", "--well")]
    + [
        ("--accent-text", "--accent", 4.5),
        ("--avatar-text", "--avatar-bg", 4.5),
        ("--me-text", "--me-bg", 4.5),
    ]
)


def _hex_tokens(block: str) -> dict[str, str]:
    return dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})\s*;", block))


def _block(pattern: str) -> str:
    match = re.search(pattern, CSS, re.DOTALL | re.MULTILINE)
    assert match, f"app.css has no block matching {pattern!r}"
    return match.group(1)


LIGHT = _hex_tokens(_block(r"^:root\s*\{(.*?)^\}"))
DARK_BLOCK = r"@media \(prefers-color-scheme: dark\)\s*\{\s*:root\s*\{(.*?)\}"
DARK_OVERRIDES = _hex_tokens(_block(DARK_BLOCK))
SCHEMES = {"light": LIGHT, "dark": {**LIGHT, **DARK_OVERRIDES}}


def _luminance(hex_colour: str) -> float:
    channels = [int(hex_colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_contrast_reference_values():
    # Worked examples from the WCAG definition, so the formula itself is checked.
    assert _contrast("#000000", "#ffffff") == pytest.approx(21.0)
    assert _contrast("#767676", "#ffffff") == pytest.approx(4.54, abs=0.01)


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize(("fg", "bg", "minimum"), PAIRS, ids=[f"{f}-on-{b}" for f, b, _ in PAIRS])
def test_text_tokens_are_readable(scheme: str, fg: str, bg: str, minimum: float):
    tokens = SCHEMES[scheme]

    ratio = _contrast(tokens[fg], tokens[bg])

    assert ratio >= minimum, f"{scheme}: {fg} {tokens[fg]} on {bg} {tokens[bg]} is {ratio:.2f}:1"


def test_dark_mode_redefines_every_colour_token():
    missing = LIGHT.keys() - DARK_OVERRIDES.keys()

    assert not missing, f"dark mode falls back to light values for {sorted(missing)}"
