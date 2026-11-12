"""The `/api/*` routes built so far (SPEC §17.2)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import BaseModel

from memex.core.errors import NotFound, Validation
from memex.core.store import FileVersion
from memex.core.workspace import Workspace

router = APIRouter(prefix="/api")


def workspace(request: Request) -> Workspace:
    ws = request.app.state.memex.workspace
    if ws is None:
        raise NotFound("Workspace")  # Setup isn't done yet (§3.3)
    return ws


WS = Annotated[Workspace, Depends(workspace)]


class NewFile(BaseModel):
    path: str
    content: str


def _etag(hash: str) -> str:
    return f'"{hash}"'


def _expected_hash(if_match: str | None) -> str:
    if not if_match:
        raise Validation("If-Match is required: send the hash you last read")
    return if_match.strip().removeprefix("W/").strip('"')


@router.get("/tree")
def tree(ws: WS) -> dict:
    return {
        "folders": ws.cache.folders(),
        "files": [
            {
                "path": f.rel,
                "id": f.id,
                "type": f.type,
                "title": f.title,
                "hash": f.hash,
                "warnings": [
                    {"kind": w.kind, "message": w.message, "line": w.line} for w in f.warnings
                ],
            }
            for f in ws.cache.files()
        ],
    }


@router.get("/files")
def read_file(ws: WS, response: Response, path: Annotated[str, Query()]) -> dict:
    version = _read(ws, path)
    response.headers["ETag"] = _etag(version.hash)
    return {"path": path, "content": version.text, "hash": version.hash}


@router.post("/files", status_code=201)
def create_file(ws: WS, body: NewFile, response: Response) -> dict:
    hash = ws.store.create(body.path, body.content)
    response.headers["ETag"] = _etag(hash)
    return {"path": body.path, "hash": hash}


@router.put("/files")
def write_file(
    ws: WS,
    body: NewFile,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> dict:
    hash = ws.store.write(body.path, body.content, _expected_hash(if_match))
    response.headers["ETag"] = _etag(hash)
    return {"path": body.path, "hash": hash}


def _read(ws: Workspace, path: str) -> FileVersion:
    try:
        return ws.store.read(path)
    except UnicodeDecodeError:
        raise Validation(f"{path} isn't UTF-8 text, so Memex can't open it") from None
