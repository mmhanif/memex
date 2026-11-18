# Memex: build spec

Status: **accepted** (2026-11-12). Sources: the brief in [initial-spec.md](initial-spec.md), the decisions on the map [Memex: build-ready spec](https://github.com/mmhanif/memex/issues/1), the research in [docs/research/](docs/research/), and the vocabulary in [GLOSSARY.md](GLOSSARY.md). Capitalised domain words (Workspace, Entity, Id, Me, Tag, Mention, …) have exactly the meanings given in the glossary.

## 0. How to use this spec

- **Normative words.** "Must" and "never" are requirements. "Should" is a strong default that can be changed with a reason.
- **Test-first.** Every section ends with an **Acceptance** list. Each item is one observable behaviour, tagged with the layer it is tested at:
  - `[core]`: unit or integration test against the shared core library
  - `[REST]`: in-process `TestClient` test
  - `[MCP]`: in-memory MCP client/server test
  - `[e2e]`: Playwright journey
  - `[launcher]`: real-process test
  - `[CI]`: a pipeline job

  Write each item as a failing test before implementing it (see §16).
- **Decision trail.** Each section links the ticket that decided it. If this spec and a ticket disagree, this spec wins; report the disagreement.
- **Drafting calls.** Choices made while writing this spec that no ticket settled are listed in [Appendix A](#appendix-a-drafting-calls). All were accepted.

## 1. Product, scope and phases

Memex is a personal, offline workspace for one manager to track their portfolio of work, their people and the commitments between them, stored as plain Markdown files with YAML frontmatter. It is a local Python server plus a browser single-page app.

### 1.1 Phases

| Phase | Contents |
|---|---|
| **v1 (core)** | File-backed Workspace and editor; Themes, Projects, Deliverables; People (Person View, org tree); To-dos (three views, quick-add, inline capture); Glossary; Bookmarks; Notes and Templates; search and Ctrl-K palette; Dashboard and Portfolio; archive, delete and trash; Broken Reference repair; Settings and Setup; Windows distribution and launch. |
| **Later** | MCP server (§14); Mind Maps (§15); macOS support (§13.7). |

The v1 data model must already support the later phase: Mind Maps and MCP need **no** schema change ([Mind Map views](https://github.com/mmhanif/memex/issues/14), [MCP tool surface](https://github.com/mmhanif/memex/issues/12)). The core library must expose every operation MCP needs (§14) so MCP is an adapter, not new logic.

### 1.2 Fixed constraints (from the brief; not negotiable)

1. **Air-gapped at runtime.** No outbound network request of any kind. All assets (JS, CSS, fonts, icons) are bundled in the wheel. No CDN links.
2. **Localhost only.** Bind `127.0.0.1`, never `0.0.0.0` or `::`.
3. **Zero telemetry.** No tracking, crash reporting or analytics. FastAPI's OpenTelemetry instrumentation is explicitly disabled (§13.1).
4. **No admin rights** to install or run.
5. **Storage is plain files:** standard `.md` files with YAML frontmatter bounded by `---`. No database.
6. **Workspace separate from app code,** so the Workspace can be zipped or backed up on its own.

### 1.3 Environment

- v1 runs on **Windows** workstations with **Python 3.14** and **Chrome 150**. The code stays portable (`pathlib` throughout; Windows-only calls confined to the launcher and shortcut modules) so macOS can follow.
- Single user, single machine. No sharing or sync between copies.
- External edits (VS Code, AI agents, sync tools) are expected while Memex runs.

### 1.4 Out of scope

Multi-user, sharing or sync between machines; any hosted, cloud or mobile variant; recurring To-dos.

## 2. Workspace layout

Decided in [Workspace bootstrap & config](https://github.com/mmhanif/memex/issues/15), [Entity frontmatter schema & reference syntax](https://github.com/mmhanif/memex/issues/7) and [Templates for new Entities](https://github.com/mmhanif/memex/issues/20).

```
<Workspace>/
├── .memex/
│   ├── config.yaml          Workspace config (§3.2)
│   ├── templates/<type>/    custom Templates (§7)
│   └── trash/               deleted files (§8.4)
├── themes/                  one file per Theme
├── projects/                one file per Project
├── deliverables/            one file per Deliverable
├── people/                  one file per Person
├── todos/                   one file per To-do
├── glossary/                one file per Glossary Term
├── notes/                   default home for new Notes (not a type folder)
├── bookmarks.md             all Bookmarks
└── … any other folders and .md files: free-form Notes
```

- **The folder is the type.** A `.md` file directly inside a **type folder** (`themes`, `projects`, `deliverables`, `people`, `todos`, `glossary`) is an Entity of that type. The type is never written into frontmatter.
- **Every other `.md` file is a Note**, including those in `notes/`, at the root, or in any other folder.
- **Dot-folders** (`.memex`, `.git`, `.obsidian`, …) are never shown in the file tree, never indexed, and never read as Notes. Workspace `ignore` globs (§3.2) exclude more paths everywhere: tree, search, views and MCP.
- Non-Markdown files are listed in the Files tree (read-only, not openable in the editor) and otherwise ignored.

## 3. Workspace bootstrap and configuration

Decided in [Workspace bootstrap & config](https://github.com/mmhanif/memex/issues/15) and [Distribution & launch](https://github.com/mmhanif/memex/issues/18).

### 3.1 Two config files

Both are YAML, read and written with ruamel.yaml in round-trip mode. Unknown keys are preserved.

| File | Location | Keys |
|---|---|---|
| **Workspace config** | `<Workspace>/.memex/config.yaml` | `format` (int, `1`), `me` (Person Id), `polling` (bool, default `false`), `ignore` (list of globs), `hidden_templates` (list of `<type>/<name>`) |
| **App config** | `config.yaml` in the per-user Memex folder | `workspace` (absolute path), `port` (int, default `47615`) |

- The **per-user Memex folder** is `%LOCALAPPDATA%\Memex\` on Windows and `~/Library/Application Support/Memex/` on macOS. It is found through one helper. The environment variable `MEMEX_HOME`, when set, overrides it (for tests). The folder also holds `run.json` (§13.4) and `logs/`.
- The presence of `.memex/config.yaml` is what makes a folder a Workspace.

### 3.2 Workspace config semantics

- `me`: the Id of the Person who is Me.
- `polling: true` switches the file watcher to polling mode, for network or synced drives. It is never auto-detected. Changing it requires a relaunch.
- `ignore`: globs relative to the Workspace root (e.g. `Archive/**`). They apply everywhere.
- `hidden_templates`: built-in Templates to hide (§7.1).
- Outside edits to this file apply live through the normal change events (§5.6), except `polling`.

### 3.3 Finding the Workspace

In order:
1. `--workspace <path>` (also written to app config as the remembered path)
2. `workspace` in app config
3. the first-run **Setup page**

`memex-mcp` uses steps 1 and 2. If neither yields a Workspace it exits with a clear error on stderr, because it has no Setup page.

A remembered path that lacks `.memex/config.yaml` is no longer a Workspace. Memex shows the Setup page with that path pre-filled, and nothing is lost.

Switching Workspace means changing the path on Settings and relaunching. Memex never switches while running. Only one Workspace is remembered.

### 3.4 Setup page

- A path field pre-filled with `~/Documents/Memex`. There is no native folder picker.
- The server checks that the path is writable, not inside the app's install folder, and not inside another Workspace (no ancestor contains `.memex/config.yaml`).
- **Adoption:** a non-empty folder can be adopted.
  - Nothing is moved or rewritten. Existing `.md` files become Notes.
  - Existing type folders are read leniently as Entities of that type, and problems are flagged, not fixed.
  - Setup first shows counts ("312 Notes, 4 Persons found") and writes nothing until the user confirms.
- **Me:** Setup asks "Your name" and creates `people/<id>.md` with `kind: [team-member]`, using the default Person Template. If Persons already exist, the user may pick one instead. Memex writes `me: <id>`.
- **Seeding:** `.memex/config.yaml` (with `format: 1`), the six type folders, `notes/`, an empty `bookmarks.md`, and Me's Person file. No Templates are seeded and there is no welcome Note. An empty Dashboard shows a "get started" panel that disappears once any Entity besides Me exists.

### 3.5 Missing and broken pieces

- A type folder, `notes/` or `bookmarks.md` deleted outside the app is treated as empty and recreated on the next write into it. Empty folders are never recreated at startup.
- **Me not set:** `me` is missing or matches no Person. Memex never guesses a replacement.
  - A persistent banner reads "Me isn't set: pick or create".
  - Views that depend on Me (Dashboard waiting-on cards, quick-add defaults, the Directs Mind Map) show the banner in place of their content.
  - Writes that would default to Me fail with `me_not_set`.
- **Unparseable Workspace config:** Memex runs on defaults (polling off, no ignores, Me unset) and shows a banner with the parse error and line number. Settings is read-only and never overwrites the file until it parses again.
- **Workspace format:**
  - **Older** than the app: offer a one-time migration with a preview; nothing changes until the user confirms. v1 ships no migrations.
  - **Newer** than the app: the Workspace opens **read-only**, with an "upgrade Memex" banner. Every write returns `read_only`.

### 3.6 Settings page

One page covering both files:
- Me (pick a Person)
- polling (relaunch needed)
- `ignore` patterns
- Workspace path (relaunch needed)
- port (relaunch needed)
- the **Templates** section (§7.4)
- the running version

Saves to the Workspace config use the same hash check as Notes (§5.3), so conflicts get the usual banner. MCP has no config access.

**Acceptance**
- [core] Setup on an empty folder creates exactly `.memex/config.yaml` (`format: 1`, `me`), the six type folders, `notes/`, empty `bookmarks.md` and Me's Person file.
- [core] Adopting a folder with 3 Notes and a `people/` folder with 1 file reports "3 Notes, 1 Person" and writes nothing until confirmed; after confirmation no pre-existing file's bytes have changed.
- [core] Setup rejects a path inside another Workspace and a path inside the install folder.
- [core] `.git/`, `.obsidian/` and paths matching `ignore` are absent from the tree, search and views.
- [core] With `me: ghost` (no such Person), a quick-add without `@` fails with `me_not_set`.
- [core] An unparseable Workspace config yields defaults plus a config error carrying the line number; a Settings save is refused.
- [core] A Workspace with `format: 2` opens read-only and every write returns `read_only`.
- [REST] `memex` run with no app config and no `--workspace` serves the Setup page.

## 4. Domain model

Decided in [To-do storage: own file or inline checkbox?](https://github.com/mmhanif/memex/issues/2), [Entity frontmatter schema & reference syntax](https://github.com/mmhanif/memex/issues/7), [Entity identity & rename semantics](https://github.com/mmhanif/memex/issues/8) and [Entity lifecycle: delete & archive](https://github.com/mmhanif/memex/issues/16).

### 4.1 Ids

- **The Id is the filename without `.md`** (`people/alice-smith.md` → `alice-smith`). Every `.md` file in the Workspace has an Id, including Notes.
- **Unique across the whole Workspace,** for every type, compared **case-insensitively**. Files in `.memex/trash/` don't count.
  - The app never creates a clash.
  - If outside edits create one, every file involved is flagged **ambiguous**: each still opens and works as a plain file. References to that Id resolve to nothing and are reported as ambiguous.
- **Generated from the title at creation; never changed by title edits.**
- **Id rules** (applied when the app creates or renames):
  1. Convert to ASCII (NFKD, strip combining marks: "José" → `jose`).
  2. Lowercase.
  3. Replace each run of characters outside `a–z0–9` with `-`, and trim leading and trailing `-`.
  4. Cut to at most 60 characters at a `-` boundary where possible.
  5. Empty result → `untitled`.
  6. A Windows reserved name (`con`, `prn`, `aux`, `nul`, `com1`–`com9`, `lpt1`–`lpt9`) or a taken Id → append `-2`, `-3`, … until free.
- **Date-prefixed Ids:** To-dos, and Notes created with a `date` (Meeting and 1:1 Templates), get `YYYY-MM-DD-` + the title rule, within the same 60-character limit (e.g. `2026-11-11-send-revised-deck`). The date is the creation date for To-dos and the Note's `date` for Notes.
- Files created outside the app with other names are accepted as they are.
- **Moving a Note** between folders keeps its Id. **Typed Entities can't leave their type folder**, and changing an Entity's type is not supported.

### 4.2 Frontmatter conventions

- **Shared fields:**
  - `title` (required; for a Glossary Term it is the term; for a Person their name)
  - `created` (`YYYY-MM-DD`, set automatically at creation, never edited by the app afterwards)
  - `labels` (optional list of strings)
- **Dates** are `YYYY-MM-DD` and dates are local to the machine.
- **References** are the target's bare Id: `project: data-migration`, `team: [alice-smith, bob-jones]`. No wiki-link syntax in frontmatter.
- **Unknown fields** are preserved exactly.
- **Plain Notes without frontmatter** are valid. Their display title is the first `# ` heading, else the filename.

### 4.3 Fields by type

`?` = optional. **Bold** = required.

| Type | Fields |
|---|---|
| Theme | **title**, lead?, team?, stakeholders?, labels?, archived? |
| Project | **title**, theme? (one Theme), **status**, lead?, team?, stakeholders?, start?, due?, labels? |
| Deliverable | **title**, **project** (one Project), **status**, lead?, team?, stakeholders?, start?, due?, labels? |
| Person | **title**, **kind** (list, `team-member` and/or `stakeholder`, at least one), manager? (one Person), role?, organisation?, email?, archived? |
| To-do | **title**, **owner** (Person), **requester** (Person; defaults to Me), **status**, due?, completed (automatic), about? (one Theme, Project or Deliverable), source? (a Note's Id) |
| Note | title?, date?, people? (Participants: list of Persons), about? (list of Themes, Projects or Deliverables), labels? |
| Glossary Term | **title** (the term), aliases? (list of strings), labels?; the body is the definition |

All types also carry `created`.

- **Project and Deliverable status:** `not-started` (default), `active`, `on-hold`, `blocked`, `done`, `cancelled`. There is no health/RAG field.
- **To-do status:** `open` (default), `done`, `cancelled`.
  - Moving to `done` or `cancelled` sets `completed` to today.
  - Moving back to `open` removes `completed`.
  - Done To-dos stay in `todos/`.
- **`archived: YYYY-MM-DD`** exists on Themes and Persons only (§8.3).
- **Directs are never stored.** A Direct is a Person whose `manager` is Me. Me may have a manager.
- **Meetings** are Notes with a `date` and Participants. There is no Meeting type.

### 4.4 Tags, Mentions, Labels, Participants

- **Tags** live on the work: the `lead`, `team` and `stakeholders` fields of Themes, Projects and Deliverables. The Person View finds them by reverse lookup. (`lead` is the Lead, not a Tag, but the Person View lists it alongside Tags with the role "Lead".)
- **Mentions** are `[[id]]` in a Note's or Entity's body.
  - They render as links and feed a **"Mentioned in"** list on the target.
  - They are never Tags and never count as references for the `@person` search filter.
  - `[[…]]` inside fenced code blocks or inline code is not a Mention.
- **Labels** are free-text keywords in `labels:`, separate from Tags. Bookmarks are the only place Labels are written inline, as `#label`.
- **Participants** are the `people:` list on a Note. They are never Tags.

### 4.5 Validation: lenient read, strict write

**Reading** never fails.
- A file whose frontmatter won't parse still opens, with a warning bar showing the error, and appears in views with its title taken from its filename.
- A bad field value (wrong enum, bad date, missing required field, wrong-type or unknown reference) is **flagged** where it is shown. The Entity is never hidden. Outside edits are never "fixed" automatically.
- Non-UTF-8 files open read-only with a warning.

**Writing** (from any surface: UI, REST, MCP, Templates) never produces invalid frontmatter. A write is rejected (`validation` or `unknown_reference`) if any of these is broken:

| Rule | Error |
|---|---|
| Required fields present (per §4.3) | `validation` |
| Enums (`status`, `kind` values) valid; error lists the allowed values | `validation` |
| Dates are real `YYYY-MM-DD` dates | `validation` |
| `kind` is non-empty | `validation` |
| A reference names an existing, unambiguous Id | `unknown_reference`, with up to 3 "did you mean" Ids |
| The referenced Entity has the right type (`project` → Project; `theme` → Theme; `owner`, `requester`, `lead`, `team`, `stakeholders`, `manager`, `people` → Person; `about` → Theme, Project or Deliverable; `source` → a Note) | `unknown_reference` |
| `manager` is not the Person themself, and does not create a manager cycle | `validation` |

The app's own writes therefore never create Broken References. Those come only from outside edits.

### 4.6 Broken References

A **Broken Reference** is a frontmatter reference, a Mention, or `me` in config whose Id matches no Entity.
- Flagged inline wherever it is shown.
- Collected on the **Broken references** page (§8.5).
- Never shown as search results.
- References to an **ambiguous** Id are listed on the same page, marked "ambiguous".
- **Manager cycles** created by outside edits are flagged as a validation warning on each Person in the cycle. The org tree breaks the cycle for display.

**Acceptance**
- [core] Id generation: "José's Q3 Plan!" → `joses-q3-plan`; a 100-character title → ≤60 characters ending at a word boundary; "CON" → `con-2`; a second "Data migration" → `data-migration-2`; a title with no ASCII letters or digits → `untitled`.
- [core] A To-do titled "Send revised deck" created on 2026-11-11 gets `2026-11-11-send-revised-deck`.
- [core] `Alice.md` in `notes/` and `alice.md` in `people/` are both flagged ambiguous, and `owner: alice` is reported as an ambiguous reference.
- [core] Editing `title` never renames the file.
- [core] A Project file with `status: wip` loads, is listed, and carries a validation warning naming the field and the allowed values.
- [core] A file with unparseable YAML loads with its filename as title and a parse warning.
- [core] Creating a Deliverable without `project`, or with `project: alice-smith` (a Person), is rejected with the right error code.
- [core] `owner: alise-smith` is rejected with `unknown_reference` suggesting `alice-smith`.
- [core] Setting a To-do to `done` writes `completed: <today>`; setting it back to `open` removes `completed`.
- [core] Setting Bob's manager to Alice when Alice's manager is Bob is rejected; the same cycle written by hand is flagged on both Persons.
- [core] `[[alice-smith]]` inside a fenced code block is not a Mention.

## 5. Storage engine

Decided in [Disk sync & auto-save conflict model](https://github.com/mmhanif/memex/issues/9), [Python backend stack](https://github.com/mmhanif/memex/issues/3) and [Localhost hardening](https://github.com/mmhanif/memex/issues/6).

### 5.1 The path gate

Every surface reaches the filesystem only through one core function, `resolve_workspace_path(rel) -> Path`, defined in [localhost-hardening §5](docs/research/localhost-hardening.md#5-path-traversal-outside-the-workspace). It has two stages.

**Lexical stage**, run on the decoded string. Accept only `/`-separated relative paths. Reject:
- empty paths
- a leading `/` or `\`, or any `\`
- a drive letter
- `:` anywhere
- NUL or control characters
- any `.`, `..` or empty segment
- a segment ending in `.` or space
- a reserved device name (with or without extension, case-insensitive)
- any of `<>"|?*`

These rules apply on every OS.

**Resolution stage:** the `realpath` must be contained in the Workspace's `realpath` (via `commonpath`, `normcase` on Windows). For targets that don't exist yet, resolve the parent strictly.

**Further rules:**
- **Writes** create or overwrite `.md` files and folders only.
- **Walks** never follow links out of the Workspace.
- **Folder deletes** never follow links.
- **Error bodies** contain only Workspace-relative paths.

### 5.2 Reading and the parse cache

- The core keeps an **in-memory parse cache** of every indexed `.md` file:
  - relative path, Id, type
  - raw-bytes SHA-256 **hash**
  - mtime
  - parsed frontmatter (ruamel round-trip) and its parse/validation warnings
  - body text
  - outgoing references and Mentions
- Views, search and reverse lookups (Tags, "Mentioned in", Directs, Broken References) are computed from this cache.
- The cache is built at startup and updated from watcher hints (§5.6) and from the app's own writes.
- The cache is an optimisation only. **The save-time hash check is authoritative,** and anything returned to the client for editing is read from disk.
- Frontmatter is split from the body by an in-house splitter: the file starts with a `---` line and ends frontmatter at the next `---` line. A leading BOM is allowed and preserved.

### 5.3 Version token and hash-checked writes

- The **version token** is the SHA-256 (lowercase hex) of the file's raw bytes. Modification time is never used.
- Every read returns the hash (`ETag` in REST, `hash` in JSON). Every write carries the expected hash (`If-Match` in REST, `expected_hash` in MCP).
- **Write algorithm** (in the core, shared by REST and MCP), all under an in-process **lock per path**:
  1. Reread the file and hash it.
  2. If the hash differs from the expected hash → `conflict`, carrying the current content and hash.
  3. Apply the change.
  4. Write atomically (§5.4).
  5. Update the cache.
  6. Return the new hash.
- **One-field writes** (status clicks, property edits, Tag toggles) follow the same rule. List and view responses carry each Entity's hash, which the client sends back.
- **No automatic retry** anywhere. On conflict the client reloads that Entity and shows "Changed on disk. Try again."
- The few-millisecond race with other processes (MCP, VS Code) is accepted. The next save's hash check catches it.
- **Frontmatter edits** go through ruamel.yaml round-trip, preserving key order, comments and quoting. The body bytes are left untouched. New keys are appended at the end of existing frontmatter. Newly created files use the canonical key order of §4.3.
- **Creating** a file fails with `exists` if the path is taken.

### 5.4 Atomic writes

- Write to a temp file in the same folder, named `.<name>.memex-tmp-<random>`, then `os.replace` it over the target. The watcher and tree ignore this name pattern.
- **Line endings, BOM and trailing newline are preserved** exactly as the file had them. New files use UTF-8, LF and a trailing newline.
- **Windows lock:** if `os.replace` fails with `PermissionError`, retry up to 5 times over about 1 s. Then fail with `locked`. The UI shows a "Couldn't save" banner and keeps the edits in the editor.

### 5.5 Rename id

Available in the UI and through MCP. It has two steps.

1. **Preview** (`dry_run`): lists every file and occurrence that will change ("updates 14 references in 9 files").
2. **Apply:**
   - rename the file
   - rewrite every frontmatter reference to the old Id in every reference field (§4.5), plus `me` in the Workspace config when renaming Me
   - rewrite every `[[old-id]]` Mention in bodies
   - each file is saved individually through the hash-checked write, against the hash captured in the preview
   - files that fail (conflict, lock) are **skipped and reported**; the rest are applied

The new Id must satisfy the Id rules (§4.1) and be free.

### 5.6 Change notification (SSE)

- **watchfiles** events are hints only. On a hint the server rereads the affected paths, updates the cache, and sends a batched `changed` event (debounced about 200 ms) listing `{path, hash}` for each affected path (`hash: null` for deletions).
- The stream is `GET /api/events`. Because every `/api/*` request must carry `X-Memex: 1` (§12), the client reads it with `fetch` and a stream parser, not `EventSource`, and reconnects with backoff.
- **Client behaviour:**
  - on `changed`: reload the tree and the current view's data (coarse invalidation, no dependency tracking)
  - on regaining focus, or after reconnecting: check whether the open file's hash is still current, and reload the tree
  - **own-save echo:** an event whose hash equals the version the client holds for the open file is ignored for that file
- `polling: true` switches watchfiles to polling mode.

### 5.7 Editor auto-save and conflicts (client)

- **Auto-save** fires 1 s after the last keystroke, and immediately on leaving the editor, navigating away, or closing the tab.
- The browser's "Leave site?" prompt is armed while there are unsaved edits, a save is in flight, or a conflict banner is showing. There is no browser-storage backup.
- **File changed on disk, no unsaved edits:** reload in place, keep the cursor and scroll position as closely as possible, and briefly show "Updated from disk".
- **File changed on disk with unsaved edits** (seen via SSE or a `409`): auto-save pauses for that file. A banner offers three choices:
  - **Reload:** discard my edits
  - **Keep mine:** overwrite, sending the new hash
  - **Compare:** a side-by-side line diff computed on the server with `difflib` (`POST /api/diff`)

  There is no three-way merge.
- **Open file deleted or moved outside the app:** a banner says so and the editor keeps its contents. The choices are **Recreate** (save to the original path) or **Close**. The app never follows a rename.
- **Several tabs** are independent clients. The hash check settles conflicts between them.

**Acceptance**
- [core] Every path in the hostile-path table (§16.6) is rejected and leaves disk unchanged.
- [core] Read, then change the file on disk, then save with the old hash → `conflict` carrying the new content and hash; the file holds the outside edit.
- [core] Changing one frontmatter field leaves comments, key order, quoting and every body byte unchanged.
- [core] A CRLF file without a trailing newline, saved through Memex, is still CRLF without a trailing newline; a BOM is kept.
- [core] A write leaves no `.memex-tmp-` file behind, and readers never see a partial file.
- [core] Rename id from `alice` to `alice-smith` rewrites `owner: alice`, `team: [alice, bob]`, `[[alice]]` and `me: alice`, and leaves the text `alice` elsewhere untouched; a file changed after the preview is skipped and reported.
- [core] Moving `projects/x.md` to `notes/x.md` is refused; moving `notes/a.md` to `meetings/a.md` keeps Id `a`.
- [core][windows] With the target held open without share-delete, a save retries and then fails with `locked`.
- [REST][slow] An outside write produces one `changed` event within 5 s carrying the path and new hash; 10 writes within 100 ms produce one batched event.
- [e2e] An outside edit while the editor is dirty shows the conflict banner; **Keep mine** writes the editor's text.
- [e2e] An outside edit while the editor is clean reloads in place and shows "Updated from disk".

## 6. To-dos

Decided in [To-do storage: own file or inline checkbox?](https://github.com/mmhanif/memex/issues/2), [UI layout & core views](https://github.com/mmhanif/memex/issues/11) and [Inline To-do capture](https://github.com/mmhanif/memex/issues/19).

### 6.1 Model

- Each To-do is its own file, `todos/<id>.md`, with exactly one **Owner** and one **Requester** (§4.3).
- A To-do where neither party is Me is allowed. It appears only on those two Persons' Person Views and in search, never in Me's lists.
- The Person View, To-do lists and MCP edit the To-do file directly. **Notes are never rewritten to change a To-do.**

### 6.2 Views

| View | Definition | Grouping |
|---|---|---|
| **Mine** | Owner is Me | Overdue / This week / Later / No date |
| **Waiting on them** | Requester is Me, Owner is not Me | by Owner |
| **Waiting on me** | Owner is Me, Requester is not Me | by Requester |

- "This week" runs through the coming Sunday.
- All three hide `done` and `cancelled` unless **Show completed** is on.
- A To-do where Me is both Owner and Requester appears only in Mine.

### 6.3 Quick-add syntax

Parsed **only on the server** (`POST /api/parse/quick-add` serves the live preview). The same parser is used by the To-dos page, Person View boxes, the Ctrl-K `+` prefix and inline capture.

```
Title words @owner from @requester due:YYYY-MM-DD
```

- **`@token`** not preceded by `from` sets the Owner.
- **`from @token`** sets the Requester.
- **`due:YYYY-MM-DD`** sets the due date.
- The tokens may appear in any order. The **title** is the remaining text, trimmed and with whitespace collapsed. An empty title is an error.
- **`@token` resolves fuzzily** to a Person Id, using the same name matching as search (§9.3): exact Id or title first, then prefix, then fuzzy subsequence; archived Persons are excluded.
  - If it matches no Person, or more than one equally well, that is an error naming the candidates. It is never silently dropped.
- **Defaults:** no Owner → Me; no Requester → Me.
- Repeated `@owner`, `from` or `due:` tokens, or an invalid date, are errors.
- **Pre-fill by context:**
  - in "Waiting on <name>", the box defaults to Owner = that Person and Requester = Me
  - in "<name> is waiting on me", the box defaults to Owner = Me and Requester = that Person

  Typed tokens override the defaults.
- The parse result is `{title, owner, requester, due, errors: [{token, message, candidates?}]}`. Creation uses the default To-do Template (§7).

### 6.4 Inline To-do capture

**Explicit action only.** Nothing converts while the user types or saves.

- **Trigger:** a Note in read mode with unconverted task items shows a bar, "N task items aren't To-dos yet", with **"Create N To-dos"**, which opens a preview.
- **Which lines count:**
  - unchecked task items (`- [ ]`, `* [ ]`, `+ [ ]`) at any indent
  - not inside fenced code or frontmatter
  - not lines whose only content is a To-do Mention (already converted)
  - `- [x]` lines are ignored
- **Preview rows:** a table, one row per item, with the text parsed by the quick-add parser unchanged: a tick, the To-do's title with its body line, Owner and Requester with their avatars, Due and About. Indented sub-lines under an item become the To-do's body. Clicking a row's Owner, Requester, Due or About edits it, and each row can be unticked. A row with errors is tinted rust, with the message under its title and the field at fault open for editing; the footer reads "Fix or untick N rows to continue" and **Create** stays disabled until every ticked row is fixed.
- **Defaults on created To-dos:**
  - `source:` is the Note's Id
  - `about:` is pre-filled only when the Note's frontmatter `about` names exactly one Project or Deliverable
  - `status: open`, `created:` today, Id from the title (§4.1)
  - The Note's Participants are never used to guess the Owner.
- **Confirm runs as all-or-nothing:**
  1. Save any pending edits to the Note, then record the Note's hash when the preview opens.
  2. On confirm, recheck the hash. If it changed: "This Note changed, review again". Reopen the preview; nothing has been written.
  3. Create all To-do files.
  4. Rewrite the Note with the hash check. Each converted item and its sub-lines become `- [ ] [[todo-id]]`, matched by exact text, not line number.
  5. If step 4 conflicts, move the new To-do files to `.memex/trash/` and reopen the preview.
- **Rendering:** in Memex, a task item whose only content is a To-do Mention renders as a **live To-do row** (real status, title, Owner, due). Ticking it edits the **To-do file**. The Note's `[ ]` is decorative and never rewritten again.
- **Reminders:** the Dashboard shows a quiet line "N Notes have To-dos to create" linking to them. `get_entity` reports `unconverted_todos: n` for Notes.

**Acceptance**
- [core] `Send deck @ali from @bo due:2026-11-20` → title "Send deck", Owner `alice-smith`, Requester `bob-jones`, due 2026-11-20.
- [core] `Call vendor` → Owner Me, Requester Me.
- [core] `@zz review` → error on `@zz`, with no To-do created; `@al` matching `alice-smith` and `alan-po` equally → error listing both.
- [core] Mine groups an overdue, a this-Sunday, a next-month and an undated To-do into the four groups, using an injected clock.
- [core] A To-do with Owner Alice and Requester Bob appears on both their Person Views and in none of Me's three views.
- [core] Capture on a Note with `- [ ] Draft plan @alice` plus an indented sub-line creates one To-do (Owner Alice, `source` = the Note, body = the sub-line) and rewrites the item to `- [ ] [[<id>]]`.
- [core] Capture where the Note changes between preview and confirm writes nothing; capture where the Note rewrite conflicts leaves the new To-dos in trash and none in `todos/`.
- [core] `- [x]` items, items in fenced code, and already-converted lines are not offered.
- [e2e] Typing `+Buy milk due:2026-12-01` in Ctrl-K shows a preview row; Enter creates the To-do and it appears in Mine.

## 7. Templates

Decided in [Templates for new Entities](https://github.com/mmhanif/memex/issues/20).

### 7.1 Storage and resolution

- **Built-in Templates** ship in the package as files under `memex/core/templates/<type>/<name>.md`.
- **Custom Templates** live at `.memex/templates/<type>/<name>.md`. A file with the same `<type>/<name>` as a built-in **replaces** it; a new name **adds** a variant. Setup seeds none.
- `hidden_templates: [<type>/<name>, …]` in the Workspace config hides built-ins. Deleting a custom copy brings the built-in back.
- `<type>` is one of `note`, `theme`, `project`, `deliverable`, `person`, `todo`, `glossary`.

### 7.2 Template file format

An Entity-shaped Markdown file. A reserved `template:` block holds the Template's own metadata and is stripped from the created file:

```markdown
---
template:
  name: Meeting        # display name
  default: false
date: "{{date}}"
people: ["{{me}}"]
---
## Agenda

## Notes

## Actions
```

- **Placeholders:** only `{{title}}`, `{{date}}` (today, `YYYY-MM-DD`) and `{{me}}` (Me's Id), substituted in frontmatter values and the body. There is no logic, and unknown placeholders stay as literal text.
- **Defaults only:** values supplied by the form, quick-add or MCP call win over the Template.
- **Fields the app controls never come from a Template:** `title`, `created`, the Id, and required references (`project` on a Deliverable, `owner`/`requester` on a To-do).
- **Copy once:** a Template applies only at creation. No link back is kept and no `template` field is written. Editing a Template never changes existing files.
- **Default Template per type:** the one with `template: {default: true}`.
  - If several claim it, the first alphabetically by `<name>` wins and Settings warns.
  - If none does, **Blank** is the default.
  - **Blank** (no fields, empty body) is always available for every type and can't be hidden or overridden.

### 7.3 Built-in set (★ = default)

| Type | Template | Frontmatter defaults | Body |
|---|---|---|---|
| Note | ★ Blank | none | empty |
| Note | Meeting (`note/meeting`) | `date: {{date}}`, `people: [{{me}}]` | `## Agenda`, `## Notes`, `## Actions` |
| Note | 1:1 (`note/one-on-one`) | `date: {{date}}`, `people: [{{me}}]` | `## Their topics`, `## My topics`, `## Feedback`, `## Actions` |
| Theme | ★ Theme (`theme/theme`) | none | `## Purpose`, `## Notes` |
| Project | ★ Project (`project/project`) | none | `## Goal`, `## Scope`, `## Risks`, `## Decisions` |
| Deliverable | ★ Deliverable (`deliverable/deliverable`) | none | `## Definition of done`, `## Notes` |
| Person | ★ Person (`person/person`) | `kind: [team-member]` | `## About`, `## Goals & development`, `## Running notes` |
| Person | Stakeholder (`person/stakeholder`) | `kind: [stakeholder]` | `## What they care about`, `## How to work with them`, `## Running notes` |
| To-do | ★ Blank | none | empty |
| Glossary Term | ★ Blank | none | empty (the body is the definition) |

### 7.4 Using Templates

- **+ New… form:** a Template dropdown with the default preselected. Switching Template replaces the body and the Template-supplied fields, unless the user has already edited them.
- **Ctrl-K:** "New <Type>" uses the default Template. Each other variant gets its own command, e.g. "New Note: Meeting".
- **Quick-add** (To-dos, Person View boxes) and **outline inline rows** always use the default Template.
- **Context pre-fill:**
  - The Person View has a **New 1:1** button: the Note 1:1 Template with `people: [<me>, <person>]`.
  - "+ Deliverable" from a Project pre-fills `project`.
- **Settings → Templates** lists every Template (built-in and custom, with hidden and broken ones marked).
  - **Customise** copies a built-in to `.memex/templates/` and opens it in the raw editor (`#/f/.memex/templates/…` is reachable from here even though dot-folders are not in the tree).
  - **Hide** / **Show** edit `hidden_templates`.
- **New Notes land in `notes/`.** This covers notes created from + New…, Ctrl-K, New 1:1 and MCP. Notes with a `date` get a date-prefixed Id. **New file here** on the Files page creates a Note in the browsed folder, with the same Template picker.

### 7.5 Broken Templates and validation

- A custom Template whose frontmatter won't parse is listed on Settings with the error and left out of pickers. If it overrides a built-in, the built-in is **not** used in its place.
- Template values go through the normal strict-write validation (§4.5).
  - In the form, an unknown reference is shown as an error to fix before saving.
  - Through MCP the error is `unknown_reference`, naming the Template as the source.
- A broken Template never blocks creation, because Blank always works.

**Acceptance**
- [core] Creating a Project with no Template choice uses `project/project`: the body has the four headings and `created` is today.
- [core] A custom `.memex/templates/note/meeting.md` replaces the built-in; deleting it restores the built-in.
- [core] `hidden_templates: [note/one-on-one]` removes the 1:1 Template from the list; Blank can't be hidden.
- [core] `{{title}}`, `{{date}}` and `{{me}}` are substituted (with an injected clock and Me); `{{foo}}` stays literal; the `template:` block never reaches the created file.
- [core] A Template with `status: active` creates a Project with `active`, but an explicit `status: on-hold` wins.
- [core] A Template with `title: X` or `project: y` has those fields ignored.
- [core] A custom Template with unparseable YAML is excluded and reported, and its built-in namesake is not offered either.
- [core] Two custom Templates claiming `default: true` → the alphabetically first wins, with a warning.
- [core] A Meeting Note titled "Platform sync" created on 2026-11-12 is `notes/2026-11-12-platform-sync.md`.
- [e2e] Create a Project from the + New… form with its default Template, then see it on its Entity page.

## 8. Entity lifecycle: archive, delete, trash, repair

Decided in [Entity lifecycle: delete & archive](https://github.com/mmhanif/memex/issues/16).

### 8.1 Create

Every create goes through one core function: `create_entity(type, fields, body?, template?)`.
1. Apply the Template (§7).
2. Overlay the caller's fields.
3. Validate (§4.5).
4. Generate the Id (§4.1).
5. Write the file with `created: today`.
6. Return the Id and hash.

### 8.2 Update

- **Fields:** a partial set/unset, hash-checked.
- **Body:** a whole-body replace, hash-checked.
- **Append:** add to the end of the body.

All three go through §5.3.

### 8.3 Archive

- **`archived: YYYY-MM-DD`** on Themes and Persons only. Projects, Deliverables and To-dos end via `done`/`cancelled`. Notes and Glossary Terms aren't archived.
- The file, its Id and every reference stay as they are. There's no archive folder.
- **Display:**
  - Hidden by default from reference pickers, the Portfolio Theme filter chips, the People page and Mind Maps, each with a **Show archived** toggle. A Theme's own Mind Map still opens if navigated to.
  - Demoted in search and Ctrl-K, in the same tier as done work.
  - Existing references stay valid and show an **archived** badge. An archived Person remains Owner of their old To-dos.
  - The Entity's page shows "Archived on <date>" with an **Unarchive** button.
- **Guards** (warnings only, never blocks):
  - Archiving a Person shows a checklist of loose ends ("Owner of 3 open To-dos · Lead on 1 active Project · Manager of 2 Persons"), each linking to a filtered list.
  - Archiving a Theme warns about its Projects that aren't `done`/`cancelled`.
  - Archived Managers stay Managers until changed.
- **Me can't be archived.**

### 8.4 Delete and trash

- **No incoming references:** delete after one confirmation.
- **Incoming references:** an impact preview (like Rename id) with two choices:
  - **Replace with…** an Entity of the same type. Every reference and Mention is rewritten to point at it.
  - **Remove references:**
    - optional single fields are cleared
    - the Id is dropped from `team`, `stakeholders`, `people` and `about` lists
    - `[[id]]` Mentions become plain text showing the title

    Remove is **blocked** by required references (a Deliverable's `project`, a To-do's `owner`/`requester`, `me` in config), leaving only Replace.
- **No cascade.** **Me can't be deleted;** change Me in Settings first.
- **Trash:**
  - A deleted file moves to `.memex/trash/<YYYYMMDD-HHMMSS>/<original relative path>`.
  - **Restore** puts it back at its original path only if the Id and the path are both free. Rewritten references are not restored.
  - Trash is never emptied automatically.
  - Files in trash never count for Id clashes and are never read as Entities.
- **Files page deletes** of a plain Note or folder use the same rules: a file with incoming references goes through the impact preview. A folder delete is refused while any file inside has incoming references from outside the folder. Type folders can't be deleted.

### 8.5 Broken references page and repair

- `#/broken` lists every Broken Reference and ambiguous reference, grouped by the missing Id.
- Each group, and each inline flag, offers three repairs:
  - **Replace with…:** pick an Entity of the right type; every occurrence is rewritten.
  - **Remove:** the same rules as delete (required references can't be removed).
  - **Create:** a new Entity with that Id, of the type its references imply. Disabled if the references disagree about the type.
- No automatic guessing.

### 8.6 Through MCP

Archive and unarchive go through `update_fields`. There is no delete tool and there are no repair tools. List and search hide archived Entities by default, with an `include_archived` option.

**Acceptance**
- [core] Archiving Alice sets `archived: <today>`. She disappears from pickers and the People page but still shows (badged) as Owner on her To-dos. Search ranks her with done work.
- [core] Archiving or deleting Me is refused.
- [core] Deleting a Person with no references moves the file to `.memex/trash/<stamp>/people/<id>.md`.
- [core] Delete with Replace rewrites every reference and Mention to the replacement and moves the file to trash.
- [core] Delete with Remove clears `lead`, drops the Id from `team` lists and turns `[[id]]` into the title; Remove is refused when a To-do names the Person as Owner.
- [core] Restore fails cleanly when the Id has since been reused.
- [core] Broken Reference **Create** makes `people/zed.md` when `owner: zed` and `team: [zed]` both imply Person; it is disabled when `project: zed` and `owner: zed` disagree.

## 9. Search and the command palette

Decided in [Search & command palette](https://github.com/mmhanif/memex/issues/13), refined by [Testing strategy](https://github.com/mmhanif/memex/issues/21).

### 9.1 One engine

- There is one core `search(query, types?, limit?, offset?, include_archived?)`, shared by REST and MCP. It runs over the parse cache (§5.2): an in-memory word index derived from that cache, updated per file and never written to disk, keeps it within budget ([ADR 0001](docs/adr/0001-in-memory-word-index-for-search.md)).
- **Performance budget:** p95 ≤ 50 ms on a 5,000-file / 50 MB Workspace (§16.8). Exceeding it is the trigger for adding SQLite FTS5 as a disposable cache stored **outside** the Workspace. No FTS5 until then.
- **Query parsing** (free text and filter tokens) is server-only. The response includes the parsed filter state and any token errors, so chips can render them.

### 9.2 What's indexed

- **As text:** Id, title, Glossary `aliases`, Labels, Person `role`/`organisation`/`email`, and the body of every indexed `.md` file (Entities, Notes, and files with invalid frontmatter).
- **Bookmarks:** each Bookmark line is its own result, indexed by title, URL, note and Labels.
- **Not indexed as text:** reference fields (`team`, `lead`, `owner`, …). They are reached through the `@person` filter.
- **Skipped:** dot-folders, `ignore` matches and non-Markdown files.

### 9.3 Matching

- Matching ignores case and accents. Space-separated words must all match (AND). `"quoted phrases"` must match exactly.
- **Names** (Id, title, aliases) use **fuzzy subsequence** matching (`dmig` → `data-migration`). Everything else uses **word-prefix** matching. No stemming and no regex.

### 9.4 Filters

- **Tokens:**
  - `type:<t>[,<t>]`
  - `status:<s>[,<s>]`
  - `@person`
  - `label:<l>[,<l>]`
  - due filters: `due<YYYY-MM-DD`, `due>YYYY-MM-DD`, `due:overdue`, `due:today`, `due:this-week` (through Sunday), `due:none`
- Different filters combine with AND; comma-separated values within one filter combine with OR. A query of only filters is valid.
- `@person` resolves like quick-add (§6.3) and matches any **frontmatter** reference to that Person (Lead, team, stakeholders, Owner, Requester, Participants, Manager), not Mentions. An unresolved `@` is an error, never dropped.
- Chips and typed tokens edit the same filter state.

### 9.5 Ranking

Ranked in tiers:
1. exact Id or title
2. Id or title starts with the query
3. fuzzy name match (closer first)
4. alias match
5. Label or Person-field match
6. body-only match

- Within a tier, ties break by status group (open/active/not-started → on-hold/blocked → done/cancelled/archived), then by mtime, newest first. Themes and plain Notes count as open.
- No ranking by how often things are opened.
- Done, cancelled and archived items are **demoted, never hidden**: they are greyed and carry a badge. The search page's **Hide completed** chip is off by default; an explicit `status:` filter overrides it.
- Broken References never appear as results.

### 9.6 Palette (Ctrl-K)

- The top-bar search box opens the palette. Queries are debounced about 100 ms.
- **Empty:** the 8 most recently opened Entities or files in this browser (localStorage; a convenience only), then a few top commands.
- **Typing** shows sections:
  - **Go to:** Entities, Notes and Views from tiers 1–5, up to 8
  - **Commands:** up to 4
  - **In text:** body and Bookmark hits with a one-line snippet, up to 5
  - a final row, **See all results for '…'**, which opens `#/search?q=…`

  Views and commands are a static list in the frontend, matched in the browser and merged in.
- **Look:** a centred modal over a scrim: the query box (with an Esc hint), the grouped rows, and a footer of key hints (↑↓ move, ↵ open, Ctrl ↵ new tab, `>` commands, `+` add To-do).
- **Row:** type icon, title with the query's words in bold, and a muted context line: the type and its context (a Project's Theme, a Deliverable's Project, a To-do's Owner → Requester, or a Note's folder; Me shows as "Me"). An In text row puts the Note's folder (else the type) after the title and the snippet under it. The selected row shows ↵.
- **Prefixes:**
  - `>` limits the palette to commands.
  - `+` turns it into To-do quick-add with a live preview row (server-parsed). Enter creates and closes; Shift-Enter creates and stays open.
- **Keys:** ↑/↓ move, Enter opens, Ctrl-Enter opens in a new tab, Esc closes.
- **Commands** include:
  - "New <Type>" and "New <Type>: <Template>"
  - every named view
  - "Quit Memex"
  - "Settings"
  - "Broken references"
  - "Trash"

### 9.7 Search page (`#/search?q=…`)

- The heading counts the results ("7 results for ‘cutover’"). A query box (with a hint at the filter tokens) and chips (Type, Status, Person, Label, Due, Hide completed) sit under it; filters already in the query show as removable chips.
- One ranked list, with per-type counts as tabs over it ("All 7", "To-do 3", …) that act as quick filters. The counts ignore the `type:` filter, so the tabs stay while one is picked; All clears it.
- Each row shows title, type badge, status badge (a dot for work, a box for an open To-do, a pill once done, cancelled or archived), a context line and up to 2 highlighted snippets. The context line adds to the palette's: the Lead and due date for work ("Data Migration · lead Alice Smith · due 11 Dec"); the due or completed date and the `about` for To-dos; the date and Labels for Notes ("notes/ · Tue 17 Nov · #one-on-one"). Done, cancelled and archived rows are greyed.
- 50 results at a time, with **Show more** for the next 50.

### 9.8 Opening a hit

- An Entity opens `#/e/<id>`; a Person opens their Person View; a Note opens `#/f/<path>`.
- A body hit scrolls to the first match and highlights it briefly.
- A Bookmark opens its URL in a new browser tab on Enter. The app never fetches it. Alt-Enter jumps to the Bookmark's line in `#/bookmarks`.

**Acceptance**
- [core] `dmig` ranks `data-migration` (tier 3) above a Note whose body contains "dmig" (tier 6).
- [core] `type:project status:active,blocked @alice` returns only active or blocked Projects with Alice in a reference field, and excludes a Project that only Mentions `[[alice]]`.
- [core] `due:this-week` with the clock on Wednesday includes Sunday and excludes next Monday.
- [core] A done Project with an exact title match is still returned, ranked below an active one in the same tier.
- [core] `"revised deck"` matches the exact phrase only; `revis dec` matches by word-prefix.
- [core] Accented "José" is found by `jose`.
- [core] `@nobody` returns a token error, not unfiltered results.
- [core] Each Bookmark line is its own result.
- [CI] The perf job holds p95 ≤ 50 ms (§16.8).
- [e2e] Ctrl-K, type a Project name, Enter opens its Entity page.

## 10. Bookmarks and Glossary

Decided in [Entity frontmatter schema & reference syntax](https://github.com/mmhanif/memex/issues/7) and [UI layout & core views](https://github.com/mmhanif/memex/issues/11).

### 10.1 Bookmarks

- **Storage:** all Bookmarks live in `bookmarks.md` at the Workspace root, one per list line:

  ```
  - [Title](https://url) optional note #label #label
  ```

  - Lines that don't match (headings, prose, bare URLs) are kept and shown as text. A bare `- https://…` line is treated as a Bookmark with no title.
  - `bookmarks.md` is a Note, so it can be edited raw at `#/f/bookmarks.md`.
- **`#/bookmarks`** shows the rendered list as outline blocks: each heading starts a heading block with the lines under it nested, prose lines are plain text, and each Bookmark shows its title (a bare URL in mono), ↗ and the domain, then its note and `#labels`. Above it, an **Add** form (URL, title, note, Labels) in a well and a Label filter of chips with counts (All, then each Label, most used first); with a Label picked, only its Bookmarks show, without headings. Add appends a line through the hash-checked write.
- Bookmark URLs are only ever opened by the user's browser in a new tab. Memex never fetches them.

### 10.2 Glossary

- One file per term in `glossary/`. The title is the term, `aliases` are alternative spellings, and the body is the definition.
- **`#/glossary`** is an A–Z list: a strip of letters (those with no terms faded, the rest jump to their group), then each letter as a heading block with its terms under it, aliases beside each term ("aka go-live · switchover") and the definition inline with its Mentions as links.

**Acceptance**
- [core] Parsing `- [Wiki](https://w.example) team wiki #ref #eng` gives title "Wiki", URL, note "team wiki" and Labels `ref` and `eng`; a heading line is preserved as text.
- [core] Adding a Bookmark appends exactly one line and preserves the rest of the file byte for byte.
- [core] A Glossary Term with aliases `[SLO]` is found by searching `slo`.

## 11. User interface

Decided in [Frontend architecture & build step](https://github.com/mmhanif/memex/issues/10), [UI layout & core views](https://github.com/mmhanif/memex/issues/11) and [Offline-bundleable frontend libraries](https://github.com/mmhanif/memex/issues/4). The throwaway prototype is on the [`prototype/ui-layout`](https://github.com/mmhanif/memex/blob/prototype/ui-layout/prototype/ui-layout.html) branch (`?variant=B`, board from `?variant=C#/portfolio`).

### 11.1 Architecture

- **No build step** for app code. The browser loads the package's own ES modules through an **import map** in `index.html`.
- **Vendored libraries:**
  - Preact and htm
  - `@preact/signals`
  - markdown-it 15 (raw HTML **off**) with a small in-house task-list rule
  - DOMPurify 3
  - Cytoscape.js (later phase)
  - Lucide SVG icons
  - system font stack

  All are committed as ESM files under `static/vendor/`, pinned in `VERSIONS` (§13.6). A library that only ships in pieces may be bundled once, offline, and the result committed. App code is never bundled.
- **CSP and the import map:** the import map is an inline script, so the CSP's `script-src` carries its `sha256-…` hash. The server computes the hash from the served `index.html` at startup. `'unsafe-inline'` is never used.
- Plain JS with JSDoc types and `// @ts-check`. `tsc --noEmit` checks it in dev and CI only.
- Hand-written CSS with custom-property design tokens (light and dark, following `prefers-color-scheme`). No utility framework, no CSS-in-JS.
- **Client state** (Preact signals). The server is the only source of truth. The client holds exactly three pieces of state:
  1. **Tree:** reloaded on `changed`.
  2. **Open document:** text, loaded hash, and save state `clean`/`dirty`/`saving`/`conflict`/`deleted`.
  3. **Current view data:** refetched on route change or `changed`.

  There is no Entity cache, no normalised store and no offline mode. One tab edits one document at a time.
- **Rendering safety:**
  - Every rendered body goes through markdown-it (`html: false`) and then DOMPurify.
  - Link schemes are limited to `http`, `https`, `mailto` and in-app links. External links get `target="_blank" rel="noopener noreferrer"`.
  - Heading ids are prefixed `user-content-`.
  - Frontmatter values, filenames, titles and snippets are inserted as text, never HTML.

### 11.2 Shell

- A left **sidebar** (Logseq-style, light), fixed at 248px, with no collapse toggle and no narrow-width layout. From top to bottom:
  - a Workspace header: the Memex mark and the Workspace folder (under the home folder as `~/…`)
  - nav rows Home · Portfolio · People · To-dos · Glossary · Bookmarks · Files; the active route's row is highlighted (a file's raw editor lights Files, a Person View lights People). The To-dos row shows how many open To-dos Me owns; the count is hidden at 0 and while Me isn't set.
  - a **Bookmarked** list: the first 10 Bookmarks in `bookmarks.md` order, each showing its title (else its URL) and opening in a new tab like the Bookmarks page, then an **All Bookmarks →** row to `#/bookmarks` when there are more
  - a **Recent** list: the same recently opened Entities and files as the palette's empty state (§9.6), newest first, at most 8
  - **+ New…** (one entry per type, plus Note) and Settings at the bottom. `N` opens the New… menu from anywhere except a text field or an open dialog; Escape closes it.

  Both lists always show their heading; when one is empty it shows a muted line ("No Bookmarks yet" / "Nothing opened yet"). The raw file tree is the Files page, not part of the sidebar.
- A **top bar**: Back and Forward (browser history), the search box (opens Ctrl-K), and, while a file or body is open, its save status (Saved / Unsaved / Saving… / Not saved).
- A **banner strip** under the top bar, full width of Main. Workspace-wide banners stay until the cause is fixed:
  - **Me not set** (amber): names the `me` value that matches no Person, with **Pick a Person** (Settings) and **Create Person**. Not shown while the config doesn't parse, whose banner already says so.
  - **Config error** (rust): the parse error and its line, with **Open config.yaml** (the raw editor).
  - **Read-only** (neutral): the Workspace's format and this Memex's, and `pipx upgrade memex` (§3.5, §13.5).

  File banners belong to the open file or body and pause its auto-save (§5.7): **changed on disk** (Reload / Keep mine / Compare, with the diff below the strip), **deleted or moved outside Memex** (Recreate, for raw files / Close), and **Couldn't save** (Retry), which says when another program has the file locked. After a failed save, typing doesn't retry on its own; Retry does. A conflict or deletion replaces the banner.

### 11.3 Routes

| Route | View |
|---|---|
| `#/home` | **Dashboard** (§11.4) |
| `#/portfolio/board` | Board: five status columns (Cancelled hidden), each with its status dot and count, showing Projects *or* Deliverables. Themes are filter chips (All, each Theme, No theme), shared with the outline. A card shows its title, its Theme (or Project), its status as a pill that opens a status menu (Cancelled last: picking it takes the card off the board), its due day (bold within 7 days, lateness in rust) and its Lead's avatar; a Project's card also lists its blocked and late Deliverables. Blocked cards get a rust edge, Done cards are faded. The eyebrow sums the board ("7 Projects · 1 blocked · 1 due this week"). |
| `#/portfolio/outline` | Outline table: Theme → Project → Deliverable, collapsible (a collapsed Project counts its Deliverables), Projects without a Theme under "No theme". A Project's or Deliverable's Status (the same status menu), Lead, Team, Stakeholders and Due show as text and avatars, and become editable in place when clicked. "+ Project in <Theme>" / "+ Deliverable" rows create inline. The eyebrow counts Themes, Projects and Deliverables. A Board / Outline toggle switches between the two. |
| `#/people` | An eyebrow counting Team Members and Stakeholders, then outline blocks: the org tree from Me (Me's Manager above Me, marked Manager; Directs and their reports below, each with reports collapsible to "N reports"), each Person with their role and the open To-dos between them and Me ("1 waiting on them · 1 on me"); other Team Members not under Me ("reports to …"); and a Stakeholders table (name, organisation, role, Tag count). "+ Team Member" and "+ Stakeholder" open the New Person form with that kind. A Show archived toggle brings archived Persons back, badged. |
| `#/people/<id>` | **Person View** (§11.6). `#/e/<person-id>` redirects here. |
| `#/todos/mine`, `#/todos/waiting-on-them`, `#/todos/waiting-on-me` | One page (§6.2): an eyebrow counting the shown view's open and overdue To-dos, a three-way switch with each view's open count (Mine's equals the sidebar badge), a Show completed toggle, and the quick-add box whose live preview names the title, Owner, Requester and due date and says which list the To-do goes to. The lists are outline blocks: Mine always shows its four groups once anything is open ("This week" says the Sunday it runs through, an empty group says so), the Waiting views a group per Person linking to their Person View. Rows tick in place and show the other party and the due date, with lateness in rust. |
| `#/glossary` | A–Z Glossary |
| `#/bookmarks` | Bookmarks |
| `#/files`, `#/f/<path>` | Raw tree, and the raw whole-file editor (frontmatter included) with a live preview pane. This is the escape hatch for any file. |
| `#/e/<id>` | Entity page (§11.5) |
| `#/search?q=…` | Search page |
| `#/broken` | Broken references |
| `#/trash` | Trash, with Restore |
| `#/settings` | Settings |
| `#/setup` | Setup (shown automatically when there is no Workspace) |
| `#/map/…` | Mind Maps (later phase, §15) |

### 11.4 Dashboard

Home is titled with today's date ("Tuesday, 17 November", by this machine's clock), under a one-line summary of the Due block ("Today · 2 overdue · 2 due this week"). Below it, one outline block per list:

| Block | Contents |
|---|---|
| **Due within 7 days** | Overdue and due-within-7-days Projects and Deliverables that aren't done/cancelled, plus Me's open To-dos (Owner Me); overdue first. Each row leads with how late it is ("2 days late", in rust) or its day ("Fri 20 Nov") |
| **Waiting on them** | Open To-dos with Requester Me and Owner not Me, grouped by Owner |
| **Waiting on me** | Open To-dos with Owner Me and Requester not Me |
| **Blocked work** | Projects and Deliverables with status `blocked` |
| **Directs** | A table: each Direct (with their role) and two counts, Waiting on them (open To-dos they owe Me) and Waiting on me (open To-dos they're waiting on from Me) |
| **Recent notes** | The 10 most recently modified Notes, each with its date, and "N To-dos to create" when it has unconverted task items (§6.4), else its labels and `about` |

While Me isn't set (§3.5), Waiting on them, Waiting on me and Directs show a dashed "Paused until Me is set" note instead of their contents, and Due within 7 days keeps its Projects and Deliverables with a note that Me's To-dos are paused.

The Dashboard also shows the "N Notes have To-dos to create" line (§6.4) and the "get started" panel on an empty Workspace (§3.4).

### 11.5 Entity page

- **Read mode by default.**
- **Header:** an eyebrow with the type and, for a Note, its `date` ("Note · Thu 12 Nov 2026"), for a Project its Theme and for a Deliverable its Project; then the title, editable in place; then **✎ Edit** and the **…** Actions menu.
- A **properties well** shows the typed fields by their frontmatter key, editable in place without entering edit mode: status, dates, Lead, Tags as avatar checklists, and the person pickers. References read as links. Each edit is a hash-checked one-field write.
- On a Note with task items that aren't To-dos yet, a bar between the well and the body reads "N task items aren't To-dos yet" with **Create N To-dos** (§6.4).
- The body is rendered Markdown as **outline blocks**: each heading and every bulleted item has a bullet, and what sits under a heading or item hangs off a guide line. Clicking the bullet of a block with children collapses it (the bullet gets a halo) or expands it; this is a view only and writes nothing. A task item whose only content is a To-do Mention is a live To-do row (§6.4): its box, its title, its Owner when not Me, and its due date, in rust when late. **✎ Edit** switches just the body to a raw `<textarea>` with auto-save (§5.7). The textarea has small helpers: Tab indents, Enter continues lists.
- **Below the body**, each under a section header with a count and a chevron that folds it:
  - related children (a Theme's Projects, a Project's Deliverables), with status, Lead and due date or lateness, and a row to add one
  - To-dos about this Entity, ticked in place; finished ones behind **Show completed (N)**
  - Notes with `about` pointing here, newest first, with **New Note about this**
  - **Mentioned in:** each file that Mentions this Entity, with the first line that Mentions it
- **Actions menu:**
  - Create N To-dos (Notes, §6.4)
  - Rename id
  - Archive (Themes, Persons); Unarchive is on the "Archived on" bar (§8.3)
  - Open file (`#/f/…`)
  - Delete
- Validation warnings appear in an amber bar. Broken References appear in a rust bar ("1 Broken Reference. `stakeholders` points to `marco-ruiz`, which isn't in the Workspace."), with their repair actions under it (§8.5), and are flagged inline where shown.
- **Notes** use the same page: the properties well shows `date`, Participants, `about` and Labels.

### 11.6 Person View

- **Header:** an avatar with their initials, an eyebrow ("Person · Team Member · Direct": their kinds, and Direct when Me is their Manager), the name, Open file, and the "…" Actions menu (§11.5). Archived Persons get the "Archived on" bar.
- **Properties well** (§11.5): kind, Manager, role, organisation, email, and their Directs.
- **Three columns,** each under a heading with a count:
  - **Tagged on:** each item with its type, its status (blocked or lateness in rust), and the role (Lead, Team, Stakeholder), plus a "Tag <name> to…" picker that writes the Tag on the chosen item
  - **Waiting on <name>**
  - **<name> is waiting on me**

  To-do rows tick in place and show due (or lateness), the other party when it isn't Me, and the Note they came from. Each To-do column ends in its own dashed quick-add box, pre-filled by context (§6.3), with the syntax hinted under it. "Show completed" adds finished To-dos.
- **Notes with them** (Notes whose `people` include them, newest `date` first): day, title, the other Participants and Labels; the five newest show, the rest behind "Show N older". The **New 1:1** button sits on this section's header.
- **Below:** the Person's body as outline blocks (§11.5), with Edit body.

### 11.7 Creating and tagging

- **New… menu:** a popover above the sidebar's New… button with a row per type and each type's other Templates as sub-rows ("Note: Meeting", "Note: 1:1", "Person: Stakeholder"; custom ones too, Blank left out). Rows carry hints: the Note folder, the date prefix of dated variants, "needs a Project" on Deliverable. Each row opens + New… with that Template.
- **+ New… form per type:** a modal with the title, a live preview of the new file's path (the Id date-prefixed for a dated Note), then the fields in a properties well. The Template dropdown comes first: each usable Template with its headings, custom ones marked with their path, the default starred, and a Manage Templates link to Settings. Person pickers for Lead, Team, Stakeholders, Owner, Requester, Manager and Participants filter as you type, with the match in bold. A Deliverable requires a Project. Pickers hide archived Entities: the popover says how many matches it hid, and its Include archived switch shows them. Below the well, the Template's body as it will be copied. Create (Ctrl+Enter) opens the new file.
- Inline create rows in the outline, Ctrl-K "New <Type>", and quick-add for To-dos.
- **Tags** are edited from the avatar checklist on any work item, or from "Tag to…" on the Person View.

### 11.8 Files page

- A tree of the Workspace, without dot-folders or ignored paths. Each folder shows how many files it holds; non-Markdown files are listed greyed and read-only. The open file is highlighted, with a dot when it has warnings.
- The open file's header shows its path, type and Id, with Rename / move, Delete and **Open page ↗**.
- **Actions:**
  - New file here (with Template picker)
  - New folder
  - Rename/move
  - Delete (to trash, §8.4)
- Typed Entities can be opened and edited raw, but not moved out of their folder.
- A file with invalid frontmatter opens here with its warning bar; **Go to line N** puts the cursor on the line, which the editor's gutter marks.

**Acceptance**
- [REST] `index.html` is served with a CSP whose `script-src` is `'self'` plus exactly the hash of its inline import map.
- [e2e] Edit a Project body, wait 1 s, and the file on disk has the new text.
- [e2e] Clicking a status on the board card writes the new status, and the card moves column.
- [e2e] Person View: quick-add in "Waiting on Alice" creates a To-do with Owner Alice and Requester Me, and it appears in that column.
- [e2e] Rename id from the Entity page shows the impact preview and, after confirming, the page is at the new route.
- [e2e] A Note containing `<img src=x onerror=alert(1)>`, `[x](javascript:alert(1))` and the rest of the R17 corpus renders with no script execution and no `javascript:` URLs.

## 12. Security

Decided in [Localhost hardening](https://github.com/mmhanif/memex/issues/6). **Rules R1–R20 in [localhost-hardening §8](docs/research/localhost-hardening.md#8-concrete-testable-rules-for-the-spec) are normative and part of this spec.** Each gets at least one test named by its rule ID (§16.6). In summary:

- **Bind** `127.0.0.1` only. On Windows use `SO_EXCLUSIVEADDRUSE`, not `SO_REUSEADDR` (R1–R3; port policy in §13.3).
- **Host allowlist:** exactly `127.0.0.1:PORT` or `localhost:PORT` on every route, including static files; otherwise `421` (R4). Verify at build time how Starlette's `TrustedHostMiddleware` handles the port, and add an explicit test for it.
- **Per-launch secret** (R5–R7):
  - The launcher generates a 256-bit secret and a one-time code, and opens `http://127.0.0.1:PORT/auth?code=…`.
  - `/auth` compares the code in constant time, burns it on first use, sets `memex_session=<secret>; HttpOnly; SameSite=Strict; Path=/`, and redirects `303` to `/`.
  - Every route except `/auth`, `/relaunch` (a static "run memex again" page) and `/launcher/*` (§13.4) needs the cookie, or returns `401`. The SPA treats any `401` as "go to `/relaunch`".
  - The secret never appears in logs or responses.
- **No CORS** headers at all, and no successful preflight (R8).
- **Writes** (R9–R11):
  - every `POST`/`PUT`/`PATCH`/`DELETE` needs an exact `Origin` match (missing or `null` is rejected)
  - `Sec-Fetch-Site` must be `same-origin` or `none`
  - bodies must be `application/json` (otherwise `415`)
  - every `/api/*` request needs `X-Memex: 1` (otherwise `403`)
  - `GET` never changes disk state
- **Path gate** (R12–R16; §5.1). Error bodies never contain absolute paths.
- **XSS and CSP** (R17–R19):
  - rendering as in §11.1
  - every HTML response carries:

    ```
    default-src 'self'; script-src 'self' 'sha256-<importmap>'; style-src 'self';
    img-src 'self' data:; connect-src 'self'; font-src 'self'; object-src 'none';
    base-uri 'none'; form-action 'self'; frame-ancestors 'none'
    ```

    plus `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`
  - JSON responses carry `nosniff`
  - CSP `img-src`/`connect-src` also enforce the air-gap for remote images in Notes
- **MCP** uses stdio only (R20).

**Acceptance:** one `[REST]` or `[core]` test per rule R1–R20, named `test_R<nn>_…` (§16.6).

## 13. Distribution and launch

Decided in [Installing a Python app without admin rights](https://github.com/mmhanif/memex/issues/17) ([research](docs/research/distribution-launch.md)) and [Distribution & launch](https://github.com/mmhanif/memex/issues/18).

### 13.1 Runtime dependencies

| Package | Pin | Notes |
|---|---|---|
| `fastapi` | `>=0.135` | Construct with `telemetry={"tracing": False, "metrics": False, "logs": False}`. Never install `fastapi[standard]` or any OpenTelemetry SDK or exporter. The transitive `opentelemetry-api` is inert and accepted. |
| `uvicorn` | `>=0.30`, **no** `[standard]` | Run programmatically on a socket the launcher bound |
| `ruamel.yaml` | `>=0.19.1,<0.20` | Round-trip frontmatter and config |
| `watchfiles` | `>=1.0` | Change hints |
| `mcp` | `>=2.3,<3` | Later phase. Brings `pywin32` on Windows, used for shortcuts. |
| `pywin32` | on Windows | Shortcuts (v1 needs it even before MCP) |

**Forbidden:** python-frontmatter/PyYAML, Flask/waitress, `http.server`, watchdog, Whoosh, tantivy. Target Python 3.14 (floor 3.11).

### 13.2 Package and install

- **Build:** one pure-Python wheel `memex`, built with hatchling. The vendored front end ships as package data under `memex/static/`, served via `importlib.resources`.
- **Mirror:** published to the internal mirror. The mirror needs cp314 `win_amd64` wheels for the compiled dependencies.
- **Install:**
  1. `py -m pip install --user pipx`
  2. `pipx ensurepath`
  3. `pipx install memex` (dependencies `--only-binary :all:`)

  pip is already configured for the mirror.
- **Fallback:** a documented two-command venv in `%LOCALAPPDATA%\Memex\venv`. uv is allowed for power users. zipapp, shiv and pex are not offered.
- **Entry points:** `memex` (console script) and `memex-mcp` (later phase).

### 13.3 Launch

```
memex [--workspace PATH] [--port N] [--no-browser]
memex shortcuts [--remove]
memex --version
```

- **`memex` is a console app.**
  - The window shows the URL and the log. Closing it or pressing Ctrl-C stops Memex.
  - A rotating log goes to `<per-user folder>/logs/memex.log`. It records Workspace-relative paths only, never Note content or secrets.
  - **Quit Memex** in Ctrl-K (`POST /api/quit`) shuts down cleanly.
- **Port:**
  - `47615` by default, overridable by `port` in app config or `--port`.
  - The launcher binds `127.0.0.1:<port>` itself (`SO_EXCLUSIVEADDRUSE` on Windows) and hands the socket to `uvicorn.Server`.
  - The browser opens only after the server is listening, and the URL with its one-time code is always printed too. `--no-browser` prints without opening.
  - **If the port is busy,** the already-running check (§13.4) runs first. If the listener isn't a verified Memex, try the next 9 ports in order, with a warning that bookmarks won't match this session. If all are taken, exit with a clear error. Never pick a random port.

### 13.4 Already running: `run.json` and challenge-response

- **`run.json`** in the per-user folder holds `{pid, port, workspace, key}`, where `key` is a 256-bit HMAC key generated per launch.
  - It is written after binding, and removed on clean shutdown.
  - It lives under the user profile; on POSIX it is created with mode `0600`.
- **A second `memex`,** finding its port busy and `run.json` present:
  1. Sends `POST /launcher/hello` with a random `nonce`.
  2. The server answers with `HMAC(key, "server" ‖ nonce)` and its `workspace`.
  3. The launcher verifies that MAC (constant time) before trusting the listener.
  4. If verified and the Workspace is the same (compared by `normcase(realpath)`): the launcher sends `POST /launcher/open` with `HMAC(key, "open" ‖ nonce)`. The server answers with a fresh one-time code. The launcher opens the browser, prints "Memex is already running; opened it in your browser" and exits `0`.
  5. If verified but `--workspace` differs: print "Memex is already running on <path>. Quit it first to switch" and exit non-zero.
  6. If verification fails, or `run.json` is missing or stale: treat the listener as a stranger and use port fallback (§13.3). **Never send a code or key to an unverified listener.**
- `/launcher/*` endpoints are exempt from the cookie (they are HMAC-authenticated) but still subject to the Host check.
- `memex-mcp` runs alongside the app with no coordination. Hash-checked writes and the watcher keep them in step.

### 13.5 Shortcuts, upgrade and versions

- **Shortcuts:** `memex shortcuts [--remove]` is opt-in and never run at install. It writes a per-user Start-menu `.lnk` with pywin32 (not PowerShell).
- **Upgrade:** quit Memex, then run `pipx upgrade memex`. If the upgrade fails because Windows has the running `.exe` locked, the message tells the user to quit first. There is no auto-update or update check.
- The version shows in Settings and in `memex --version`.

### 13.6 Vendored front-end files

- A dev-only `scripts/vendor.py` (not in the wheel) reads the pinned manifest `src/memex/static/vendor/VERSIONS`. For each package it:
  1. downloads the npm tarball
  2. checks its `dist.integrity` hash
  3. extracts only the browser files and `LICENSE*`
  4. writes them under `static/vendor/<pkg>/`

  The output is committed. Workstations never fetch anything.
- **Refresh:** bump `VERSIONS`, rerun the script, review the diff (including a grep for `http(s)://`), and commit.
- CI unzips every built wheel and asserts that every manifest file is present (§16.9).

### 13.7 macOS (later phase)

The later phase covers:
- a `~/Applications/Memex.app` or `.command` shortcut
- macOS wheels on the mirror
- a Gatekeeper check
- the per-user folder `~/Library/Application Support/Memex/`
- `0600` files
- a macOS CI job

**Acceptance**
- [launcher] With the port held by a dummy listener, `memex --no-browser` starts on port+1 and warns.
- [launcher] A second `memex` against a running instance prints the hand-off message, exits 0, and its printed code authenticates once.
- [launcher] A second `memex --workspace <other>` exits non-zero with the "already running on" message.
- [launcher] With `run.json` holding a wrong key, the second launch treats the listener as a stranger and falls back to the next port.
- [launcher] With all 10 ports held, `memex` exits non-zero with a clear message.
- [launcher] `POST /api/quit` stops the process and removes `run.json`.
- [core] The log file contains no Note content and no secret after a session of edits.
- [CI] The built wheel contains every file listed in `VERSIONS`.

## 14. MCP server (later phase)

Decided in [MCP integration options](https://github.com/mmhanif/memex/issues/5) and [MCP tool surface](https://github.com/mmhanif/memex/issues/12), amended by [Templates for new Entities](https://github.com/mmhanif/memex/issues/20), [Entity lifecycle: delete & archive](https://github.com/mmhanif/memex/issues/16), [Inline To-do capture](https://github.com/mmhanif/memex/issues/19) and [Workspace bootstrap & config](https://github.com/mmhanif/memex/issues/15).

### 14.1 Shape

- **SDK:** the official `mcp` SDK v2, `MCPServer` decorator API.
- **Transport:** stdio, as a separate process `memex-mcp [--workspace PATH] [--read-only]` spawned by the AI client. It works whether or not the web UI is running.
- **No logic of its own:** tools are thin adapters over the same core library as REST, with the same validation, hash checks and path gate.
- **Writes are allowed.** `--read-only` disables every write tool, and a read-only Workspace (§3.5) behaves the same. A write attempted anyway returns `read_only`.
- **Identity:**
  - Every tool takes a bare **Id**, never a path, and no type is needed.
  - An ambiguous Id → `ambiguous_id`, listing the relative paths.
  - There is no fuzzy lookup in Id parameters; agents call `search` first.
  - Output shows Workspace-relative paths only.
- **Output:** structured content plus a short text summary.
  - Field names match §4.3.
  - References come back as `{id, title}`; Broken References as `{id, broken: true}`.
  - Bodies are raw Markdown.
- **Archived** Entities are hidden from list and search tools unless `include_archived: true`.

### 14.2 Read tools (9)

| Tool | Returns |
|---|---|
| `search(query, types?, limit=20, include_archived?)` | `{id, type, title, status, path, snippets, score_tier}` rows |
| `get_entity(id)` | Typed fields, body, type, path, hash, validation warnings, Broken References, "mentioned in", and `unconverted_todos` for Notes |
| `list_entities(type, status?, theme?, project?, person?, label?, due_before?, include_archived?)` | Summaries: id, title, status, due, lead, hash |
| `list_todos(view = mine \| waiting_on_them \| waiting_on_me, person?, include_done?, due_before?)` | The three To-do views |
| `get_person_view(id)` | Tags, both waiting-on lists, Manager, Directs, recent Notes with them |
| `get_dashboard()` | The Dashboard cards |
| `list_bookmarks(label?)` | Bookmarks |
| `list_broken_references()` | Broken and ambiguous references |
| `list_templates(type?)` | `{type, name, default, fields, body}` |

### 14.3 Write tools (7)

| Tool | Notes |
|---|---|
| `create_entity(type, fields, body?, template?)` | Default Template if `template` is omitted; `"blank"` for none. An explicit `body` replaces the Template body; the Template's frontmatter defaults still apply. Returns the Id. |
| `add_todo(title, owner?, requester?, due?, about?, source?)` | Owner and Requester default to Me (`me_not_set` if Me is unset). Uses the default To-do Template. |
| `update_fields(id, set?, unset?, expected_hash?)` | Partial frontmatter change, including `archived`. Unknown fields are kept. |
| `update_body(id, body, expected_hash)` | Whole-body replace; the hash is **required** |
| `append_to_body(id, markdown, expected_hash?)` | Append to the body |
| `rename_id(id, new_id, dry_run = true)` | The preview first; then `dry_run=false` applies it and reports skipped files |
| `add_bookmark(url, title?, note?, labels?)` | Appends a line to `bookmarks.md` |

- **Hash rule:** without `expected_hash`, the core rereads, applies and writes under the per-path lock. A mismatch returns `conflict` with the current hash and content. There is no retry.
- **References** that are unknown or of the wrong type are rejected, with up to 3 suggestions.
- There are no delete, repair or config tools, and no provenance fields or write log.

### 14.4 Errors, resources, prompts

- **Errors the agent can fix** are `is_error` results: `{code, message, field_errors?: [{field, message, allowed?}], …}`. `code` is one of:
  - `validation`
  - `conflict`
  - `not_found`
  - `ambiguous_id`
  - `unknown_reference`
  - `read_only`
  - `me_not_set`

  Only unexpected failures become `-32603`.
- **Resources:** `memex://entity/{id}` (the raw file with frontmatter, plus `lastModified`) and `memex://bookmarks`. No `resources/list` enumeration, no subscriptions.
- **Prompts:**
  - `one-on-one-prep(person)`
  - `weekly-review`
  - `capture-from-note(note)`: proposes To-dos and creates them with `source` once the user confirms in chat. It uses `add_todo` and then `update_body` with `expected_hash`.
- Ship copy-paste client config snippets for Claude Desktop, `claude mcp add` and VS Code `.vscode/mcp.json`.

**Acceptance**
- [MCP] Every tool has a success test and a test for each error code it can return.
- [MCP] With `--read-only`, `add_todo` returns `read_only`.
- [MCP] `update_body` without `expected_hash` is a validation error; with a stale hash it is `conflict` with the current content.
- [MCP] `create_entity(type="deliverable", fields={project: "alice-smith"})` returns `unknown_reference` with suggestions.
- [MCP] No tool output contains an absolute path.
- [launcher] `memex-mcp` over real stdio answers `initialize` and `search`.

## 15. Mind Maps (later phase)

Decided in [Mind Map views](https://github.com/mmhanif/memex/issues/14). The throwaway prototype is on the [`prototype/mind-maps`](https://github.com/mmhanif/memex/blob/prototype/mind-maps/prototype/mind-maps.html) branch (`?variant=C`, "+n" from `?variant=A`).

- **Read-only** diagrams drawn with Cytoscape.js (`concentric` layout around the focus). Each Entity appears **once**, with one edge per link. Nothing about a map is stored.
- **Node style:**
  - the type sets the shape and fill
  - the border shows status: red blocked, amber on-hold, green active, faded for done or cancelled
  - Me is drawn dark
- **Edge kinds,** each styled and in a legend: **Hierarchy** (Theme→Project→Deliverable; Manager→Person), **Lead**, **Team**, **Stakeholder**.

| Map | Route | Focus | Default edges |
|---|---|---|---|
| Theme | `#/map/theme/<id>` | the Theme | Hierarchy + Lead |
| Directs | `#/map/directs` | Me | Hierarchy (Manager) + Lead |
| Stakeholders | `#/map/stakeholders` | every Person whose kind includes `stakeholder`, grouped by `organisation` (non-clickable group nodes; "No organisation" collects the rest) | Stakeholder + Hierarchy + Lead |
| Entity | `#/map/entity/<id>` | any Entity | as for its type |

- **Toggles:** Team and Stakeholder edges are off by default on the Theme and Directs maps. Done and cancelled work, and archived Entities, are hidden behind toggles.
- **Depth:** 3 levels open from the focus. A boundary node with hidden neighbours gets a **"+n" stub**; clicking the stub opens one more level from that node. **Expand all** and **Reset** restore everything or the default.
- **Interaction:**
  - a single click on a node opens the Entity (Person → Person View)
  - hover shows a tooltip card
  - pan, zoom and **Fit**
  - positions are recomputed every time
- **Placement:**
  - a **Map panel** on every Theme, Project, Deliverable and Person View page, with a **Full screen** link
  - buttons on Portfolio ("Map") and People ("Directs map", "Stakeholders map")
  - Ctrl-K targets
  - no sidebar row
- **Open check:** confirm the "+n" stub as the way to expand with the user when building it.

**Acceptance**
- [core] The graph for a Theme with 2 Projects sharing a Lead contains that Person once, with two Lead edges.
- [core] With depth 3, a 4th-level neighbour is replaced by a "+n" stub carrying the correct count.
- [e2e] Clicking a Project node navigates to `#/e/<id>`.

## 16. Testing and CI

Decided in [Testing strategy](https://github.com/mmhanif/memex/issues/21).

### 16.1 Environment

- The air-gap, no-admin and 127.0.0.1 constraints apply to the **running app** only. Development and CI may use the internet (Node for `tsc`, Playwright's browser download). None of those tools ship.
- The implementing agent runs the portable suite locally (macOS). Tests needing Windows carry `@pytest.mark.windows` and are skipped elsewhere. CI results are read with `gh run view --log-failed`.

### 16.2 Layers and tools

| Layer | Tool | Scope |
|---|---|---|
| core | pytest | Most tests: parsing, validation, references, Ids, Rename id, hash-checked writes, search, Templates, views, quick-add, filter tokens, lifecycle, capture |
| REST | Starlette `TestClient` | Every route: at least one success and one error-mapping test; security rules |
| MCP | SDK in-memory client/server pair | Every tool: success plus each error code |
| e2e | Playwright for Python (pytest-playwright) | About 8 journeys (§16.7) |
| launcher | subprocess | Real `memex` and `memex-mcp` |

No JS unit tests: logic lives server-side, and `tsc --noEmit` type-checks the JS.

### 16.3 Test Workspaces

- Real temp folders (`tmp_path`) built with a **Workspace builder**, e.g. `ws.project("data-migration", theme="platform", lead="alice")`.
- Committed sample Workspaces under `tests/fixtures/` for adoption and lenient reading:
  - invalid frontmatter
  - CRLF
  - BOM
  - missing trailing newline
  - unknown fields
  - Broken References
  - an `.obsidian/` folder
- The **clock** and **Me** are injectable into the core.

### 16.4 External edits and conflicts

- **Deterministic core tests** (§5 Acceptance).
- **`@pytest.mark.slow` watcher tests** use real watchfiles plus SSE with a ≤5 s bounded wait.
- **Windows file-lock test.**

### 16.5 Air-gap

1. **Runtime:** a session-wide pytest fixture makes any non-loopback socket connection raise.
2. **Static:** a CI scan of the source and the built wheel's static files for `http(s)://` URLs, with an allowlist (licence files, comments).
3. **Header:** the CSP is asserted (§12).
4. **E2E:** Playwright records every request and asserts each went to `127.0.0.1` (this also covers R19).

### 16.6 Security tests

- One test per rule, named by ID (`test_R03_…`, …, `test_R20_…`).
- The **hostile-path table** covers every R12 input plus the Windows cases (`C:`, `CON`, `foo.`, `a:b`, `\\?\`), checked on every OS.
- Symlink and junction escapes are tested on Windows.
- A real-socket test asserts the server listens on `127.0.0.1` only.
- The `TrustedHostMiddleware` port check has an explicit test.
- R17 runs as an e2e test over the XSS corpus.

### 16.7 E2E journeys

1. Create a Project from a Template
2. Edit and auto-save
3. An outside edit while dirty → conflict banner → Keep mine
4. To-do quick-add
5. Ctrl-K search and open
6. Person View
7. Rename id
8. Launch-code cookie exchange

All run against a real server and a temp Workspace.

### 16.8 Search performance

- A seeded generator builds a synthetic 5,000-file / 50 MB Workspace with a realistic type mix.
- The `perf` job times about 30 fixed queries (fuzzy names, prefixes, filters, phrases) after warm-up and **fails if p95 > 50 ms**.
- It is not part of the default `pytest` run.

### 16.9 CI (GitHub Actions; private repo, so minutes are billed)

| Trigger | Job | Contents |
|---|---|---|
| every push and PR (required) | `ubuntu-latest` | ruff (lint and format), pyright (standard), `tsc --noEmit`, the portable suite |
| every push and PR (required) | `windows-latest` | the full suite, including `windows`-marked tests and Playwright |
| pushes to `main` | `perf` (Windows) | §16.8 |
| pushes to `main` | `package` (Windows) | build the wheel, check `VERSIONS`, run the static URL scan, install offline into a fresh venv (`--no-index` from a local wheelhouse), smoke test (GET `/`, one vendored file) |

There is no macOS CI until the macOS phase, and no coverage percentage gate.

### 16.10 Release check

[docs/release-checklist.md](docs/release-checklist.md) is a manual check of about ten minutes, run on the real Windows workstation before a version is announced as usable.

## 17. REST API

The browser's only interface. All routes are under the security rules of §12. JSON bodies are `application/json`.

### 17.1 Errors

Error body: `{"error": {"code", "message", "field_errors"?: [{field, message, allowed?}], "current"?: {hash, content}, "suggestions"?: [...], "impact"?: {...}}}`.

| `code` | HTTP status |
|---|---|
| `validation` | 422 |
| `unknown_reference` | 422 |
| `conflict` | 409 (with `current`) |
| `exists` | 409 |
| `has_references` | 409 (with `impact`) |
| `ambiguous_id` | 409 |
| `me_not_set` | 409 |
| `not_found` | 404 |
| `read_only` | 423 |
| `locked` | 503 |
| `bad_path` | 400 |
| `forbidden` | 403 |
| `unauthenticated` | 401 |

### 17.2 Routes

| Method & path | Purpose |
|---|---|
| `GET /auth?code=` | Exchange the one-time code for the session cookie, then `303` to `/` |
| `GET /relaunch` | Static "run memex again" page (no cookie) |
| `POST /launcher/hello`, `POST /launcher/open` | Already-running hand-off (§13.4; HMAC, no cookie) |
| `GET /` and `/static/…` | SPA and assets |
| `GET /api/events` | SSE stream (§5.6) |
| `GET /api/tree` | Workspace tree (files and folders, typed or Note, warnings; `other_files`: non-Markdown files, listed read-only), plus `workspace: {read_only, config_error, me_set}` for the shell's banners |
| `GET /api/files?path=` | Raw file content plus `ETag` |
| `POST /api/files` `{path, content}` | Create a raw file (`exists` if taken) |
| `PUT /api/files` `{path, content}` + `If-Match` | Overwrite a raw file |
| `DELETE /api/files?path=` | Delete a file or folder to trash (§8.4) |
| `POST /api/folders` `{path}` | New folder (Files page, §11.8; `exists` if taken) |
| `POST /api/move` `{from, to, overwrite?}` | Move or rename a file or folder (R14; typed Entities can't leave their folder) |
| `POST /api/diff` `{path, content}` | Side-by-side diff against disk |
| `GET /api/entities?type=&status=&theme=&project=&person=&label=&due_before=&include_archived=` | Entity summaries, each with a hash |
| `GET /api/entities/{id}` | Fields, body, hash, warnings, Broken References, mentioned-in, children, related To-dos and Notes, `unconverted_todos` |
| `POST /api/entities` `{type, fields, body?, template?}` | Create (§8.1) |
| `POST /api/entities/placement` `{type, fields, folder?}` | The `{id, path, created}` a create would use, from `title` (and a Note's `date`); writes nothing. The + New… form's preview (§11.7) |
| `PATCH /api/entities/{id}` `{set?, unset?}` + `If-Match` | Field update |
| `PUT /api/entities/{id}/body` `{body}` + `If-Match` | Body replace |
| `POST /api/entities/{id}/rename` `{new_id, dry_run, hashes?}` | Rename id (`hashes`: the preview's, by path) |
| `POST /api/entities/{id}/delete` `{mode: "plain"\|"replace"\|"remove", replacement?, dry_run, hashes?}` | Guided delete |
| `POST /api/entities/{id}/archive` `{archived}` + `If-Match` | Archive (`archived: <today>`) or Unarchive (§8.3) |
| `POST /api/parse/quick-add` `{text, defaults?}` | Quick-add preview |
| `POST /api/todos/quick-add` `{text, defaults?}` | Create a To-do from quick-add text |
| `GET /api/notes/{id}/capture` / `POST /api/notes/{id}/capture` `{hash, rows}` | Inline capture preview and confirm |
| `GET /api/views/dashboard` | Dashboard cards |
| `GET /api/views/todos?view=&person=&include_done=` | To-do views; without `person`, also each view's open count (`counts`) and the Sunday "This week" runs through (`week_ends`) |
| `GET /api/views/portfolio?mode=board\|outline&kind=&themes=&include_archived=` | Portfolio |
| `GET /api/views/people?include_archived=` | Org tree, other Team Members and Stakeholders table, plus `waiting`: open To-dos between Me and each Person (`on_them`, `on_me`) |
| `GET /api/views/person/{id}` | Person View |
| `GET /api/views/glossary` | Glossary |
| `GET /api/search?q=&limit=&offset=&include_archived=&hide_completed=` | Search results plus parsed filters and token errors. A file row carries `context` and, for the search page's context line, `lead`, `about` (names; Me as "Me"), `due`, `completed`, `date` and `labels` |
| `GET /api/bookmarks?label=` / `POST /api/bookmarks` | Bookmarks list and add. The list gives every line, `labels` (`name`, `count`, most used first) and `total`, both counted over the whole file whatever the filter |
| `GET /api/broken-references` / `POST /api/broken-references/repair` `{id, action, replacement?, type?, dry_run, hashes?}` | Broken references and repair |
| `GET /api/trash` / `POST /api/trash/restore` `{entry}` | Trash list and restore |
| `GET /api/templates?type=` / `POST /api/templates/customise` `{type, name}` | Templates |
| `GET /api/settings` / `PUT /api/settings` + `If-Match` | Both config files (the app-config part needs a relaunch) |
| `GET /api/setup` / `POST /api/setup/scan` `{path}` / `POST /api/setup/apply` `{path, me}` | First-run Setup |
| `POST /api/quit` | Clean shutdown |

**Acceptance:** [REST] each route has a success test and an error-mapping test; R11's snapshot test calls every `GET`.

## 18. Repository layout

```
pyproject.toml                 hatchling; entry points memex, memex-mcp
src/memex/
  core/                        no web or MCP imports
    paths.py                   resolve_workspace_path (§5.1)
    clock.py                   injectable clock
    config.py                  Workspace and app config
    workspace.py               Setup, adoption, format
    frontmatter.py             splitter + ruamel round-trip
    ids.py                     Id rules (§4.1)
    schema.py                  fields and validation (§4.3, §4.5)
    store.py                   hash-checked atomic writes, per-path locks
    cache.py                   parse cache, reverse lookups, Broken References
    watch.py                   watchfiles → cache → change events
    entities.py                create, update, read (Entity page)
    lifecycle.py               Rename id, archive, guided delete, trash, repair
    templates.py  templates/   Template resolution and the built-in set
    todos.py  quickadd.py  capture.py
    search.py  views.py  bookmarks.py
  web/                         FastAPI app, security middleware, routes, SSE
  mcp/                         MCPServer adapter (later phase)
  launcher/                    CLI, socket binding, run.json, hand-off, shortcuts_win.py
  static/                      index.html, app/*.js, css/, icons/, vendor/ + VERSIONS
scripts/vendor.py              dev only
tests/                         core/, rest/, mcp/, e2e/, launcher/, fixtures/, perf/
docs/release-checklist.md
```

### Suggested build order

1. **Core storage:** path gate, frontmatter, Ids, store, cache.
2. Workspace and Setup.
3. Web app and security (R1–R19) plus auth.
4. UI shell, Files page and editor with auto-save and conflicts.
5. **Entities:** schema, create/update, Entity page, Templates.
6. **People and To-dos:** views, quick-add, Person View, Dashboard.
7. Portfolio.
8. Search and palette.
9. Lifecycle: archive, delete, trash, repair, Rename id.
10. Bookmarks and Glossary.
11. Inline capture.
12. Launcher, packaging and the release checklist.

The later phase follows: MCP, then Mind Maps, then macOS.

## Appendix A: Drafting calls

Choices made while writing this spec that no ticket decided. All were reviewed and accepted on 2026-11-12. Each is cheap to change.

1. **Id comparison is case-insensitive** (Windows filesystems are). `Alice.md` and `alice.md` clash.
2. **Reserved-name Ids get `-2`** (`con-2`), the same suffix rule as taken Ids. An empty slug becomes `untitled`.
3. **Only direct children of a type folder are Entities.** Subfolders inside type folders aren't created by the app, and files in them are Notes.
4. **`created` is a date,** not a datetime. Plain Notes without frontmatter take their title from the first `#` heading, else the filename.
5. **New files are UTF-8, LF, with a trailing newline.** Non-UTF-8 files open read-only.
6. **Manager cycles are rejected on write** and flagged when found on read.
7. **Mentions inside code** (fenced or inline) are not Mentions. Rename id and Remove leave them alone.
8. **Quick-add:** only `due:YYYY-MM-DD` (no `due:tomorrow`). Repeated tokens are errors. An ambiguous `@` is an error listing the candidates. Archived Persons don't match.
9. **"Waiting on me"** excludes To-dos where Me is both Owner and Requester; those appear in Mine only.
10. **Dashboard "Due within 7 days"** = non-finished Projects and Deliverables plus Me's own open To-dos. "Recent Notes" = the 10 most recently modified Notes.
11. **SSE via `fetch` streaming,** not `EventSource`, because `EventSource` can't send the required `X-Memex` header.
12. **CSP carries the sha256 of the inline import map.** Chrome treats import maps as inline scripts.
13. **Launcher hand-off protocol** (§13.4): `/launcher/hello` and `/launcher/open` with nonce-based HMAC both ways, and `--no-browser` for tests.
14. **Trash layout:** `.memex/trash/<YYYYMMDD-HHMMSS>/<original path>`. Folder deletes are refused while anything inside has incoming references from outside.
15. **REST surface and error→status mapping** (§17), including new codes `exists`, `has_references`, `locked` and `bad_path`.
16. **`memex-mcp` with no known Workspace** exits with an error.
17. **The Setup-created Me** gets `kind: [team-member]`.
18. **Files page editor** is a split raw textarea plus live preview. Entity pages use read mode plus ✎ Edit.
19. **Windows lock retry:** 5 attempts over about 1 s.
20. **`MEMEX_HOME`** overrides the per-user folder (for tests).
21. **The built-in Person Template sets `kind: [team-member]`.** `kind` is required, and [Templates for new Entities](https://github.com/mmhanif/memex/issues/20) listed no frontmatter defaults for it.
22. **Lifecycle details** (§5.5, §8):
    - A delete whose rewrite skips any file keeps the deleted file, so no Broken References are left behind. Retrying rewrites the rest.
    - Rename id and repair write `me` first. If that write fails, nothing else changes.
    - Every rewrite previews first (`dry_run` defaults to true), and the apply sends the preview's hashes back.
    - **Create** may offer a choice of type when every use allows several (for example, only Mentions). It never guesses.
    - Archive has its own route, so the server's clock sets the date and only Themes and Persons can be archived.
    - Each delete gets its own trash entry folder, which restores as one.
