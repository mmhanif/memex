# Localhost hardening

Research for ticket [05-localhost-hardening](../../.scratch/memex-spec/issues/05-localhost-hardening.md).
Researched 2026-11-11.

**Question.** Which attacks still reach a server bound to `127.0.0.1`, and what is the minimum defence? The ticket covers DNS rebinding, CSRF from other browser tabs, path traversal outside the Workspace, XSS through rendered Markdown, and other local users on a shared machine.

**Short answer.** Binding to `127.0.0.1` hides Memex from the LAN and from nothing else. Three things can still reach it: any web page open in the user's browser (through CSRF and DNS rebinding), any process run by *any* user on the same machine (the loopback interface is per host, not per user), and any Markdown that reaches the Workspace from another source (agents, pasted content, synced files). The minimum defence has five parts, and each is cheap on its own:

1. A strict `Host` allowlist, which defeats DNS rebinding.
2. A per-launch secret exchanged for an `HttpOnly; SameSite=Strict` session cookie, which keeps out other local users and other localhost apps.
3. An exact-match `Origin` check plus a JSON-only, custom-header API, which defeats CSRF.
4. One path-resolution function that does a lexical check and then a `realpath` containment check, which stops traversal.
5. Sanitised Markdown rendering behind a strict CSP, which stops XSS. The same CSP also enforces the air-gap rule.

---

## 1. Threat model

| Attacker | How they reach Memex | What binding to 127.0.0.1 does about it |
|---|---|---|
| Remote host on the LAN | TCP to the workstation IP | **Blocked.** This is the only threat the bind removes. |
| Malicious or compromised web page in the user's browser | The browser sends requests to `http://127.0.0.1:PORT` (CSRF), or a rebound DNS name resolves to 127.0.0.1 | Nothing. The browser is on the host. |
| Another local OS user (shared or RDP host, service accounts) or other local malware | Direct TCP to 127.0.0.1 | Nothing. Loopback is not per user. |
| Another web app on `127.0.0.1:<other port>` (dev servers, other tools) | Same-*site* browser requests; cookies are shared across ports | Nothing. |
| Untrusted content inside the Workspace (AI agent output via MCP, pasted web content, files written by VS Code or agents) | Rendered in the SPA's preview | Nothing. |

The impact is high. The API can read, overwrite, move and delete every file in the Workspace. If path containment fails, it can do the same anywhere the user's account can reach.

Published advisories for this exact class of tool show that "it's only on localhost" is not a defence:

- **Transmission, CVE-2018-5702.** Tavis Ormandy (Project Zero) showed that a DNS-rebound page could drive the local RPC daemon. The CSRF defence used a session-id header, and it did not help: after rebinding, the attacker's page is same-origin and can read that header. The fix was a `Host` header whitelist that answers `421` for unknown hosts. Source: [oss-security, 2018-01-15](https://www.openwall.com/lists/oss-security/2018/01/15/1). The same researcher found the same bug in the Blizzard Update Agent.
- **MCP Inspector, CVE-2025-49596 / [GHSA-7f8r-222p-6f5g](https://github.com/advisories/GHSA-7f8r-222p-6f5g)** (critical). The local proxy had no authentication between client and proxy, so a web page could launch commands through it. It was fixed in 0.14.1 by adding a session token and origin checks.
- **MCP Python SDK, CVE-2025-66416 / [GHSA-9h52-p55h-vw2f](https://github.com/modelcontextprotocol/python-sdk/security/advisories/GHSA-9h52-p55h-vw2f).** HTTP MCP servers on localhost did not have DNS rebinding protection on by default. "A malicious website" could "invoke tools or access resources." It was fixed in 1.23.0. The TypeScript SDK has a companion advisory, GHSA-w48q-cv73-mx4w (CVE-2025-66414).
- **Jupyter Notebook** added a loopback `Host` header check in 5.6/5.7 "to protect against DNS rebinding" as a pre-emptive measure ([changelog](https://jupyter-notebook.readthedocs.io/en/5.7.4/changelog.html)). It has also required a token by default for years ([Jupyter Server security docs](https://jupyter-server.readthedocs.io/en/latest/operators/security.html)).

Memex plans an MCP interface, so the MCP spec's own transport warning applies directly. For Streamable HTTP, servers "**MUST** validate the `Origin` header on all incoming connections to prevent DNS rebinding attacks", "**SHOULD** bind only to localhost", and "**SHOULD** implement proper authentication" ([MCP transports, 2025-06-18](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)). stdio-transport servers are explicitly not affected by the rebinding advisory.

### Browser mitigations are not enough on their own

Chrome's Local Network Access (LNA) gates requests from websites to loopback and private addresses behind a user permission prompt. It was opt-in in Chrome 138 and the prompt launched in Chrome 142 ([Chrome blog](https://developer.chrome.com/blog/local-network-access)). There are three reasons not to rely on it:

- It covers `fetch()`, subresources and subframes. WebSockets, WebTransport and WebRTC are "not yet gated".
- Users can click "Allow", and enterprises can pre-grant it by policy.
- It is Chromium-only. The predecessor (Private Network Access) was put "on hold" after years of rollout ([Chrome blog, PNA update](https://developer.chrome.com/blog/private-network-access-update)).

Treat LNA as defence in depth only.

---

## 2. DNS rebinding → `Host` allowlist

**Mechanism.** The attacker serves a page from `evil.example`, then changes the DNS answer for `evil.example` to `127.0.0.1`. The browser still treats the page as origin `http://evil.example:PORT`, so same-origin policy lets it read Memex's responses. Cookies scoped to `127.0.0.1` are *not* sent, but an unauthenticated API needs none. Any token the SPA fetches from the API can also be fetched by the rebound page (the Transmission lesson).

**Defence.** The `Host` header still carries `evil.example:PORT`. Reject every request whose `Host` is not exactly one of the expected loopback authorities. This is the defence used by Transmission, Jupyter and the MCP SDKs. In Python, Starlette's `TrustedHostMiddleware` (used by FastAPI) does this. It must be configured with explicit hosts, never `*`.

The session cookie in §3 is a second, independent barrier, because a rebound origin never has the cookie.

---

## 3. Other local users and other localhost apps → per-launch secret

**Mechanism.** Any local process can `connect()` to `127.0.0.1:PORT`. On a multi-user or RDP workstation, that includes other people's processes. Jupyter's default token exists for exactly this case. Origin and Host checks do not help, because a non-browser client sets whatever headers it likes.

**Cookies leak across ports.** RFC 6265 §8.5: "Cookies do not provide isolation by port. If a cookie is readable by a service running on one port, the cookie is also readable by a service running on another port of the same server" ([RFC 6265](https://www.rfc-editor.org/rfc/rfc6265#section-8.5)). For the same reason, another app on `127.0.0.1:3000` is *same-site* with Memex. `SameSite` cookies will be sent from it, and `Sec-Fetch-Site` will say `same-site`, not `cross-site`. Two consequences:

- The cookie must be `HttpOnly`, so another localhost page cannot read it with JavaScript.
- The `Origin` check in §4 must compare the full origin including the port. "Not cross-site" is not enough.

**Defence: a secret per launch.**

1. The launcher generates a 256-bit secret (`secrets.token_urlsafe(32)`).
2. It binds the socket itself, reads back the actual port, and opens the browser at `http://127.0.0.1:PORT/auth?code=<one-time code>`.
3. The server compares the code in constant time (`hmac.compare_digest`) and invalidates it on first use, so the code left in browser history or process arguments is dead. It then sets `memex_session=<secret>; HttpOnly; SameSite=Strict; Path=/` and answers `303` to `/`.
4. Every request except `/auth` and a static "please relaunch" page needs the cookie. That includes `/`, static assets, and `/api/*`.

If a second browser window or a restart needs a new code, the launcher (or a `memex open` command) mints one.

**Port hijacking (Windows).** Microsoft: "All server applications must set `SO_EXCLUSIVEADDRUSE`". `SO_REUSEADDR` makes a server "eminently vulnerable to 'socket hijacking'" ([Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/winsock/using-so-reuseaddr-and-so-exclusiveaddruse)). Enhanced socket security already stops a *different* user from re-binding a specific-address socket with `SO_REUSEADDR`. Setting the exclusive flag is still the documented practice.

The bigger risk is a squatter that is already listening on the default port. The launcher must never assume an existing listener is Memex, and must never send a code to a port it did not bind itself.

**Workspace and secret on disk.** The Workspace and any secret or config file must live under the user's profile, where the OS already denies other standard users access (`%LOCALAPPDATA%` / `~/Library/Application Support`). On POSIX, create secret files with mode `0600`. Never write the session secret to logs.

---

## 4. CSRF from other tabs → Origin check plus a non-simple API

**Mechanism.** A cross-site page can send "simple" requests without a CORS preflight: `GET`, or `POST` with `text/plain`, `application/x-www-form-urlencoded` or `multipart/form-data`, using forms, `fetch(..., {mode:'no-cors'})` or `<img>`. The page cannot read the response, but the side effect happens.

OWASP's current guidance ([CSRF cheat sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)):

- Verify `Origin` against the target origin. "Missing headers and `Origin: null` are not evidence of a same-origin request."
- Use `Sec-Fetch-Site` as the primary signal, with an Origin fallback that "is a mandatory requirement". It is supported in Chrome 76+, Firefox 90+ and Safari 16.4+ ([web.dev](https://web.dev/articles/fetch-metadata)).
- Custom request headers force a preflight for AJAX APIs.
- Disallowing simple content types "is a simple mitigation".
- `SameSite` is defence in depth only.

**Defence for Memex.** Memex's only legitimate browser client is its own SPA, served from the same origin. That allows a strict, allowlist-only rule set:

- Every request with an unsafe method (`POST`, `PUT`, `PATCH`, `DELETE`) must carry `Origin` exactly equal to `http://127.0.0.1:PORT` (or `http://localhost:PORT`). A missing or `null` Origin is rejected.
- Reject `Sec-Fetch-Site` values other than `same-origin` or `none` on `/api/*`.
- Every `/api/*` request body must be `Content-Type: application/json`, and every `/api/*` request must carry a custom header such as `X-Memex: 1`. Both force a preflight on any cross-origin request.
- Send **no** CORS headers at all and do not answer `OPTIONS`. Preflights fail, so cross-origin requests never reach handlers.
- `GET` never changes state.
- `SameSite=Strict` on the session cookie adds a third barrier against cross-*site* pages.

---

## 5. Path traversal outside the Workspace

Every endpoint in the brief takes a client-supplied relative path: `GET/POST/PUT/DELETE /api/files`, `POST /api/move` (two paths), and the tree and search endpoints.

**Windows quirks** ([Microsoft: Naming Files, Paths, and Namespaces](https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file)):

- `\` and `/` are both separators.
- Drive-relative paths such as `C:tmp.txt` and `C:..\tmp.txt` exist, as do UNC paths (`\\server\share`), `\\?\` (which "disable[s] all string parsing" and allows literal `..`) and `\\.\` (the device namespace).
- Reserved device names (`CON`, `PRN`, `AUX`, `NUL`, `COM1-9`, `LPT1-9`, plus superscript digits) are reserved *in every directory*, even with an extension: "`NUL.txt` and `NUL.tar.gz` are both equivalent to `NUL`".
- A name ending in a space or a period is silently trimmed by the shell.
- `:` selects an alternate data stream (`a.md:hidden`).
- Names are case-insensitive.
- 8.3 short aliases such as `PROGRA~1` may exist.

Python 3.13+ `os.path.isreserved()` checks for trailing dot or space, colons, wildcards, pipes, control characters and DOS device names ([Python docs](https://docs.python.org/3/library/os.path.html)). The docs warn it is an approximation.

**Symlinks and junctions.** A link inside the Workspace can point anywhere, and a user or agent can create one. `os.path.realpath()` resolves symlinks and, since 3.8, Windows junctions. On Windows it also expands 8.3 names. `os.path.commonpath()` gives a correct component-wise prefix; `commonprefix()` does not (`/ws` vs `/ws-evil`).

**Defence: one function, used by every endpoint.** `resolve_workspace_path(rel) -> Path` runs two stages.

1. **Lexical stage, applied to the raw string after URL and JSON decoding** (OWASP: "Validate the representation that will actually be used").
   - Accept only `/`-separated relative paths.
   - Reject:
     - an empty string
     - a leading `/` or `\`
     - any `\`
     - a drive letter (`^[A-Za-z]:`)
     - `:` anywhere
     - NUL or control characters
     - any `.`, `..` or empty segment
     - any segment ending in `.` or space
     - any segment matching a reserved device name (case-insensitive, with or without an extension)
     - characters in `<>"|?*`

   Apply the same rules on macOS too, so a Workspace stays portable between OSes.
2. **Resolution stage.** Compute `real = realpath(root / rel)` and `real_root = realpath(root)`, which is computed once at startup. Require `commonpath([real_root, real]) == real_root`, comparing with `normcase` on Windows. For create and move targets that do not exist yet, resolve the parent with `strict=True` and check it.

Further rules:

- **Writes** only create or overwrite `*.md` files and folders, as the brief requires.
- **Moves** validate both source and destination. They refuse to move the Workspace root, and refuse to move a folder into its own descendant.
- **Deletes** of folders use `shutil.rmtree`, which does not follow directory symlinks or junctions. They refuse to delete the root.
- **Tree and search** walk with `followlinks=False` and do not descend into links whose target resolves outside the root. Links inside the root may be listed but must still pass the stage-2 check when opened.
- **Error bodies** return the relative path only, never the absolute filesystem path.

A residual time-of-check/time-of-use race (a directory swapped for a link between check and open) needs write access to the Workspace. That is already the user's own account, which is out of scope.

---

## 6. XSS via rendered Markdown

**Why it matters for a single-user app.** Workspace content is not all typed by the user. The brief expects AI agents (via MCP) and external editors to write files, and agents may copy text from untrusted web pages (prompt injection). Script that runs inside Memex's origin has the session cookie's authority, so XSS gives an attacker every API capability in §1.

**Facts:**

- CommonMark allows raw HTML. markdown-it-py's default preset is "more convenient, but less secure". Its docs recommend either sanitising the output or using the `js-default` preset (HTML disabled). Even by default it blocks `javascript:`, `vbscript:`, `file:` and most `data:` links ([markdown-it-py security](https://markdown-it-py.readthedocs.io/en/latest/security.html)).
- OWASP recommends DOMPurify for HTML sanitisation and says to keep it patched. It also says not to change sanitised output afterwards, to allow only `http`/`https` URLs in `href`/`src`, to use `textContent` rather than `innerHTML` for plain values, and to treat CSP as defence in depth, "not your primary defense" ([XSS cheat sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html)).

**Defence:**

- Render with raw HTML **disabled** (markdown-it `html: false`, the JS default). Run the HTML output through **DOMPurify** (client side) or **nh3** (if rendering on the server) before inserting it into the DOM.
- Allow only `http:`, `https:`, `mailto:` and Workspace-relative link schemes. External links get `rel="noopener noreferrer"` and `target="_blank"`.
- Frontmatter values, file names, tags and search snippets are inserted with `textContent`, never `innerHTML`.
- Prefix generated heading IDs (for example `user-content-`) to prevent DOM clobbering, as markdown-it-py warns.
- Serve every HTML response with a strict CSP:

  ```
  default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:;
  connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none';
  form-action 'self'; frame-ancestors 'none'
  ```

  Also send `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`. If a chosen mind-map or editor library needs inline styles, relax `style-src` only, never `script-src`.

  **Bonus:** `img-src 'self' data:` and `connect-src 'self'` also enforce the brief's **air-gap** rule. A note that embeds `![](https://tracker.example/x.png)` cannot make an outbound request.

---

## 7. MCP interface

Prefer the **stdio** transport. The agent launches a Memex MCP process that calls the same file layer in-process. There is no listener, so §2-§4 do not apply. Both SDK rebinding advisories exempt stdio.

If Streamable HTTP is ever needed, it gets the same `Host` allowlist, an exact `Origin` check, and a bearer secret read from a per-user `0600` file, as the MCP spec's Security Warning requires. It must also call the same `resolve_workspace_path`.

---

## 8. Concrete, testable rules for the spec

Each rule is phrased so it can be checked by an automated test against a running server (S) or a unit test (U).

**Binding and launch**

- **R1 (S).** The server listens only on `127.0.0.1`. A connection to the machine's LAN IP on the same port is refused. Startup fails if the configured host is anything other than `127.0.0.1`.
- **R2 (U).** On Windows the listening socket sets `SO_EXCLUSIVEADDRUSE` and does not set `SO_REUSEADDR`.
- **R3 (U).** The launcher opens the browser only at the port its own socket actually bound. If the preferred port is busy it picks another, and never hands a code to an existing listener.

**DNS rebinding**

- **R4 (S).** A request whose `Host` header is not exactly `127.0.0.1:PORT` or `localhost:PORT` gets `421` (or `400`) with no handler executed, on every route including `/` and static assets. Test with `Host: evil.example:PORT`, `Host: 127.0.0.1.evil.example`, a missing `Host`, and the wrong port.

**Authentication (local users and other localhost apps)**

- **R5 (S).** Without a valid `memex_session` cookie, every route except `/auth` and a static re-launch page returns `401`, including `GET /api/tree`, `GET /api/files` and `GET /`.
- **R6 (S).** `/auth?code=X` with a valid one-time code sets a cookie with the attributes `HttpOnly` and `SameSite=Strict`, and redirects with `303`. Reusing the same code gets `401`. A wrong code gets `401`. Comparison is constant time (U).
- **R7 (U).** The secret has at least 256 bits from `secrets`. It never appears in logs or in any API response body. Any on-disk copy is mode `0600` (POSIX) or lives under the user profile (Windows).
- **R8 (S).** The server sends no `Access-Control-Allow-*` headers on any response, and `OPTIONS` to `/api/*` does not return a successful CORS preflight.

**CSRF**

- **R9 (S).** A `POST`/`PUT`/`DELETE` to `/api/*` with a valid cookie is rejected with `403` when any of these is true:
  - `Origin` is missing
  - `Origin` is `null`
  - `Origin` is `http://127.0.0.1:<other port>`
  - `Origin` is `http://evil.example`
  - `Sec-Fetch-Site: cross-site` or `same-site` is present
- **R10 (S).** `/api/*` write requests with `Content-Type` other than `application/json` (for example `text/plain` or form-encoded) get `415`. Any `/api/*` request lacking `X-Memex: 1` gets `403`.
- **R11 (S).** No `GET` endpoint changes disk state. A test snapshots the Workspace, calls every `GET`, and asserts no change.

**Path containment**

- **R12 (U, table-driven).** Every one of these inputs is rejected with `400`, and disk state is unchanged afterwards:
  - **Lexical:** `../x.md`, `a/../../x.md`, `/etc/passwd`, `C:\x.md`, `C:x.md`, `\\server\share\x.md`, `\\?\C:\x.md`, `a\..\..\x.md`, `%2e%2e/x.md` (after decoding), `a/./b.md`, `a//b.md`
  - **Names and characters:** `a.md:stream`, `NUL.md`, `con`, `com1.txt`, `x.md.`, `x.md `, `a\u0000.md`, `a?.md`
  - **Writes:** writing a non-`.md` file
- **R13 (U).** A symlink (and on Windows, a junction) inside the Workspace that points outside it:
  - is not descended by `/api/tree` or search
  - returns `400`/`403` when read, written, moved into or moved out of
  - on folder delete, removes only the link and never the target's contents
- **R14 (U).** `/api/move` refuses: the Workspace root as source; a destination outside the root; a folder moved into its own descendant; a destination that already exists (unless an explicit overwrite flag is set).
- **R15 (U).** `DELETE` on the Workspace root (`""`, `.`, `/`) is refused.
- **R16 (S).** Error responses contain no absolute filesystem paths.

**XSS and content**

- **R17 (U, fixture corpus).** Rendering each of these produces DOM with no script execution, no event-handler attributes and no `javascript:` URLs:
  - `<script>`
  - `<img src=x onerror=…>`
  - `[x](javascript:alert(1))`
  - `[x](JaVaScRiPt:…)`
  - `<svg onload>`
  - `<iframe>`
  - `<a href="data:text/html,…">`
  - HTML inside frontmatter values
  - a heading whose ID would clobber `window.foo`
- **R18 (S).** Every HTML response carries the CSP in §6 (at minimum `script-src 'self'`, `object-src 'none'`, `base-uri 'none'`, `frame-ancestors 'none'`, `img-src 'self' data:`, `connect-src 'self'`) plus `X-Content-Type-Options: nosniff`. JSON responses carry `nosniff` and `Content-Type: application/json`.
- **R19 (S, browser).** Opening a note containing `![](https://example.com/p.png)` produces zero outbound network requests (CSP violation only).

**MCP**

- **R20.** The MCP interface uses the stdio transport. If an HTTP transport is added, it must pass R4, R5 (with a bearer secret), R9 and R12-R15 unchanged.

---

## Sources

- OWASP: [CSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html), [XSS Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html), [Input Validation Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Input_Validation_Cheat_Sheet.html)
- Chrome: [Local Network Access (2025)](https://developer.chrome.com/blog/local-network-access), [Private Network Access update](https://developer.chrome.com/blog/private-network-access-update); web.dev: [Fetch Metadata](https://web.dev/articles/fetch-metadata)
- IETF: [RFC 6265 §8.5](https://www.rfc-editor.org/rfc/rfc6265#section-8.5)
- Microsoft Learn: [Naming Files, Paths, and Namespaces](https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file), [SO_REUSEADDR and SO_EXCLUSIVEADDRUSE](https://learn.microsoft.com/en-us/windows/win32/winsock/using-so-reuseaddr-and-so-exclusiveaddruse)
- Python: [os.path](https://docs.python.org/3/library/os.path.html); [markdown-it-py security](https://markdown-it-py.readthedocs.io/en/latest/security.html)
- MCP: [Transports spec 2025-06-18, Security Warning](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)
- Advisories: Transmission CVE-2018-5702 ([oss-security](https://www.openwall.com/lists/oss-security/2018/01/15/1)); MCP Inspector CVE-2025-49596 ([GHSA-7f8r-222p-6f5g](https://github.com/advisories/GHSA-7f8r-222p-6f5g)); MCP Python SDK CVE-2025-66416 ([GHSA-9h52-p55h-vw2f](https://github.com/modelcontextprotocol/python-sdk/security/advisories/GHSA-9h52-p55h-vw2f)); Jupyter Notebook [5.6/5.7 changelog](https://jupyter-notebook.readthedocs.io/en/5.7.4/changelog.html), [Jupyter Server security](https://jupyter-server.readthedocs.io/en/latest/operators/security.html)

**Not verified against a primary source:**

- The claim that loopback is reachable by other local users is standard OS behaviour, but I did not cite a primary source for it.
- The details of the MCP Inspector fix (session token plus origin checks) come from secondary write-ups. The GHSA page itself only says "lack of authentication between the Inspector client and proxy".
- I could not reach the Starlette docs (DNS failure). Confirm `TrustedHostMiddleware` behaviour against the installed version.
