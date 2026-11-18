"""Quick-add, inline capture and the view routes.

SPEC §6.2, §6.3, §6.4, §10.2, §11.3, §11.4, §11.6, §17.2.
"""

from collections.abc import Iterable
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field

from memex.core import capture, entities, quickadd, views
from memex.core.cache import CachedFile
from memex.core.errors import Validation
from memex.core.quickadd import QuickAddError
from memex.core.workspace import Workspace
from memex.web.api import WS
from memex.web.entities_routes import detail_json, saved_json, summary

router = APIRouter(prefix="/api")

PERSON_COLUMNS = ("waiting-on-them", "waiting-on-me")


class QuickAddText(BaseModel):
    text: str
    defaults: dict[str, str] = Field(default_factory=dict)  # `owner`, `requester` by context


@router.post("/parse/quick-add")
def parse_quick_add(ws: WS, body: QuickAddText) -> dict:
    parsed = quickadd.parse_quick_add(ws, body.text, body.defaults)
    return {
        "title": parsed.title,
        "owner": parsed.owner,
        "requester": parsed.requester,
        "due": parsed.due.isoformat() if parsed.due else None,
        "errors": [_token_error(e) for e in parsed.errors],
        "names": _names(ws, [parsed.owner, parsed.requester]),
    }


def _token_error(e: QuickAddError) -> dict:
    return {
        "field": e.field,
        "token": e.token,
        "message": e.message,
        "candidates": list(e.candidates),
    }


@router.post("/todos/quick-add", status_code=201)
def quick_add(ws: WS, body: QuickAddText, response: Response) -> dict:
    saved = quickadd.quick_add(ws, body.text, body.defaults)
    response.headers["ETag"] = f'"{saved.hash}"'
    return {"id": saved.id, "path": saved.rel, "hash": saved.hash}


class CaptureRow(BaseModel):
    index: int
    edits: dict[str, Any] = Field(default_factory=dict)  # owner, requester, due, about


class CaptureConfirm(BaseModel):
    hash: str
    rows: list[CaptureRow]


@router.get("/notes/{id}/capture")
def capture_preview(ws: WS, id: str, response: Response) -> dict:
    """The "Create N To-dos" preview (§6.4), with the Note's hash to confirm against."""
    p = capture.preview(ws, id)
    response.headers["ETag"] = f'"{p.hash}"'
    return {
        "id": p.note.id,
        "hash": p.hash,
        "rows": [
            {
                "index": r.index,
                "line": r.line,
                "text": r.text,
                "title": r.title,
                "owner": r.owner,
                "requester": r.requester,
                "due": r.due.isoformat() if r.due else None,
                "about": r.about,
                "body": r.body,
                "errors": [_token_error(e) for e in r.errors],
            }
            for r in p.rows
        ],
        "names": _names(ws, [x for r in p.rows for x in (r.owner, r.requester, r.about)]),
    }


@router.post("/notes/{id}/capture", status_code=201)
def capture_confirm(ws: WS, id: str, body: CaptureConfirm, response: Response) -> dict:
    rows = [capture.RowChoice(r.index, r.edits) for r in body.rows]
    done = capture.confirm(ws, id, body.hash, rows)
    return {
        "note": saved_json(response, done.note),
        "todos": [{"id": t.id, "path": t.rel, "hash": t.hash} for t in done.todos],
    }


@router.get("/views/todos")
def todo_view(
    ws: WS,
    view: Annotated[str, Query()],
    person: Annotated[str | None, Query()] = None,
    include_done: Annotated[bool, Query()] = False,
) -> dict:
    """Me's three lists; with `person`, that Person View's columns (`waiting-on-them`
    is what they owe, `waiting-on-me` what they're waiting on)."""
    if person is None:
        groups = views.todo_view(ws, view, include_done).groups
    elif view not in PERSON_COLUMNS:
        raise Validation(f"With person, view is one of {', '.join(PERSON_COLUMNS)}")
    else:
        found = views.person_view(ws, person, include_done)
        groups = found.waiting_on_them if view == "waiting-on-them" else found.waiting_on_me
    return {"view": view, "groups": _groups(groups), "names": _todo_names(ws, groups)}


@router.get("/views/dashboard")
def dashboard(ws: WS) -> dict:
    d = views.dashboard(ws)
    shown_todos = [*d.due_soon, *(d.waiting_on_me or ())]
    groups = d.waiting_on_them or ()
    return {
        "due_soon": [summary(f) for f in d.due_soon],
        "waiting_on_them": None if d.waiting_on_them is None else _groups(d.waiting_on_them),
        "waiting_on_me": None if d.waiting_on_me is None else [summary(t) for t in d.waiting_on_me],
        "blocked": [summary(f) for f in d.blocked],
        "directs": None
        if d.directs is None
        else [
            {
                "person": summary(c.person),
                "waiting_on_them": c.waiting_on_them,
                "waiting_on_me": c.waiting_on_me,
            }
            for c in d.directs
        ],
        "recent_notes": [summary(f) for f in d.recent_notes],
        "capture_notes": [summary(f) for f in d.capture_notes],
        "to_create": d.to_create,
        "get_started": d.get_started,
        "names": {
            **_todo_names(ws, groups, shown_todos),
            **_names(ws, _row_refs([*d.due_soon, *d.blocked, *d.recent_notes])),
        },
    }


def _row_refs(files: Iterable[CachedFile]) -> list[object]:
    """The ids a Dashboard row names: a Deliverable's Project, a Lead, a Note's `about`."""
    refs: list[object] = []
    for f in files:
        for field in ("project", "lead", "about"):
            value = f.fields.get(field)
            refs.extend(value if isinstance(value, list) else [value])
    return refs


@router.get("/views/people")
def people(ws: WS) -> dict:
    p = views.people_view(ws)
    return {
        "manager": p.manager and summary(p.manager),
        "me": p.me and _org(p.me),
        "others": [summary(f) for f in p.others],
        "stakeholders": [{"person": summary(s.file), "tags": s.tags} for s in p.stakeholders],
    }


@router.get("/views/person/{id}")
def person(
    ws: WS, id: str, response: Response, include_done: Annotated[bool, Query()] = False
) -> dict:
    p = views.person_view(ws, id, include_done)
    detail = entities.entity_detail(ws, p.person.id)
    response.headers["ETag"] = f'"{detail.file.hash}"'
    columns = (*p.waiting_on_them, *p.waiting_on_me)
    return {
        "person": detail_json(ws, detail),
        "manager": p.manager and summary(p.manager),
        "directs": [summary(f) for f in p.directs],
        "tagged_on": [{"item": summary(t.file), "roles": list(t.roles)} for t in p.tagged_on],
        "waiting_on_them": _groups(p.waiting_on_them),
        "waiting_on_me": _groups(p.waiting_on_me),
        "notes": [summary(f) for f in p.notes],
        "names": _todo_names(ws, columns),
    }


PORTFOLIO_MODES = ("board", "outline")
# The references a Portfolio row shows by name.
_WORK_REFS = ("theme", "project", "lead", "team", "stakeholders")


@router.get("/views/portfolio")
def portfolio(
    ws: WS,
    mode: Annotated[str, Query()] = "board",
    kind: Annotated[str, Query()] = "project",
    themes: Annotated[str, Query()] = "",
    include_archived: Annotated[bool, Query()] = False,
    unthemed: Annotated[bool, Query()] = False,
) -> dict:
    """The board or the outline (§11.3). `themes` is a comma-separated list of Theme Ids;
    `unthemed` adds the work with no Theme."""
    chosen = [t for t in (t.strip() for t in themes.split(",")) if t]
    if mode == "board":
        board = views.portfolio_board(ws, kind, chosen, include_archived, unthemed)
        shown = [f for c in board.columns for f in c.items]
        return {
            "mode": "board",
            "kind": board.kind,
            "columns": [
                {"status": c.status, "items": [summary(f) for f in c.items]} for c in board.columns
            ],
            "chips": [summary(t) for t in board.chips],
            "attention": {p: [summary(d) for d in ds] for p, ds in board.attention.items()},
            "names": _work_names(ws, shown),
        }
    if mode != "outline":
        raise Validation(f"Unknown Portfolio mode {mode!r}: one of {', '.join(PORTFOLIO_MODES)}")
    outline = views.portfolio_outline(ws, chosen, include_archived, unthemed)
    shown = [
        *(f for g in outline.themes for f in ([g.theme] if g.theme else [])),
        *(p.project for g in outline.themes for p in g.projects),
        *(d for g in outline.themes for p in g.projects for d in p.deliverables),
        *outline.without_project,
    ]
    return {
        "mode": "outline",
        "themes": [
            {
                "theme": g.theme and summary(g.theme),
                "projects": [
                    {
                        "project": summary(p.project),
                        "deliverables": [summary(d) for d in p.deliverables],
                    }
                    for p in g.projects
                ],
            }
            for g in outline.themes
        ],
        "without_project": [summary(d) for d in outline.without_project],
        "chips": [summary(t) for t in outline.chips],
        "names": _work_names(ws, shown),
    }


@router.get("/views/glossary")
def glossary(ws: WS) -> dict:
    return {
        "groups": [
            {
                "letter": g.letter,
                "terms": [
                    {
                        "id": t.file.id,
                        "title": t.file.title,
                        "aliases": list(t.aliases),
                        "definition": t.definition,
                    }
                    for t in g.terms
                ],
            }
            for g in views.glossary_view(ws).groups
        ]
    }


def _work_names(ws: Workspace, shown: Iterable[CachedFile]) -> dict[str, str]:
    """Titles of the Themes, Projects, Leads and Tagged Persons named on the rows shown."""
    ids: list[object] = []
    for f in shown:
        for field in _WORK_REFS:
            value = f.fields.get(field)
            ids.extend(value if isinstance(value, list) else [value])
    return _names(ws, ids)


def _groups(groups: Iterable[views.TodoGroup]) -> list[dict]:
    return [
        {"label": g.label, "person": g.person, "todos": [summary(t) for t in g.todos]}
        for g in groups
    ]


def _org(node: views.OrgNode) -> dict:
    return {"person": summary(node.person), "directs": [_org(d) for d in node.directs]}


def _todo_names(
    ws: Workspace, groups: Iterable[views.TodoGroup], more: Iterable[CachedFile] = ()
) -> dict[str, str]:
    """Titles of the Owners and Requesters of the To-dos shown, for their rows."""
    shown = [*(t for g in groups for t in g.todos), *more]
    return _names(ws, [t.fields.get(field) for t in shown for field in ("owner", "requester")])


def _names(ws: Workspace, ids: Iterable[object]) -> dict[str, str]:
    return {
        id: found.title
        for id in ids
        if isinstance(id, str) and (found := ws.cache.resolve(id).file) is not None
    }
