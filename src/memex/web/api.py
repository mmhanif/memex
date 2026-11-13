"""The `/api/*` routes built so far (SPEC §17.2)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import BaseModel, Field

from memex.core.cache import CachedFile
from memex.core.diff import side_by_side
from memex.core.entities import body_of
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


class PathContent(BaseModel):
    path: str
    content: str


def _saved(response: Response, path: str, version_hash: str) -> dict:
    """A read or write's version token, as `ETag` and in the body (§5.3)."""
    response.headers["ETag"] = f'"{version_hash}"'
    return {"path": path, "hash": version_hash}


def expected_hash(if_match: str | None) -> str:
    if not if_match:
        raise Validation("If-Match is required: send the hash you last read")
    return if_match.strip().removeprefix("W/").strip('"')


@router.get("/tree")
def tree(ws: WS) -> dict:
    return {
        "folders": ws.cache.folders(),
        "files": [_tree_file(f) for f in ws.cache.files()],
        "workspace": {  # for the shell's banners (§11.2)
            "read_only": ws.read_only,
            "config_error": ws.config_error and ws.config_error.message,
            "me_set": ws.me() is not None,
        },
    }


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
def create_file(ws: WS, body: PathContent, response: Response) -> dict:
    return _saved(response, body.path, ws.store.create(body.path, body.content))


@router.put("/files")
def write_file(
    ws: WS,
    body: PathContent,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> dict:
    new_hash = ws.store.write(body.path, body.content, expected_hash(if_match))
    return _saved(response, body.path, new_hash)


class FolderPath(BaseModel):
    path: str


class Move(BaseModel):
    source: str = Field(alias="from")
    to: str
    overwrite: bool = False


@router.post("/folders", status_code=201)
def new_folder(ws: WS, body: FolderPath) -> dict:
    ws.store.make_folder(body.path, exist_ok=False)
    return {"path": body.path}


@router.post("/move")
def move(ws: WS, body: Move) -> dict:
    """Rename or move a file or folder (R14); typed Entities stay in their folder (§11.8)."""
    ws.move(body.source, body.to, body.overwrite)
    return {"from": body.source, "to": body.to}


@router.delete("/files")
def delete(ws: WS, path: Annotated[str, Query()]) -> dict:
    """Delete a file or folder to trash (§8.4)."""
    return {"path": path, "trash": ws.trash(path)}


class DiffRequest(PathContent):
    part: Literal["file", "body"] = "file"  # "body": an Entity page's body editor


@router.post("/diff")
def diff(ws: WS, body: DiffRequest) -> dict:
    """Compare the editor's text with what is on disk now (§5.7)."""
    disk = _read(ws, body.path)
    if body.part == "body":
        disk = body_of(disk)
    rows = side_by_side(disk.text, body.content)
    return {
        "path": body.path,
        "hash": disk.hash,
        "rows": [{"kind": r.kind, "disk": r.disk, "mine": r.mine} for r in rows],
    }


def _read(ws: Workspace, path: str) -> FileVersion:
    try:
        return ws.store.read(path)
    except UnicodeDecodeError:
        raise Validation(f"{path} isn't UTF-8 text, so Memex can't open it") from None
