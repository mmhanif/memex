"""The Glossary page (SPEC §10.2)."""

from pathlib import Path

import pytest

from memex.core.views import glossary_view
from tests.core.builder import Builder


@pytest.fixture
def b(tmp_path: Path) -> Builder:
    return Builder(tmp_path / "ws")


def test_terms_are_grouped_a_to_z_ignoring_case_and_accents(b: Builder):
    b.entity("glossary", "slo", title="SLO", body="Service level objective.\n")
    b.entity("glossary", "eta", title="Étape")
    b.entity("glossary", "api", title="api")
    b.entity("glossary", "apex", title="Apex")
    b.entity("glossary", "2fa", title="2FA")
    b.note("notes/slo-notes.md", "# Not a term\n")
    view = glossary_view(b.ws)
    assert [(g.letter, [t.file.title for t in g.terms]) for g in view.groups] == [
        ("#", ["2FA"]),
        ("A", ["Apex", "api"]),
        ("E", ["Étape"]),
        ("S", ["SLO"]),
    ]


def test_each_term_carries_its_aliases_and_its_definition(b: Builder):
    b.entity(
        "glossary",
        "slo",
        title="SLO",
        aliases=["Service level objective", "SLOs"],
        body="The target we hold uptime to.\n",
    )
    [group] = glossary_view(b.ws).groups
    [term] = group.terms
    assert term.file.id == "slo"
    assert term.aliases == ("Service level objective", "SLOs")
    assert term.definition == "The target we hold uptime to.\n"


def test_a_term_with_bad_aliases_still_shows(b: Builder):
    b.file("glossary/odd.md", "---\ntitle: Odd\naliases: 7\n---\nStill here.\n")
    [group] = glossary_view(b.ws).groups
    assert [(t.file.title, t.aliases) for t in group.terms] == [("Odd", ())]
