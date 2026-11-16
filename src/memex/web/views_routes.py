"""Quick-add and the view routes (SPEC §6.2, §6.3, §11.3, §11.4, §11.6, §17.2)."""

from collections.abc import Iterable
from typing import Annotated

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field

from memex.core import entities, quickadd, views
from memex.core.cache import CachedFile
from memex.core.errors import Validation
from memex.core.workspace import Workspace
from memex.web.api import WS
from memex.web.entities_routes import detail_json, summary

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
        "errors": [
            {
                "field": e.field,
                "token": e.token,
                "message": e.message,
                "candidates": list(e.candidates),
            }
            for e in parsed.errors
        ],
        "names": _names(ws, [parsed.owner, parsed.requester]),
    }


@router.post("/todos/quick-add", status_code=201)
def quick_add(ws: WS, body: QuickAddText, response: Response) -> dict:
    saved = quickadd.quick_add(ws, body.text, body.defaults)
    response.headers["ETag"] = f'"{saved.hash}"'
    return {"id": saved.id, "path": saved.rel, "hash": saved.hash}


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
        "get_started": d.get_started,
        "names": _todo_names(ws, groups, shown_todos),
    }


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
) -> dict:
    """The board or the outline (§11.3). `themes` is a comma-separated list of Theme Ids."""
    chosen = [t for t in (t.strip() for t in themes.split(",")) if t]
    if mode == "board":
        board = views.portfolio_board(ws, kind, chosen, include_archived)
        shown = [f for c in board.columns for f in c.items]
        return {
            "mode": "board",
            "kind": board.kind,
            "columns": [
                {"status": c.status, "items": [summary(f) for f in c.items]} for c in board.columns
            ],
            "chips": [summary(t) for t in board.chips],
            "names": _work_names(ws, shown),
        }
    if mode != "outline":
        raise Validation(f"Unknown Portfolio mode {mode!r}: one of {', '.join(PORTFOLIO_MODES)}")
    outline = views.portfolio_outline(ws, chosen, include_archived)
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
