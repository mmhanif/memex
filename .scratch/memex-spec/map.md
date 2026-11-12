Label: wayfinder:map

# Memex: build-ready spec

## Destination

A build-ready `SPEC.md` for Memex (with `GLOSSARY.md` and ADRs) that an agent can implement with no open questions: it covers every feature in `initial-spec.md`, flags a **v1 core** (file-backed workspace and editor, Themes/Projects/Deliverables, People, To-dos, Glossary, Bookmarks), and specifies Mind Maps and MCP as a later phase, far enough that the v1 data model doesn't block them.

## Notes

- Domain: personal productivity / portfolio tracking for one manager. Source brief: [initial-spec.md](../../initial-spec.md). Vocabulary: [GLOSSARY.md](../../GLOSSARY.md); challenge drift against it.
- Skills every session should consult: `grilling` + `domain-modeling` (update GLOSSARY.md inline; ADRs only for hard-to-reverse, surprising trade-offs).
- Fixed constraints (from the brief, not up for debate): air-gapped (no outbound requests, all assets bundled), bind to 127.0.0.1 only, zero telemetry, no admin rights, Markdown + YAML frontmatter, Workspace separate from app code.
- Stack: Python backend preferred; packages from an internal PyPI mirror are allowed (popular, enterprise-friendly licences).
- Research findings live in `docs/research/` (this folder is not a git repo, so no `research/*` branches).

### Settled while charting

- Single user, single machine; no sharing or sync between copies.
- Storage: flat type folders (`themes/`, `projects/`, `deliverables/`, `people/`, `glossary/`, …); one file per Entity; relationships as frontmatter references by stable identifier, not folder nesting.
- One **Person** type with a kind (Team Member / Stakeholder / both). **Me** is a Person flagged in workspace config; hierarchy via a `manager` reference, unlimited depth; **Directs** = Persons whose Manager is Me.
- **To-do** = Owner + Requester (either may be Me), optional link to a Theme/Project/Deliverable. "My to-dos" = Owner is Me; "waiting on them" = Owner them, Requester Me; "they're waiting on me" = the reverse.
- Free-form **Notes** anywhere in the Workspace, optionally tagging Entities; typed Entities sit on top of the generic file-tree + editor.
- Projects, Deliverables and To-dos have a fixed status enum and optional due date; Themes have no status.
- Glossary: one file per term. Bookmarks: a single `bookmarks.md` list with optional per-line tags.
- External edits (VS Code, agents) are expected while the app runs: no stale caching, auto-save must detect on-disk conflicts.
- Mind Maps are read-only (nodes click through to the Entity).
- Environment: workstations run Python 3.14 and Chrome 150.

## Decisions so far

- [Python backend stack](issues/02-backend-stack.md): FastAPI + uvicorn with telemetry disabled, ruamel.yaml round-trip, watchfiles, in-memory search.
- [Offline-bundleable frontend libraries](issues/03-frontend-libraries.md): Preact+htm via import maps, markdown-it + DOMPurify, textarea editor, Cytoscape.js for Mind Maps.
- [MCP integration options](issues/04-mcp-integration.md): official `mcp` SDK, stdio as a separate process, shared core library with the REST API.
- [Localhost hardening](issues/05-localhost-hardening.md): adopt rules R1–R20 (Host allowlist, launch-secret cookie, Origin/CSRF checks, single path gate, CSP).

## Not yet specified

- **Search**: scope (full text vs. frontmatter fields vs. both), index strategy, and how filters (by type, status, Person) combine. Waits on the schema and backend stack.
- **Mind Map rendering**: layout, which edges show for the Theme map vs. the People maps, how deep they expand. Waits on frontend libraries and UI views.
- **Workspace bootstrap**: first-run experience, where workspace config lives, choosing/switching the Workspace folder, seeding folders, how Me is chosen.
- **Entity lifecycle**: deleting or archiving an Entity that others reference; what happens to orphaned To-dos and Tags.
- **Distribution & launch**: how the app gets onto the workstation (wheels from internal PyPI vs. vendored), launcher script, opening the browser, port selection.
- **Templates**: default body content for new Entities of each type.
- **Dashboard / home view**: what Me sees on open (due soon, waiting-on lists, recent edits).
- **Testing strategy** for the spec'd system.

## Out of scope

- Multi-user, sharing, or syncing between machines.
- Any hosted/cloud or mobile variant.
