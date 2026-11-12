from pathlib import Path

import pytest

from memex.core.config import WorkspaceConfig
from memex.core.errors import Conflict, MeNotSet, ReadOnly, Validation
from memex.core.workspace import Workspace


def put(root: Path, rel: str, data: bytes) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "ws"


def test_dot_folders_and_ignored_paths_are_left_out_of_the_workspace(root: Path):
    put(root, ".memex/config.yaml", b"format: 1\nignore:\n  - Archive/**\n")
    put(root, ".git/notes.md", b"# git\n")
    put(root, ".obsidian/workspace.md", b"# obsidian\n")
    put(root, "Archive/2020/old.md", b"# old\n")
    put(root, "notes/kept.md", b"# kept\n")

    ws = Workspace.open(root)

    assert [f.rel for f in ws.cache.files()] == ["notes/kept.md"]


PERSON = b"---\ntitle: Alice Smith\nkind: [team-member]\n---\n"


def test_me_naming_no_person_is_not_set(root: Path):
    put(root, ".memex/config.yaml", b"format: 1\nme: ghost\n")
    put(root, "people/alice-smith.md", PERSON)

    ws = Workspace.open(root)

    assert ws.me() is None
    with pytest.raises(MeNotSet) as e:
        ws.require_me()
    assert e.value.code == "me_not_set"


def test_me_resolves_to_the_person_it_names_ignoring_case(root: Path):
    put(root, ".memex/config.yaml", b"format: 1\nme: Alice-Smith\n")
    put(root, "people/alice-smith.md", PERSON)

    me = Workspace.open(root).require_me()

    assert me.rel == "people/alice-smith.md"


def test_me_naming_an_entity_that_is_not_a_person_is_not_set(root: Path):
    put(root, ".memex/config.yaml", b"format: 1\nme: alice-smith\n")
    put(root, "projects/alice-smith.md", b"---\ntitle: A\nstatus: active\n---\n")

    assert Workspace.open(root).me() is None


def test_unparseable_config_yields_defaults_and_an_error_with_its_line(root: Path):
    put(root, ".memex/config.yaml", b"format: 1\nme: alice\nignore: [Archive/**\npolling: true\n")
    put(root, "Archive/old.md", b"# old\n")

    ws = Workspace.open(root)

    assert ws.config == WorkspaceConfig()
    assert ws.config_error is not None
    assert ws.config_error.line == 4
    assert [f.rel for f in ws.cache.files()] == ["Archive/old.md"]


def test_config_that_is_not_a_mapping_yields_defaults_and_an_error(root: Path):
    put(root, ".memex/config.yaml", b"- format\n- me\n")

    ws = Workspace.open(root)

    assert ws.config == WorkspaceConfig()
    assert ws.config_error is not None


def test_config_keys_are_read(root: Path):
    put(
        root,
        ".memex/config.yaml",
        b"format: 1\nme: alice\npolling: true\nignore: [a/**]\nhidden_templates: [note/meeting]\n",
    )

    config = Workspace.open(root).config

    assert config == WorkspaceConfig(
        format=1, me="alice", polling=True, ignore=("a/**",), hidden_templates=("note/meeting",)
    )


def test_wrongly_typed_config_values_fall_back_to_their_defaults(root: Path):
    put(root, ".memex/config.yaml", b"me: [a, b]\npolling: yes please\nignore: Archive/**\n")

    ws = Workspace.open(root)

    assert ws.config == WorkspaceConfig()


NOTE = b"---\ntitle: Kept\n---\n"


def newer_workspace(root: Path) -> Workspace:
    put(root, ".memex/config.yaml", b"format: 2\n")
    put(root, "notes/kept.md", NOTE)
    return Workspace.open(root)


def test_newer_format_opens_read_only_and_every_write_is_refused(root: Path):
    ws = newer_workspace(root)
    hash_ = ws.store.read("notes/kept.md").hash
    writes = [
        lambda: ws.store.create("notes/new.md", "# New\n"),
        lambda: ws.store.write("notes/kept.md", "changed\n", hash_),
        lambda: ws.store.update_fields("notes/kept.md", hash_, set={"title": "X"}),
        lambda: ws.store.make_folder("themes"),
        lambda: ws.save_config(ws.config_hash(), set={"me": "alice"}),
    ]

    assert ws.read_only
    for write in writes:
        with pytest.raises(ReadOnly) as e:
            write()
        assert e.value.code == "read_only"
    assert (root / "notes/kept.md").read_bytes() == NOTE
    assert not (root / "notes/new.md").exists()
    assert not (root / "themes").exists()
    assert (root / ".memex/config.yaml").read_bytes() == b"format: 2\n"


def test_saving_config_keeps_comments_and_unknown_keys_and_applies_live(root: Path):
    put(root, ".memex/config.yaml", b"# my settings\nformat: 1\nme: ghost  # fix me\nshiny: true\n")
    put(root, "people/alice-smith.md", PERSON)
    ws = Workspace.open(root)

    ws.save_config(ws.config_hash(), set={"me": "alice-smith"})

    assert (root / ".memex/config.yaml").read_bytes() == (
        b"# my settings\nformat: 1\nme: alice-smith # fix me\nshiny: true\n"
    )
    assert ws.require_me().rel == "people/alice-smith.md"


def test_settings_save_is_refused_while_config_does_not_parse(root: Path):
    broken = b"format: 1\nignore: [Archive/**\n"
    put(root, ".memex/config.yaml", broken)
    ws = Workspace.open(root)

    with pytest.raises(Validation):
        ws.save_config(ws.config_hash(), set={"polling": True})
    assert (root / ".memex/config.yaml").read_bytes() == broken


def test_settings_save_with_a_stale_hash_is_a_conflict(root: Path):
    put(root, ".memex/config.yaml", b"format: 1\n")
    ws = Workspace.open(root)
    stale = ws.config_hash()
    put(root, ".memex/config.yaml", b"format: 1\npolling: true\n")

    with pytest.raises(Conflict):
        ws.save_config(stale, set={"me": "alice"})
    assert (root / ".memex/config.yaml").read_bytes() == b"format: 1\npolling: true\n"


def test_settings_save_after_an_outside_edit_broke_the_config_is_a_conflict(root: Path):
    put(root, ".memex/config.yaml", b"format: 1\n")
    ws = Workspace.open(root)
    stale = ws.config_hash()
    put(root, ".memex/config.yaml", b"format: [1\n")

    with pytest.raises(Conflict):
        ws.save_config(stale, set={"me": "alice"})


def test_outside_edit_to_ignore_applies_live(root: Path):
    put(root, ".memex/config.yaml", b"format: 1\n")
    put(root, "Archive/old.md", b"# old\n")
    put(root, "notes/kept.md", b"# kept\n")
    ws = Workspace.open(root)

    put(root, ".memex/config.yaml", b"format: 1\nignore: [Archive/**]\n")
    ws.changed(".memex/config.yaml")
    assert [f.rel for f in ws.cache.files()] == ["notes/kept.md"]

    put(root, ".memex/config.yaml", b"format: 1\n")
    ws.changed(".memex/config.yaml")
    assert [f.rel for f in ws.cache.files()] == ["Archive/old.md", "notes/kept.md"]


def test_outside_edit_that_breaks_the_config_falls_back_to_defaults_live(root: Path):
    put(root, ".memex/config.yaml", b"format: 1\nme: alice-smith\n")
    put(root, "people/alice-smith.md", PERSON)
    ws = Workspace.open(root)

    put(root, ".memex/config.yaml", b"format: 1\nme: [alice-smith\n")
    ws.changed(".memex/config.yaml")

    assert ws.config_error is not None
    assert ws.me() is None


def test_config_deleted_outside_the_app_falls_back_to_defaults_live(root: Path):
    put(root, ".memex/config.yaml", b"format: 1\nme: alice-smith\n")
    put(root, "people/alice-smith.md", PERSON)
    ws = Workspace.open(root)

    (root / ".memex/config.yaml").unlink()
    ws.changed(".memex/config.yaml")

    assert ws.config == WorkspaceConfig()
    assert ws.config_error is not None
