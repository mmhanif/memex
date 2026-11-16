"""Search (SPEC §9, §17.2): ranked rows plus the parsed filters and token errors."""

from typing import Annotated

from fastapi import APIRouter, Query

from memex.core.search import Hit, Snippet, context_of, search, status_group
from memex.core.workspace import Workspace
from memex.web.api import WS

router = APIRouter(prefix="/api")

MAX_LIMIT = 200


@router.get("/search")
def search_route(
    ws: WS,
    q: Annotated[str, Query()] = "",
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    include_archived: Annotated[bool, Query()] = True,
    hide_completed: Annotated[bool, Query()] = False,
) -> dict:
    result = search(ws, q, limit, offset, include_archived, hide_completed)
    query = result.query
    return {
        "query": {
            "text": query.text,
            "filters": [
                {"kind": f.kind, "values": list(f.values), "token": f.token} for f in query.filters
            ],
            "errors": [
                {"token": e.token, "message": e.message, "candidates": list(e.candidates)}
                for e in query.errors
            ],
        },
        "total": result.total,
        "counts": result.counts,
        "hits": [_hit(ws, h) for h in result.hits],
    }


def _hit(ws: Workspace, h: Hit) -> dict:
    snippets = [_snippet(s) for s in h.snippets]
    if (b := h.bookmark) is not None:
        return {
            "kind": "bookmark",
            "id": h.file.id,
            "type": "bookmark",
            "title": b.title or b.url,
            "path": h.file.rel,
            "tier": h.tier,
            "bookmark": {
                "line": b.line,
                "title": b.title,
                "url": b.url,
                "note": b.note,
                "labels": list(b.labels),
            },
            "snippets": snippets,
        }
    status = h.file.fields.get("status")
    return {
        "kind": "file",
        "id": h.file.id,
        "type": h.type,
        "title": h.file.title,
        "path": h.file.rel,
        "status": "archived" if h.file.fields.get("archived") else status,
        "finished": status_group(h.file) == 2,
        "tier": h.tier,
        "context": context_of(ws, h.file),
        "snippets": snippets,
    }


def _snippet(s: Snippet) -> dict:
    return {"text": s.text, "highlights": [list(span) for span in s.highlights]}
