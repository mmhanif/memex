"""Core errors → HTTP (SPEC §17.1). Bodies hold Workspace-relative paths only (R16)."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from memex.core.errors import Conflict, CoreError, HasReferences, UnknownReference, Validation

log = logging.getLogger(__name__)

STATUS = {
    "validation": 422,
    "unknown_reference": 422,
    "conflict": 409,
    "exists": 409,
    "has_references": 409,
    "ambiguous_id": 409,
    "me_not_set": 409,
    "not_found": 404,
    "read_only": 423,
    "locked": 503,
    "bad_path": 400,
    "forbidden": 403,
    "unauthenticated": 401,
}
_CODE_FOR_STATUS = {404: "not_found", 401: "unauthenticated", 403: "forbidden"}
# On every response (R18). SecurityMiddleware adds them; the 500 handler runs outside it.
BASE_HEADERS = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}


def error_response(
    code: str, message: str, status: int | None = None, **extra: Any
) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message, **extra}},
        status_code=status or STATUS[code],
    )


def install(app: FastAPI) -> None:
    @app.exception_handler(CoreError)
    async def core_error(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, CoreError)
        extra: dict[str, Any] = {}
        if isinstance(exc, Conflict):
            extra["current"] = {"hash": exc.current.hash, "content": exc.current.text}
        if isinstance(exc, HasReferences):
            extra["impact"] = {"referrers": list(exc.referrers)}
        if isinstance(exc, Validation | UnknownReference) and exc.field_errors:
            extra["field_errors"] = [
                {"field": p.field, "message": p.message}
                | ({"allowed": list(p.allowed)} if p.allowed else {})
                for p in exc.field_errors
            ]
        if isinstance(exc, UnknownReference):
            extra["suggestions"] = list(exc.suggestions)
        return error_response(exc.code, exc.message, **extra)

    @app.exception_handler(RequestValidationError)
    async def bad_request(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, RequestValidationError)
        field_errors = [
            {
                "field": ".".join(str(p) for p in e["loc"][1:]) or str(e["loc"][0]),
                "message": e["msg"],
            }
            for e in exc.errors()
        ]
        return error_response("validation", "The request is invalid", field_errors=field_errors)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, HTTPException)
        code = _CODE_FOR_STATUS.get(exc.status_code, "validation")
        return error_response(code, str(exc.detail), status=exc.status_code)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Never echo or log the exception's text: it may carry absolute paths or Note
        # content (R16, §13.3).
        log.error("Unhandled %s on %s %s", type(exc).__name__, request.method, request.url.path)
        return JSONResponse(
            {"error": {"code": "internal", "message": "Something went wrong: see the log"}},
            status_code=500,
            headers=BASE_HEADERS,
        )
