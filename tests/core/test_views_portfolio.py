"""Portfolio: the board and the outline (SPEC §11.3, §8.3)."""

import datetime as dt
from pathlib import Path

import pytest

from memex.core.errors import Validation
from memex.core.views import portfolio_board, portfolio_outline
from tests.core.builder import Builder


@pytest.fixture
def b(tmp_path: Path) -> Builder:
    return Builder(tmp_path / "ws")


def columns(board) -> list[tuple[str | None, list[str]]]:
    return [(c.status, [f.id for f in c.items]) for c in board.columns]


def test_board_puts_projects_in_status_columns_with_cancelled_hidden(b: Builder):
    b.project("later", status="active", due=dt.date(2026, 12, 1))
    b.project("sooner", status="active", due=dt.date(2026, 11, 20))
    b.project("stuck", status="blocked")
    b.project("dropped", status="cancelled")
    b.deliverable("cutover", project="later")
    assert columns(portfolio_board(b.ws)) == [
        ("not-started", []),
        ("active", ["sooner", "later"]),
        ("on-hold", []),
        ("blocked", ["stuck"]),
        ("done", []),
    ]


def test_board_shows_deliverables_when_asked(b: Builder):
    b.project("p")
    b.deliverable("cutover", project="p", status="done")
    assert columns(portfolio_board(b.ws, kind="deliverable"))[4] == ("done", ["cutover"])


def test_board_keeps_a_bad_status_in_a_flagged_column_first(b: Builder):
    b.project("wip", status="wip")
    b.file("projects/bare.md", "---\ntitle: Bare\n---\n")
    board = portfolio_board(b.ws)
    assert columns(board)[0] == (None, ["bare", "wip"])
    assert len(board.columns) == 6


def test_board_kind_must_be_project_or_deliverable(b: Builder):
    with pytest.raises(Validation):
        portfolio_board(b.ws, kind="theme")


def test_theme_chips_leave_out_archived_themes_unless_asked(b: Builder):
    b.theme("platform")
    b.theme("growth", title="Growth")
    b.theme("legacy", archived=dt.date(2026, 1, 1))
    assert [t.id for t in portfolio_board(b.ws).chips] == ["growth", "platform"]
    shown = portfolio_board(b.ws, include_archived=True).chips
    assert [t.id for t in shown] == ["growth", "legacy", "platform"]


def test_theme_filter_keeps_work_under_the_chosen_themes(b: Builder):
    b.theme("platform")
    b.theme("growth")
    b.project("migrate", theme="Platform")
    b.project("launch", theme="growth")
    b.project("loose")
    b.deliverable("cutover", project="migrate")
    b.deliverable("ad", project="launch")
    assert columns(portfolio_board(b.ws, themes=["platform"]))[1] == ("active", ["migrate"])
    board = portfolio_board(b.ws, kind="deliverable", themes=["platform"])
    assert columns(board)[1] == ("active", ["cutover"])
    assert columns(portfolio_board(b.ws))[1] == ("active", ["launch", "loose", "migrate"])


def outline(o) -> list[tuple[str | None, list[tuple[str, list[str]]]]]:
    return [
        (
            g.theme.id if g.theme else None,
            [(p.project.id, [d.id for d in p.deliverables]) for p in g.projects],
        )
        for g in o.themes
    ]


def test_outline_nests_theme_project_deliverable_with_no_theme_last(b: Builder):
    b.theme("platform")
    b.theme("growth")
    b.theme("legacy", archived=dt.date(2026, 1, 1))
    b.project("migrate", theme="platform")
    b.project("archive-db", theme="PLATFORM", status="cancelled")
    b.project("old", theme="legacy")
    b.project("loose")
    b.project("lost", theme="nowhere")
    b.deliverable("schema", project="migrate")
    b.deliverable("cutover", project="migrate", status="done")
    b.deliverable("stray", project="gone")
    o = portfolio_outline(b.ws)
    assert outline(o) == [
        ("growth", []),
        ("platform", [("archive-db", []), ("migrate", ["cutover", "schema"])]),
        ("legacy", [("old", [])]),
        (None, [("loose", []), ("lost", [])]),
    ]
    assert [d.id for d in o.without_project] == ["stray"]
    assert [t.id for t in o.chips] == ["growth", "platform"]


def test_outline_theme_filter_keeps_only_those_themes(b: Builder):
    b.theme("platform")
    b.theme("growth")
    b.project("migrate", theme="platform")
    b.project("loose")
    b.deliverable("stray", project="gone")
    o = portfolio_outline(b.ws, themes=["platform"])
    assert outline(o) == [("platform", [("migrate", [])])]
    assert o.without_project == ()
