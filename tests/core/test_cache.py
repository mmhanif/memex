import hashlib
from pathlib import Path

import pytest

from memex.core.cache import Cache
from memex.core.schema import EntityType
from memex.core.store import Store


def put(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode())


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path


def test_file_in_a_type_folder_is_an_entity_of_that_type(root: Path):
    text = "---\ntitle: Alice Smith\nkind: [team-member]\n---\n"
    put(root, "people/alice-smith.md", text)

    entry = Cache.build(root).get("people/alice-smith.md")

    assert entry is not None
    assert entry.id == "alice-smith"
    assert entry.type is EntityType.PERSON
    assert entry.title == "Alice Smith"
    assert entry.hash == hashlib.sha256(text.encode()).hexdigest()


def test_files_outside_type_folders_and_in_their_subfolders_are_notes(root: Path):
    put(root, "notes/standup.md", "---\ntitle: Standup\n---\n")
    put(root, "readme.md", "---\ntitle: Readme\n---\n")
    put(root, "projects/old/x.md", "---\ntitle: X\n---\n")
    cache = Cache.build(root)
    for rel in ("notes/standup.md", "readme.md", "projects/old/x.md"):
        entry = cache.get(rel)
        assert entry is not None
        assert entry.type is None


def test_plain_note_takes_its_title_from_the_first_heading(root: Path):
    put(root, "ideas.md", "Some intro\n\n# Big ideas\n\n## Smaller\n")
    entry = Cache.build(root).get("ideas.md")
    assert entry is not None
    assert entry.title == "Big ideas"


def test_note_without_title_or_heading_takes_its_filename(root: Path):
    put(root, "scratch-pad.md", "just text\n")
    entry = Cache.build(root).get("scratch-pad.md")
    assert entry is not None
    assert entry.title == "scratch-pad"


def test_unparseable_frontmatter_loads_with_filename_title_and_a_parse_warning(root: Path):
    put(root, "projects/broken.md", "---\ntitle: Broken\nstatus: [active\n---\n# Heading\n")
    entry = Cache.build(root).get("projects/broken.md")
    assert entry is not None
    assert entry.type is EntityType.PROJECT
    assert entry.title == "broken"
    [warning] = entry.warnings
    assert warning.kind == "parse"
    assert warning.line == 4


def test_frontmatter_that_is_not_a_mapping_gets_a_parse_warning(root: Path):
    put(root, "notes/list.md", "---\n- a\n- b\n---\n")
    entry = Cache.build(root).get("notes/list.md")
    assert entry is not None
    assert [w.kind for w in entry.warnings] == ["parse"]


def test_non_utf8_file_loads_read_only_with_a_warning(root: Path):
    (root / "notes").mkdir()
    (root / "notes" / "latin.md").write_bytes("---\ntitle: Caf\xe9\n---\n".encode("latin-1"))
    entry = Cache.build(root).get("notes/latin.md")
    assert entry is not None
    assert entry.read_only
    assert entry.title == "latin"
    assert [w.kind for w in entry.warnings] == ["encoding"]


def test_dot_folders_ignored_paths_and_temp_files_are_not_indexed(root: Path):
    put(root, ".git/notes.md", "x")
    put(root, ".obsidian/workspace.md", "x")
    put(root, ".memex/trash/20261112-090000/people/alice.md", "x")
    put(root, "Archive/2019/old.md", "x")
    put(root, "notes/.a.md.memex-tmp-0f3a9c", "x")
    put(root, "notes/.hidden.md", "x")
    put(root, "notes/keep.md", "x")
    put(root, "notes/diagram.png", "x")

    cache = Cache.build(root, ignore=["Archive/**"])

    assert [entry.rel for entry in cache.files()] == ["notes/keep.md"]


def test_walk_does_not_follow_links_out_of_the_workspace(tmp_path: Path):
    root, outside = tmp_path / "ws", tmp_path / "outside"
    put(outside, "secret.md", "x")
    put(root, "notes/keep.md", "x")
    (root / "escape").symlink_to(outside, target_is_directory=True)
    (root / "notes" / "secret.md").symlink_to(outside / "secret.md")

    cache = Cache.build(root)

    assert [entry.rel for entry in cache.files()] == ["notes/keep.md"]


TODO = """\
---
title: Send deck
owner: alice
requester: bob-jones
status: open
about: data-migration
---
"""


def test_ids_clashing_case_insensitively_are_flagged_ambiguous_on_every_file(root: Path):
    put(root, "notes/Alice.md", "# Alice notes\n")
    put(root, "people/alice.md", "---\ntitle: Alice\nkind: [team-member]\n---\n")
    put(root, "people/bob-jones.md", "---\ntitle: Bob\nkind: [team-member]\n---\n")
    cache = Cache.build(root)

    assert [f.rel for f in cache.files() if f.ambiguous] == ["notes/Alice.md", "people/alice.md"]


def test_reference_to_an_ambiguous_id_resolves_to_nothing_and_is_reported_ambiguous(
    root: Path,
):
    put(root, "notes/Alice.md", "# Alice notes\n")
    put(root, "people/alice.md", "---\ntitle: Alice\nkind: [team-member]\n---\n")
    put(root, "people/bob-jones.md", "---\ntitle: Bob\nkind: [team-member]\n---\n")
    put(root, "todos/2026-11-11-send-deck.md", TODO)
    cache = Cache.build(root)

    todo = cache.get("todos/2026-11-11-send-deck.md")
    assert todo is not None
    assert [(r.field, r.id) for r in todo.references] == [
        ("owner", "alice"),
        ("requester", "bob-jones"),
        ("about", "data-migration"),
    ]
    assert cache.resolve("alice").status == "ambiguous"
    assert cache.resolve("alice").file is None
    assert cache.resolve("Bob-Jones").file == cache.get("people/bob-jones.md")
    assert cache.resolve("data-migration").status == "missing"


def test_list_reference_fields_yield_one_reference_per_id(root: Path):
    put(
        root,
        "projects/data-migration.md",
        "---\ntitle: DM\nstatus: active\ntheme: platform\nteam: [alice, bob]\n"
        "stakeholders:\n  - carol\nlabels: [alice]\n---\n",
    )
    entry = Cache.build(root).get("projects/data-migration.md")
    assert entry is not None
    assert [(r.field, r.id) for r in entry.references] == [
        ("theme", "platform"),
        ("team", "alice"),
        ("team", "bob"),
        ("stakeholders", "carol"),
    ]


def test_mentions_are_collected_from_the_body_but_not_from_code(root: Path):
    body = """\
Met [[alice-smith]] about [[data-migration]].

```
[[in-fenced-code]]
```

~~~python
x = "[[in-tilde-fence]]"
~~~

Use `[[in-inline-code]]` and ``[[in-double-backticks]]`` literally.
Then [[bob-jones]].
"""
    put(root, "notes/1on1.md", "---\ntitle: 1:1\nabout: [[not-a-mention]]\n---\n" + body)
    entry = Cache.build(root).get("notes/1on1.md")
    assert entry is not None
    assert entry.mentions == ("alice-smith", "data-migration", "bob-jones")


def test_store_writes_update_the_cache(root: Path):
    put(root, "projects/x.md", "---\ntitle: X\nstatus: active\n---\n")
    cache = Cache.build(root)
    store = Store(root, on_change=cache.refresh)

    new_hash = store.update_fields(
        "projects/x.md", expected_hash=store.read("projects/x.md").hash, set={"status": "done"}
    )
    created_hash = store.create("people/alice.md", "---\ntitle: Alice\n---\n")

    project = cache.get("projects/x.md")
    assert project is not None
    assert project.fields["status"] == "done"
    assert project.hash == new_hash
    assert cache.resolve("alice").file == cache.get("people/alice.md")
    assert cache.resolve("alice").file.hash == created_hash  # type: ignore[union-attr]


def test_refresh_of_a_deleted_file_drops_it_and_its_id_clash(root: Path):
    put(root, "notes/Alice.md", "x")
    put(root, "people/alice.md", "---\ntitle: Alice\n---\n")
    cache = Cache.build(root)

    (root / "notes" / "Alice.md").unlink()
    cache.refresh("notes/Alice.md")

    assert cache.get("notes/Alice.md") is None
    assert cache.resolve("alice").status == "found"
    assert not any(f.ambiguous for f in cache.files())


def test_refresh_of_an_outside_edit_rereads_the_file(root: Path):
    put(root, "notes/a.md", "# Old\n")
    cache = Cache.build(root)
    put(root, "notes/a.md", "# New\n")
    put(root, "notes/b.md", "# Added\n")
    put(root, ".obsidian/c.md", "# Hidden\n")

    for rel in ("notes/a.md", "notes/b.md", ".obsidian/c.md"):
        cache.refresh(rel)

    assert [(f.rel, f.title) for f in cache.files()] == [
        ("notes/a.md", "New"),
        ("notes/b.md", "Added"),
    ]
