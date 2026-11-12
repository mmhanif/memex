# Research: Python backend stack

Ticket: [02-backend-stack](../../.scratch/memex-spec/issues/02-backend-stack.md)
Researched: 2026-11-11. Versions, licences and `Requires-Python` values come from the PyPI JSON API (`https://pypi.org/pypi/<name>/json`) on that date unless another source is given.

## Question

Which Python libraries should the backend use, given: offline, user-level install from an internal PyPI mirror, enterprise-friendly licences, Python 3.10+ on Windows and macOS? Covers web framework/server, YAML frontmatter round-tripping, file watching, search, and a push channel for live updates.

## A finding to settle first: Python 3.10 is end-of-life

- CPython 3.10 reached **end-of-life on 2026-10-01**. 3.11 is in security-fix mode until 2027-10, 3.12 until 2028-10, and 3.13 until 2029-10 ([Python devguide: Status of Python versions](https://devguide.python.org/versions/)).
- The ecosystem is already moving off 3.10. The latest releases of several candidates require **>=3.11**: starlette 1.10.0, watchdog 7.1.0, tantivy 0.27.0 and sse-starlette 3.7.0. Their last 3.10-compatible releases are starlette 1.7.0, watchdog 6.0.0, tantivy 0.26.2 and sse-starlette 3.5.1 (PyPI release metadata).
- **Implication:** the spec should set the floor at **Python 3.11** (3.12+ preferred). If 3.10 workstations must be supported, the internal mirror needs pinned older versions and a resolver that honours `Requires-Python`. pip does this by default. Someone should check what Python the target workstations actually have.

## 1. Web framework and server

| Option | Latest | Licence | Requires-Python | Notes |
|---|---|---|---|---|
| **FastAPI** | 0.162.5 (2026-11-11) | MIT | >=3.10 | Core deps: starlette>=0.46, pydantic>=2.9, anyio, typing-extensions, typing-inspection, annotated-doc, **opentelemetry-api>=1.44** |
| Starlette | 1.10.0 (2026-10-24) | BSD-3-Clause | >=3.11 | ASGI toolkit that FastAPI is built on |
| **uvicorn** | 0.54.0 (2026-09-25) | BSD-3-Clause | >=3.10 | Core deps: click, h11 (pure Python) |
| Flask | 3.1.3 (2026-02-19) | BSD-3-Clause | >=3.9 | Deps: werkzeug, jinja2, click, itsdangerous, blinker, markupsafe |
| waitress (WSGI server for Flask on Windows) | 3.0.2 (2024-11-16) | ZPL 2.1 | >=3.9 | No release in two years. ZPL is less common, so check it with legal |
| stdlib `http.server` | Python stdlib | PSF | n/a | No dependencies |

Licences: MIT, BSD-3-Clause and Apache-2.0 are all permissive and enterprise-friendly. pydantic is MIT and opentelemetry-api is Apache-2.0 (PyPI).

### FastAPI + uvicorn

- **Binding:** uvicorn's `--host` default is `127.0.0.1` ([uvicorn settings](https://uvicorn.dev/settings/)). The app should still pass `host="127.0.0.1"` explicitly, because the brief requires it.
- **Windows:** uvicorn's `--loop auto` uses asyncio on Windows. uvloop "is not compatible with Windows or PyPy" ([uvicorn settings](https://uvicorn.dev/settings/)). Install plain `uvicorn`, not `uvicorn[standard]`, to keep the dependency set small and pure Python, apart from pydantic-core. pydantic-core ships `win_amd64` and macOS wheels for cp310 to cp313 and later (PyPI file listing).
- **Static SPA:** Starlette's `StaticFiles(directory=..., html=True)` serves `index.html` for directories, and `follow_symlink` defaults to `False` ([Starlette StaticFiles](https://www.starlette.dev/staticfiles/)).
- **Push (SSE built in):** `from fastapi.sse import EventSourceResponse, ServerSentEvent` was "Added in FastAPI 0.135.0". It sends a keep-alive ping comment every 15 s automatically, and resuming through `Last-Event-ID` is done by reading the header yourself ([FastAPI: Server-Sent Events](https://fastapi.tiangolo.com/tutorial/server-sent-events/)). With this, no `sse-starlette` dependency is needed.
- **WebSockets:** these work in FastAPI/Starlette, but uvicorn needs either the `websockets` or the `wsproto` package ([uvicorn settings](https://uvicorn.dev/settings/)). That is an extra dependency SSE doesn't need.
- **Telemetry caveat (important for the zero-telemetry constraint):** since a release between 0.140.0 (2026-07-24, no dependency) and 0.150.0 (2026-10-19, has it), FastAPI depends on `opentelemetry-api` and "provides OpenTelemetry support by default". The `tracing`, `metrics` and `logs` settings default to `True`. Exporters are added only when `FASTAPI_OTEL_AUTO_CONFIGURE=true` and an OTLP endpoint is set ([FastAPI: OpenTelemetry](https://fastapi.tiangolo.com/advanced/opentelemetry/)). The OpenTelemetry API "will only emit telemetry when it is part of an app that uses the OpenTelemetry SDK" ([OpenTelemetry Python docs](https://opentelemetry.io/docs/languages/python/instrumentation/)). Memex will not install the SDK, so nothing leaves the machine. Even so, the spec should:
  - construct the app with `FastAPI(telemetry={"tracing": False, "metrics": False, "logs": False})`;
  - never install `fastapi[standard]`, which pulls in the OTel SDK, the OTLP exporter and `fastapi-cloud-cli`;
  - optionally clear or ignore `FASTAPI_OTEL_AUTO_CONFIGURE` and `OTEL_*` environment variables at startup.

  Alternatively, pin `fastapi>=0.135,<0.150` to get SSE without the OTel dependency, but that means giving up updates.

### Flask

- Flask's docs are explicit that the dev server is not for local single-user use either: "'Production' means 'not development', which applies whether you're serving your application publicly to millions of users or privately / locally to a single user. Do not use the development server when deploying to production" ([Flask: Deploying to Production](https://flask.palletsprojects.com/en/stable/deploying/)). On Windows that means waitress, which is ZPL-licensed and has had no release since 2024-11.
- WSGI has no native async. SSE is possible with a streaming generator response, but each open stream holds a worker thread, and there is no built-in SSE helper.

### stdlib `http.server`

- "`http.server` is not recommended for production. It only implements basic security checks." `SimpleHTTPRequestHandler` follows symlinks and implements only GET and HEAD ([Python docs: http.server](https://docs.python.org/3/library/http.server.html)). `ThreadingHTTPServer` exists (since 3.7).
- Zero dependencies, but the app would hand-write routing, JSON parsing, path validation, PUT/DELETE handling, MIME types, SSE framing and error handling. For an app with about 6 to 15 endpoints plus an MCP interface later, that's a lot of security-sensitive code with no upstream maintenance.

**Verdict:** FastAPI + uvicorn. It has the best Windows story (pure-Python h11 + asyncio), built-in SSE, typed request and response models (pydantic), and async file-watch integration. The MCP Python SDK (ticket 04) is also ASGI/Starlette-based, which needs confirming in that ticket. Flask is a credible second choice. `http.server` costs too much hand-written, security-sensitive code.

## 2. YAML frontmatter: round-trip fidelity

| Library | Latest | Licence | Requires-Python | YAML engine |
|---|---|---|---|---|
| python-frontmatter | 1.3.0 (2026-05-20) | MIT | >=3.10 | PyYAML 6.0.3 (MIT), `SafeLoader`/`SafeDumper` |
| **ruamel.yaml** | 0.19.1 (2026-01-02) | MIT | >=3.9 | Own round-trip loader. Pure Python by default since 0.19.1, with C extensions now optional extras ([PyPI: ruamel.yaml](https://pypi.org/project/ruamel.yaml/)) |

- python-frontmatter's `YAMLHandler.export` calls `yaml.dump(metadata, Dumper=SafeDumper, default_flow_style=False, allow_unicode=True)` (source: `frontmatter/default_handlers.py` in the 1.3.0 wheel). PyYAML's `sort_keys` defaults to `True`, so **keys are alphabetised unless the caller passes `sort_keys=False`**, and comments are always dropped.
- ruamel.yaml "supports roundtrip preservation of comments, seq/map flow style, and map key order" in its default `YAML(typ='rt')` mode ([PyPI: ruamel.yaml](https://pypi.org/project/ruamel.yaml/)).

**Experiment** (`python-frontmatter` 1.3.0 / `ruamel.yaml` 0.19.1, CPython 3.13). The test changed `status` and wrote the file back:

| Input feature | python-frontmatter (default) | python-frontmatter `sort_keys=False` | ruamel.yaml rt (`preserve_quotes=True`) |
|---|---|---|---|
| Key order | **alphabetised** | kept | kept |
| `# comment` | **lost** | **lost** | kept |
| `"quoted"` scalar | quotes dropped | quotes dropped | kept |
| Flow list `[infra, 'ops']` | rewritten as block list | rewritten as block list | kept |
| Block scalar `\|` | rewritten as quoted multi-line string | same | kept |
| `zeta: yes` | rewritten `true` (YAML 1.1) | same | kept as `yes` (YAML 1.2 treats it as a string) |
| `alpha:   1` (extra spaces) | normalised | normalised | normalised to `alpha: 1` (the only diff) |
| Body | blank line inserted after closing `---` | same | untouched (we split the body ourselves) |

Caveats for ruamel.yaml:

- The author warns about API churn ("Please adjust/pin your dependencies accordingly") ([PyPI: ruamel.yaml](https://pypi.org/project/ruamel.yaml/)). Pin `ruamel.yaml>=0.19.1,<0.20`.
- It uses YAML 1.2 semantics, so `yes`/`no`/`on`/`off` are strings, not booleans. That's fine, and arguably better, but the schema (ticket 06) should use `true`/`false` explicitly.
- It doesn't parse frontmatter delimiters. Memex needs a roughly 20-line splitter: an opening `---` line, then YAML up to the next `---` line, then the body bytes left verbatim.

**Verdict:** **ruamel.yaml** (round-trip mode, `preserve_quotes=True`, wide `width`) with a small in-house frontmatter splitter. Only re-serialise the YAML block when the app actually changes metadata. Body edits should replace only the body and leave the original frontmatter text byte-for-byte. Don't add python-frontmatter or PyYAML.

## 3. File watching

| Option | Latest | Licence | Requires-Python | Mechanism |
|---|---|---|---|---|
| **watchfiles** | 1.3.0 (2026-09-21) | MIT | >=3.10 | Rust `notify` crate. abi3 wheels for Windows/macOS/Linux, with `cp310-abi3-win_amd64` present. Async `awatch` via anyio, and changes are batched in Rust ([watchfiles docs](https://watchfiles.helpmanual.io/)) |
| watchdog | 7.1.0 (2026-11-05) | Apache-2.0 | **>=3.11** (6.0.0 is the last for 3.9/3.10) | Windows `ReadDirectoryChangesW`, macOS FSEvents/kqueue, polling fallback. On Windows it "may not fully scan a moved directory" and "directory deletions may be reported as file deletions" ([watchdog installation](https://python-watchdog.readthedocs.io/en/stable/installation.html)). Thread/callback API |
| Polling (stdlib `os.scandir` + mtime/size) | n/a | n/a | n/a | No deps. Scanning a few thousand files every 1 to 2 s is cheap, and it works on network or synced drives where native events are unreliable |

**Verdict:** **watchfiles** `awatch()` in an asyncio background task feeding the SSE stream. It fits the async server natively and has one dependency (anyio, already present via FastAPI). Two design rules for the spec, because events are lossy on every OS:

1. Treat watcher events as hints that trigger a re-stat or re-read of affected paths. Never treat them as the source of truth.
2. Conflict detection on save must not depend on the watcher. Each save sends the client's last-seen `mtime_ns` + size (or content hash), and the server compares before writing. This belongs to ticket 08.

Fall back to polling (watchfiles `force_polling=True`, or a stdlib scan) if the Workspace is on a network or synced drive. Confirm the exact `force_polling` parameter in the watchfiles API reference when implementing; the landing page doesn't document it.

## 4. Search

| Option | Status | Licence | Notes |
|---|---|---|---|
| **In-memory scan** | stdlib | n/a | Keep `{path: (mtime, frontmatter dict, body text)}` and refresh entries on watcher hints or mtime change. Substring or regex over a personal workspace (hundreds to low thousands of files, a few MB) runs in milliseconds |
| **SQLite FTS5** (disposable cache) | stdlib `sqlite3` | Public domain | python.org Windows builds compile SQLite with `SQLITE_ENABLE_FTS5` in 3.10 to 3.13 (`PCbuild/sqlite3.vcxproj`), and so does the macOS installer (`Mac/BuildScript/build-installer.py`) ([CPython source](https://github.com/python/cpython/blob/3.13/PCbuild/sqlite3.vcxproj)). It has `bm25()` ranking, plus `porter` and `trigram` (substring) tokenizers ([SQLite FTS5](https://www.sqlite.org/fts5.html)). Verified locally: `CREATE VIRTUAL TABLE ... USING fts5(x, tokenize="trigram")` works on CPython 3.13 / SQLite 3.51 |
| Whoosh | 2.7.4, last release **2016-04-04** | BSD-2 | Unmaintained. The fork `whoosh-reloaded` was last released 2024-02-02. Avoid |
| tantivy (tantivy-py) | 0.27.0 (2026-10-22) | MIT | Rust wheels, **>=3.11** latest (0.26.2 for 3.10). Overkill for this corpus size |

**Verdict:** start with the **in-memory scan** over the parsed-file cache that the app needs anyway for entity views (Directs, waiting-on lists, and so on). Frontmatter filters (type, status, Person) become plain Python predicates over that cache. If ranked full-text search becomes necessary, add **SQLite FTS5** as a disposable cache. It's stdlib, so no new dependency. The cache file should live outside the Workspace (for example in a user cache dir) so the Workspace contains only Markdown, as the brief requires. Rebuild it on start or on mtime drift.

## 5. Push mechanism for live updates

- **SSE** via `fastapi.sse.EventSourceResponse` (FastAPI >= 0.135): one-way server-to-browser, which is all that's needed to say "file X changed on disk" or "tree changed". The browser's `EventSource` auto-reconnects, and FastAPI sends the keep-alive pings ([FastAPI SSE](https://fastapi.tiangolo.com/tutorial/server-sent-events/)). No extra package is needed.
- **WebSocket:** two-way, but needs `websockets` or `wsproto` under uvicorn ([uvicorn settings](https://uvicorn.dev/settings/)). Client-to-server traffic already goes over REST, so this adds nothing.

**Verdict:** SSE.

## Recommendation

Target **Python >= 3.11** (3.10 has been EOL since 2026-10-01). Runtime dependencies, all permissive licences:

| Package | Pin suggestion | Licence | Purpose |
|---|---|---|---|
| `fastapi` | `>=0.135` (for `fastapi.sse`) | MIT | API, validation, SSE, static SPA via Starlette `StaticFiles` |
| `uvicorn` (no `[standard]`) | `>=0.30` | BSD-3-Clause | ASGI server, run programmatically with `host="127.0.0.1"` |
| `ruamel.yaml` | `>=0.19.1,<0.20` | MIT | Round-trip frontmatter (comments, order, quotes, styles preserved) |
| `watchfiles` | `>=1.0` | MIT | Async file-change hints feeding SSE |
| stdlib `sqlite3` (optional, later) | n/a | Public domain | FTS5 search cache outside the Workspace, only if the in-memory scan proves insufficient |

Transitive dependencies (pydantic/pydantic-core, starlette, anyio, h11, click, typing-extensions, annotated-doc, typing-inspection, opentelemetry-api) are MIT, BSD or Apache-2.0. All binary dependencies (pydantic-core, watchfiles) publish Windows and macOS wheels.

Rules for the spec:

1. Disable FastAPI's built-in OpenTelemetry instrumentation explicitly (`telemetry={"tracing": False, "metrics": False, "logs": False}`) and never install `fastapi[standard]` or the OTel SDK.
2. Write frontmatter through ruamel.yaml round-trip mode only when metadata changes, and leave body bytes untouched.
3. Use watcher events as hints only. Save-time conflict detection uses mtime/size/hash comparison (ticket 08).
4. Use SSE, not WebSocket, for push.
5. Don't use python-frontmatter/PyYAML, Flask/waitress, `http.server`, watchdog, Whoosh or tantivy.

Open points for the user:

- Confirm the Python version on target workstations. If 3.10 is unavoidable, the mirror needs starlette <= 1.7.0 and the other pins listed above.
- Decide whether the transitive `opentelemetry-api` package (inert without an SDK) is acceptable under the zero-telemetry rule, or whether to pin `fastapi<0.150` instead.
