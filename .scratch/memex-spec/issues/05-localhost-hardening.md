# Localhost hardening

Type: research
Status: resolved
Blocked by:

## Question

What attacks still reach a server bound to 127.0.0.1, and what's the minimum defence? Cover DNS rebinding (Host header allowlist), CSRF from other browser tabs (Origin checks, per-session token), path traversal outside the Workspace (including symlinks and Windows path quirks), XSS via rendered Markdown, and other local users on a shared machine. Recommend concrete, testable rules for the spec.

## Research

Findings: [docs/research/localhost-hardening.md](../../../docs/research/localhost-hardening.md) (threat model, defences, and testable rules R1-R20).

## Answer

Per [localhost-hardening research](../../../docs/research/localhost-hardening.md), adopt its rules R1–R20 as the spec's security baseline:
- Host header allowlist (`127.0.0.1:PORT` / `localhost:PORT`) on every route.
- Per-launch secret: launcher opens browser with a one-time code, exchanged for an `HttpOnly; SameSite=Strict` cookie required on every route.
- Writes: exact-Origin match, JSON-only + custom `X-Memex` header, no CORS, GET is side-effect-free, Fetch-Metadata check.
- Single `resolve_workspace_path()` gate: lexical rejects (`..`, absolute, drive letters, `:`, reserved Windows names, trailing dot/space), realpath containment, no following symlinks out, `.md`-only writes.
- XSS: raw HTML off + sanitiser + strict CSP (`script-src 'self'`, `connect-src 'self'`) which also enforces air-gap.
- Unverified items flagged in the doc (Starlette TrustedHostMiddleware behaviour) must be checked at build time.
