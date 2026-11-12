"""The FastAPI app (SPEC §11.1, §12, §17)."""

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from memex.web import api, errors, launcher_routes, setup_routes
from memex.web.security import SecurityMiddleware
from memex.web.session import COOKIE
from memex.web.state import STATIC, AppState

__all__ = ["AppState", "create_app"]


def create_app(state: AppState) -> FastAPI:
    app = FastAPI(
        telemetry={"tracing": False, "metrics": False, "logs": False},
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.memex = state
    errors.install(app)
    app.include_router(api.router)
    app.include_router(launcher_routes.router)
    app.include_router(setup_routes.router)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/auth", include_in_schema=False)
    def auth(request: Request) -> Response:
        """Exchange the launcher's one-time code for the session cookie (R6)."""
        code = request.query_params.get("code", "")
        if not code or not state.session.redeem(code):
            return errors.error_response("unauthenticated", "That link has been used")
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            COOKIE, state.session.secret, httponly=True, samesite="strict", path="/"
        )
        return response

    @app.get("/relaunch", include_in_schema=False)
    def relaunch() -> FileResponse:
        return FileResponse(STATIC / "relaunch.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    app.add_middleware(SecurityMiddleware, state=state)
    return app
