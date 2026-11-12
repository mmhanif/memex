# Python backend stack

Type: research
Status: resolved
Blocked by:

## Question

Which Python libraries should the backend use, given: offline operation, user-level install from an internal PyPI mirror, enterprise-friendly licences, Python 3.10+ on Windows and macOS? Compare FastAPI/Starlette+uvicorn vs. Flask vs. stdlib `http.server` for a localhost JSON API + static file server; pick a YAML frontmatter library that round-trips without reordering or reformatting user content (python-frontmatter vs. ruamel.yaml); pick a file-watching option (watchdog vs. polling) and a lightweight search option (in-memory scan vs. Whoosh/tantivy/SQLite FTS as a disposable cache). Report licences, maintenance status, Windows compatibility, and any push mechanism for live updates (SSE/WebSocket).

## Research

Findings: [docs/research/backend-stack.md](../../../docs/research/backend-stack.md)

## Answer

Per [backend-stack research](../../../docs/research/backend-stack.md), with user facts (2026-11-11): workstations run **Python 3.14**; OpenTelemetry dependency **acceptable** provided it's disabled.
- Runtime: Python 3.14 target; spec floor 3.11.
- Server: FastAPI (>=0.135, built-in SSE) + plain `uvicorn`, bound to 127.0.0.1. Construct with telemetry disabled (`telemetry={"tracing": False, "metrics": False, "logs": False}`); never install `fastapi[standard]` or an OTel SDK/exporter.
- Frontmatter: ruamel.yaml round-trip mode + in-house `---` splitter (preserves key order, comments, quoting).
- File watching: watchfiles; events are hints only, save-time conflict check is authoritative (ticket 08).
- Search: in-memory scan first; SQLite FTS5 as a disposable cache outside the Workspace only if needed.
