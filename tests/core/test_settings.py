"""Settings saves to the Workspace config (SPEC §3.6, §7.4 Hide/Show)."""

from pathlib import Path

import pytest

from memex.core.errors import Conflict, UnknownReference, Validation
from memex.core.settings import save_workspace_settings
from tests.core.builder import Builder


@pytest.fixture
def b(tmp_path: Path) -> Builder:
    return Builder(tmp_path / "ws")


def test_hiding_a_template_writes_hidden_templates_and_keeps_other_keys(b: Builder):
    save_workspace_settings(b.ws, b.ws.config_hash(), {"hidden_templates": ["note/one-on-one"]})
    text = b.read(".memex/config.yaml")
    assert "hidden_templates: [note/one-on-one]" in text
    assert "me: ada" in text
    assert b.ws.config.hidden_templates == ("note/one-on-one",)


def test_settings_saves_are_hash_checked(b: Builder):
    stale = b.ws.config_hash()
    save_workspace_settings(b.ws, stale, {"polling": True})
    with pytest.raises(Conflict):
        save_workspace_settings(b.ws, stale, {"polling": False})


@pytest.mark.parametrize(
    "changes",
    [
        {"hidden_templates": ["note/blank"]},
        {"hidden_templates": ["widget/x"]},
        {"hidden_templates": "note/meeting"},
        {"polling": "yes"},
        {"ignore": [1]},
        {"format": 2},
        {"colour": "blue"},
    ],
)
def test_bad_settings_are_rejected(b: Builder, changes: dict):
    with pytest.raises(Validation):
        save_workspace_settings(b.ws, b.ws.config_hash(), changes)


def test_me_must_name_a_person(b: Builder):
    b.theme("platform")
    with pytest.raises(UnknownReference):
        save_workspace_settings(b.ws, b.ws.config_hash(), {"me": "platform"})
    b.person("bob")
    save_workspace_settings(b.ws, b.ws.config_hash(), {"me": "bob"})
    me = b.ws.me()
    assert me is not None
    assert me.id == "bob"
