"""Request checks and response headers for every route (SPEC §12, rules R4-R10, R18).

A pure ASGI middleware, so a refused request never reaches a handler.
"""

import base64
import hashlib
import re
from http.cookies import CookieError, SimpleCookie
from pathlib import Path
from typing import TYPE_CHECKING

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import PlainTextResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from memex.web.errors import BASE_HEADERS, error_response
from memex.web.session import COOKIE
from memex.web.state import STATIC

if TYPE_CHECKING:
    from memex.web.state import AppState

# Reachable without the cookie (R5). `/launcher/*` is HMAC-authenticated instead (§13.4).
COOKIE_EXEMPT = ("/auth", "/relaunch")
LAUNCHER_PREFIX = "/launcher/"
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
SAFE_FETCH_SITES = frozenset({"same-origin", "none"})

_IMPORT_MAP = re.compile(r'<script type="importmap">(.*?)</script>', re.DOTALL)


def csp_for(index_html: Path) -> str:
    """The CSP of §12. Chrome treats the inline import map as a script, so its hash is allowed."""
    script_src = "'self'"
    # read_text turns CRLF into LF, as the HTML parser does before Chrome hashes an inline
    # script, so a CRLF checkout (Windows) still matches.
    if match := _IMPORT_MAP.search(index_html.read_text("utf-8")):
        digest = base64.b64encode(hashlib.sha256(match.group(1).encode("utf-8")).digest())
        script_src += f" 'sha256-{digest.decode('ascii')}'"
    return (
        f"default-src 'self'; script-src {script_src}; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; font-src 'self'; object-src 'none'; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    )


class SecurityMiddleware:
    def __init__(self, app: ASGIApp, state: AppState) -> None:
        self.app = app
        self.state = state
        self.hosts = frozenset({f"127.0.0.1:{state.port}", f"localhost:{state.port}"})
        self.csp = csp_for(STATIC / "index.html")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        refusal = self._refusal(scope)
        sender = self._with_headers(send)
        if refusal is not None:
            await refusal(scope, receive, sender)
            return
        await self.app(scope, receive, sender)

    def _refusal(self, scope: Scope) -> Response | None:
        headers = Headers(scope=scope)
        path: str = scope["path"]
        method: str = scope["method"]
        host = (headers.get("host") or "").lower()
        if host not in self.hosts:  # R4: before anything else, on every route
            return PlainTextResponse("Misdirected request", status_code=421)
        if path.startswith(LAUNCHER_PREFIX):
            return _json_required(headers) if method in WRITE_METHODS else None
        if path not in COOKIE_EXEMPT and not self.state.session.is_valid_cookie(_cookie(headers)):
            return error_response("unauthenticated", "Run memex again to open this page")
        if (path.startswith("/api/") or path == "/api") and headers.get("x-memex") != "1":
            return error_response("forbidden", "Missing X-Memex header")
        if method in WRITE_METHODS:
            if headers.get("origin") != f"http://{host}":  # R9: exact; missing or null fails
                return error_response("forbidden", "Cross-origin write refused")
            site = headers.get("sec-fetch-site")
            if site is not None and site not in SAFE_FETCH_SITES:
                return error_response("forbidden", "Cross-site write refused")
            if method != "DELETE" or "content-type" in headers:
                return _json_required(headers)
        return None

    def _with_headers(self, send: Send) -> Send:
        csp = self.csp

        async def sender(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.update(BASE_HEADERS)
                if headers.get("content-type", "").startswith("text/html"):
                    headers["Content-Security-Policy"] = csp
            await send(message)

        return sender


def _cookie(headers: Headers) -> str | None:
    raw = headers.get("cookie")
    if not raw:
        return None
    jar = SimpleCookie()
    try:
        jar.load(raw)
    except CookieError:
        return None
    morsel = jar.get(COOKIE)
    return morsel.value if morsel is not None else None


def _json_required(headers: Headers) -> Response | None:
    media_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":  # R10
        return PlainTextResponse("Request bodies must be application/json", status_code=415)
    return None
