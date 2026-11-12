# MCP integration options

Research for ticket [04-mcp-integration](../../.scratch/memex-spec/issues/04-mcp-integration.md). Researched 2026-11-11.

**Question:** How should Memex expose an MCP interface, given it runs offline on localhost? This covers the official Python SDK (licence, maturity, PyPI), the transports and how Claude Desktop, Claude Code and VS Code/Copilot connect to each, whether to run in-process with the web server or as a separate stdio process, and how Resources, Tools and Prompts map onto a file-backed workspace.

The detailed tool surface belongs to ticket 11 (`11-mcp-surface`) and is only sketched here.

---

## 1. Protocol state (as of Nov 2026)

- The **current** spec revision is **2026-07-28**. [Versioning](https://modelcontextprotocol.io/specification/versioning)
- This revision is a big change from 2025-11-25. [Changelog 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/changelog)
  - MCP is now **stateless**. The `initialize` handshake is gone, and every request carries its protocol version and client capabilities in `_meta`. Servers MUST implement `server/discover`.
  - The protocol-level sessions (`Mcp-Session-Id`) and the HTTP GET stream are removed. Change notifications now flow over `subscriptions/listen`.
  - Server-initiated requests (sampling, elicitation, roots) are replaced by Multi Round-Trip Requests (`InputRequiredResult`).
  - **Roots, Sampling and Logging are deprecated.** For Roots, the changelog says to "pass directories or files via tool parameters, resource URIs, or server configuration instead". For logging, it says to log to stderr (stdio) or OpenTelemetry.
  - The old HTTP+SSE transport (2024-11-05) is formally Deprecated.
- Implication for Memex: pass the Workspace path as server configuration (a CLI arg or env var), not via Roots. Don't build on sampling.

## 2. Official Python SDK (`mcp` on PyPI)

| Fact | Value | Source |
|---|---|---|
| Package | `mcp` | [PyPI JSON](https://pypi.org/pypi/mcp/json) |
| Licence | **MIT** | PyPI, [repo](https://github.com/modelcontextprotocol/python-sdk) |
| Python | `>=3.10` | PyPI |
| Latest | **2.3.0** (2026-10-02). 2.0.0 shipped 2026-07-28, the same day as the spec revision | PyPI release history |
| v1 line | 1.30.0 (2026-09-07). Maintenance only: "critical fixes and security patches" | [What's new in v2](https://py.sdk.modelcontextprotocol.io/whats-new/index.md) |
| Cadence | Roughly monthly releases on both lines through 2026 | PyPI |

**Runtime dependencies (2.3.0):** anyio, `httpx2`, jsonschema, `mcp-types` (pinned to the same version), opentelemetry-api, pydantic>=2.12, `pyjwt[crypto]` (pulls in `cryptography`), python-multipart, sse-starlette, starlette, typing-extensions, typing-inspection, uvicorn, and `pywin32` on Windows. [PyPI JSON](https://pypi.org/pypi/mcp/json)

- These are all mainstream, permissively licensed packages. Even so, the internal mirror must carry them, including `mcp-types` and `httpx2`. Check this before committing.
- `opentelemetry-api` is only the API package. With no SDK or exporter configured, nothing is sent, so it doesn't conflict with the zero-telemetry rule. Still worth confirming during the ticket 05 hardening review.
- Starlette and uvicorn overlap with the FastAPI/Starlette option in ticket 02, so choosing that stack adds little extra weight.

**v2 API notes** ([What's new](https://py.sdk.modelcontextprotocol.io/whats-new/index.md), [Migration guide](https://py.sdk.modelcontextprotocol.io/migration/index.md)):

- `FastMCP` is renamed **`MCPServer`** (`from mcp.server.mcpserver import MCPServer`). The decorators are `@mcp.tool()`, `@mcp.resource("scheme://{param}")` and `@mcp.prompt()`.
- v2 "serves both revisions at once": 2026-07-28 clients, plus older `initialize`-handshake clients. This matters because client apps lag behind the spec.
- Resource URI templates follow RFC 6570, use exact matching, and **reject path traversal by default**.
- A tool that raises a plain exception now returns a sanitized `-32603` error. Use `is_error=True` results for errors the model should see, such as validation failures and conflicts.
- stdio is started with `mcp.run(transport="stdio")`.
- Streamable HTTP can be **mounted into an existing Starlette app**. The guide's code:
  ```python
  app_routes = [Mount("/", app=mcp.streamable_http_app(json_response=True))]

  @contextlib.asynccontextmanager
  async def lifespan(app):
      async with mcp.session_manager.run():  # host app must enter this
          yield

  app = Starlette(routes=app_routes, lifespan=lifespan)
  ```
  The guide documents Starlette only, not FastAPI, though FastAPI is Starlette underneath.
- **DNS-rebinding protection is on by default** when the host is 127.0.0.1, localhost or ::1. The automatic Host allowlist is `127.0.0.1:*`, `localhost:*` and `[::1]:*`. You can configure it with `TransportSecuritySettings(allowed_hosts=..., allowed_origins=...)`.
- Request bodies are capped at 4 MiB by default.

## 3. Transports

The spec defines two standard transports. [Transports overview (2025-06-18)](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports), [stdio (2026-07-28)](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio), [Streamable HTTP (2026-07-28)](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)

**stdio**
- "The client launches the MCP server as a subprocess." Messages are newline-delimited JSON-RPC on stdin/stdout, and logs go to stderr. The server MUST NOT write anything else to stdout.
- The server should exit when stdin closes. If the server dies, the client SHOULD restart it ("Because the protocol is stateless, any in-flight requests are simply lost").
- The spec says: "Clients **SHOULD** support stdio whenever possible."
- No network socket at all, so no Origin, Host or auth concerns.

**Streamable HTTP**
- A single POST endpoint (for example `/mcp`). The server "operates as an independent process that can handle multiple client connections".
- Spec security requirements, quoted:
  1. "Servers **MUST** validate the `Origin` header on all incoming connections to prevent DNS rebinding attacks." An invalid Origin gets a 403.
  2. "When running locally, servers **SHOULD** bind only to localhost (127.0.0.1)".
  3. "Servers **SHOULD** implement proper authentication for all connections."
- In 2026-07-28, clients must send `MCP-Protocol-Version`, `Mcp-Method` and `Mcp-Name` headers, and the server must validate them against the body. The SDK handles this.

**HTTP+SSE (legacy):** Deprecated. Don't implement it.

## 4. How clients connect

| Client | stdio | Streamable HTTP to `http://127.0.0.1:PORT/mcp` | Resources / Prompts in UI | Source |
|---|---|---|---|---|
| **Claude Desktop** | Yes, via `claude_desktop_config.json` (`command`, `args`, `env`). File lives at `~/Library/Application Support/Claude/` (macOS) or `%APPDATA%\Claude\` (Windows). The server's stderr goes to `mcp-server-NAME.log` | The local config file documents only `command` entries. Remote servers are added as **Custom Connectors** through Claude settings, and the docs assume an internet-hosted `https://` URL with auth. Not a documented path for a localhost-only server | Resources and prompts can be attached from the "+" menu (shown for connectors) | [Connect local servers](https://modelcontextprotocol.io/docs/develop/connect-local-servers), [Connect remote servers](https://modelcontextprotocol.io/docs/develop/connect-remote-servers) |
| **Claude Code** | Yes: `claude mcp add --transport stdio memex -- <cmd> [args]`. Scopes are local, project (`.mcp.json`) and user | Yes: `claude mcp add --transport http memex http://127.0.0.1:PORT/mcp`. `--header` adds a token. SSE is deprecated | Resources via `@server:uri` mentions, with built-in list/read tools. Prompts become `/mcp__server__prompt` commands | [Claude Code MCP docs](https://code.claude.com/docs/en/mcp) |
| **VS Code / Copilot** | Yes: `mcp.json` with `"type": "stdio"`, `command`, `args`, `env`, `envFile`, `cwd` | Yes: `"type": "http"`, `url`, `headers` | Prompts as `/mcp.server.prompt`. Resources can be attached as chat context. Admins can restrict servers via the `chat.mcp.access` setting | [MCP config reference](https://code.visualstudio.com/docs/agents/reference/mcp-configuration), [MCP servers](https://code.visualstudio.com/docs/copilot/customization/mcp-servers), [MCP developer guide](https://code.visualstudio.com/api/extension-guides/ai/mcp) |

**stdio is the only transport all three clients document for a local server.** HTTP works for Claude Code and VS Code. Claude Desktop's documented route for a local server is stdio.

## 5. In-process vs. separate stdio process

| | **A. Separate stdio process sharing a core library** | **B. Streamable HTTP mounted in the web server (`/mcp`)** |
|---|---|---|
| Client coverage | All three clients | Claude Code and VS Code. Claude Desktop needs a stdio shim |
| Network exposure | **None.** No new port, so the 127.0.0.1 and rebinding analysis (ticket 05) is unchanged | A new endpoint on the 127.0.0.1 port. Needs Origin/Host validation (on by default in the SDK) and a bearer token, because any local process or browser page could otherwise reach it |
| Web app must be running? | No. The client spawns Memex's MCP server on demand | Yes. The agent fails if the user hasn't launched Memex |
| Concurrency with the UI | Two processes write the same files. Memex already treats this as normal: external edits (VS Code, agents) are expected, there's no stale caching, and saves detect on-disk conflicts (map Notes, ticket 08). The UI sees MCP writes through the same file-watch/refresh path as any external edit | One process, so writes could share in-memory locks and push live updates to the SPA directly. A minor benefit given the above |
| Packaging | One extra console entry point, for example `python -m memex.mcp --workspace <path>`. The client config needs the absolute path to the venv's Python. No admin rights needed | Nothing extra to launch. Port selection becomes part of client config, and the port may change |
| Coupling | Forces a clean seam: REST handlers and MCP tools are both thin adapters over one `memex.core` service layer (entity read/write, validation, frontmatter round-trip, search) | Same core needed anyway; mounting adds lifespan wiring (`session_manager.run()`) to the web app |
| SDK footprint | `mcp` package in both cases | Same |

Because MCP is stateless as of 2026-07-28, and the SDK serves both eras from one app, either option can be added later without redesign. The decision that matters now is the **shared core library**. Both REST and MCP must go through it so validation, stable-identifier references and conflict detection behave the same (ticket 11 depends on this).

## 6. Mapping primitives to a file-backed workspace

The spec's control model ([Server overview](https://modelcontextprotocol.io/specification/2026-07-28/server/index)):

| Primitive | Control | Spec example |
|---|---|---|
| Prompts | User-controlled | Slash commands, menu options |
| Resources | Application-controlled | File contents, git history |
| Tools | Model-controlled | API POST requests, file writing |

How each applies to Memex:

- **Tools carry the core capability.** They are the one primitive every client exposes to the model autonomously. Resources are "application-driven": whether the model can pull one on its own depends on the host. Claude Code adds list/read tools; others mostly need the user to attach them. [Resources spec](https://modelcontextprotocol.io/specification/2026-07-28/server/resources)
  - So every read the agent needs (search, get Entity, list waiting-on) must exist as a **tool**, not only as a resource.
  - Writes go through domain-level tools (for example "create To-do" or "set Project status") that call the core library's validation. Don't expose a raw "write file" tool: it would bypass frontmatter validation and Entity references.
  - Return validation and conflict failures as `is_error=True` results.
- **Resources are for read-only context the user attaches.**
  - Use one resource template per Entity type, for example `memex://project/{id}`, `memex://person/{id}` and `memex://note/{path}`. Each returns `text/markdown` (the raw file with frontmatter), with `lastModified` annotations.
  - A custom scheme is allowed (it must follow RFC 3986). `file://` is also allowed for "resources that behave like a filesystem". A custom scheme keyed on **stable identifiers** instead of paths survives renames (ticket 07) and avoids leaking absolute paths.
  - Servers "MUST sanitize file paths to prevent directory traversal". The v2 SDK rejects traversal in templates by default, but the core library should still resolve every id or path strictly inside the Workspace.
  - `listChanged` and `subscribe` are optional. Skip them at first; they would mean wiring the file watcher into `subscriptions/listen`.
- **Prompts are a few user-invoked workflows.** For example: "1:1 prep for {person}" (their Projects, Deliverables and both waiting-on lists), "weekly review", "triage inbox To-dos". These show up as slash commands in Claude Code and VS Code. Cheap to add, not essential.
- **Don't use:** Roots (deprecated; the Workspace comes from config), Sampling (deprecated, and it would need an LLM), or Logging (deprecated; log to stderr instead).

## Recommendation

1. **Use the official `mcp` SDK, v2 line, pinned `mcp>=2.3,<3`.** It's MIT-licensed, on PyPI, Python ≥3.10, has roughly monthly releases, and speaks both the 2026-07-28 and older handshake protocols. Write against the high-level `MCPServer` decorator API. Confirm the internal mirror carries the transitive dependencies, including `mcp-types`, `httpx2`, `pyjwt[crypto]` and `opentelemetry-api`.
2. **Use stdio, as a separate process.** Ship a `memex-mcp` entry point (`python -m memex.mcp --workspace <path>`) that the AI client spawns.
   - It is the only transport all three target clients document for local servers, the spec says clients SHOULD support it, it opens no network port, and it works whether or not the web UI is running.
   - Provide copy-paste config snippets for `claude_desktop_config.json`, `claude mcp add` and `.vscode/mcp.json`.
3. **Put a shared core library under both adapters.** REST handlers and MCP tools are thin adapters over one `memex.core` (Entity CRUD, frontmatter round-trip, validation, search, conflict checks). MCP writes then follow exactly the rules the UI follows, and the UI picks up MCP edits the same way it picks up any external edit.
4. **Defer in-process Streamable HTTP (`/mcp`).** Add it only if a concrete need appears, for example a client that can't spawn processes. If added, mount it in the Starlette/FastAPI app on 127.0.0.1. Keep the SDK's default Host/Origin protection and require a per-install bearer token stored in workspace-external config.
5. **Primitive mapping:** domain-level **Tools** for every read and write the agent needs (no raw file-write tool). Read-only **Resource templates** per Entity type under a `memex://` scheme keyed by stable id. A few **Prompts** for user-invoked workflows. No Roots, Sampling or Logging. Ticket 11 settles the exact list.
