"""The Bookmarks routes (SPEC §10.1, §17.2)."""

from typing import Annotated

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field

from memex.core import bookmarks
from memex.core.bookmarks import Bookmark
from memex.core.workspace import BOOKMARKS
from memex.web.api import WS

router = APIRouter(prefix="/api")


class NewBookmark(BaseModel):
    url: str
    title: str = ""
    note: str = ""
    labels: list[str] = Field(default_factory=list)


@router.get("/bookmarks")
def bookmark_list(ws: WS, label: Annotated[str | None, Query()] = None) -> dict:
    view = bookmarks.bookmarks_view(ws, label or None)
    return {
        "lines": [
            {"line": r.line, "text": r.text, "bookmark": r.bookmark and bookmark_json(r.bookmark)}
            for r in view.lines
        ],
        "labels": list(view.labels),
    }


@router.post("/bookmarks", status_code=201)
def add_bookmark(ws: WS, body: NewBookmark, response: Response) -> dict:
    saved = bookmarks.add_bookmark(ws, body.url, body.title, body.note, body.labels)
    response.headers["ETag"] = f'"{saved}"'
    return {"path": BOOKMARKS, "hash": saved}


def bookmark_json(b: Bookmark) -> dict:
    return {
        "line": b.line,
        "title": b.title,
        "url": b.url,
        "note": b.note,
        "labels": list(b.labels),
    }
