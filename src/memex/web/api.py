"""The `/api/*` routes built so far (SPEC §17.2)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import BaseModel

from memex.core.cache import CachedFile
from memex.core.errors import CoreError, Validation
from memex.core.store import FileVersion
from memex.core.workspace import Workspace
from memex.web.state import AppState, app_state

router = APIRouter(prefix="/api")


class NoWorkspace(CoreError):
    """Setup isn't done yet, so there is nothing to read or write (§3.3)."""

    code = "not_found"

    def __init__(self) -> None:
        super().__init__("No Workspace is open: finish Setup first")


def workspace(state: Annotated[AppState, Depends(app_state)]) -> Workspace:
    if state.workspace is None:
        raise NoWorkspace()
    return state.workspace


WS = Annotated[Workspace, Depends(workspace)]


class NewFile(BaseModel):
    path: str
    content: str


def _saved(response: Response, path: str, version_hash: str) -> dict:
    """A read or write's version token, as `ETag` and in the body (§5.3)."""
    response.headers["ETag"] = f'"{version_hash}"'
    return {"path": path, "hash": version_hash}


def _expected_hash(if_match: str | None) -> str:
    if not if_match:
        raise Validation("If-Match is required: send the hash you last read")
    return if_match.strip().removeprefix("W/").strip('"')


@router.get("/tree")
def tree(ws: WS) -> dict:
    return {"folders": ws.cache.folders(), "files": [_tree_file(f) for f in ws.cache.files()]}


def _tree_file(f: CachedFile) -> dict:
    return {
        "path": f.rel,
        "id": f.id,
        "type": f.type,
        "title": f.title,
        "hash": f.hash,
        "warnings": [{"kind": w.kind, "message": w.message, "line": w.line} for w in f.warnings],
    }


@router.get("/files")
def read_file(ws: WS, response: Response, path: Annotated[str, Query()]) -> dict:
    version = _read(ws, path)
    return {**_saved(response, path, version.hash), "content": version.text}


@router.post("/files", status_code=201)
def create_file(ws: WS, body: NewFile, response: Response) -> dict:
    return _saved(response, body.path, ws.store.create(body.path, body.content))


@router.put("/files")
def write_file(
    ws: WS,
    body: NewFile,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> dict:
    new_hash = ws.store.write(body.path, body.content, _expected_hash(if_match))
    return _saved(response, body.path, new_hash)


def _read(ws: Workspace, path: str) -> FileVersion:
    try:
        return ws.store.read(path)
    except UnicodeDecodeError:
        raise Validation(f"{path} isn't UTF-8 text, so Memex can't open it") from None
