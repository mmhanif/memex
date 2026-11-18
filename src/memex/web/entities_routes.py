"""Entity and Template routes (SPEC §17.2): `/api/entities*` and `/api/templates*`."""

import datetime as dt
from collections.abc import Mapping
from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Response
from pydantic import BaseModel, Field

from memex.core import capture, entities, lifecycle
from memex.core.cache import CachedFile
from memex.core.entities import BrokenReference, Saved
from memex.core.schema import EntityType, type_named
from memex.core.templates import Template, customise_template, render, templates_for
from memex.core.workspace import Workspace
from memex.web.api import WS, expected_hash

router = APIRouter(prefix="/api")


class NewEntity(BaseModel):
    type: str
    fields: dict[str, Any] = Field(default_factory=dict)
    body: str | None = None
    template: str | None = None
    folder: str | None = None  # Notes only: the Files page's "New file here" (§7.4)


class FieldChanges(BaseModel):
    set: dict[str, Any] = Field(default_factory=dict)
    unset: list[str] = Field(default_factory=list)


class NewBody(BaseModel):
    body: str


class TemplateName(BaseModel):
    type: str
    name: str


@router.get("/entities")
def list_entities(
    ws: WS,
    type: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
    theme: Annotated[str | None, Query()] = None,
    project: Annotated[str | None, Query()] = None,
    person: Annotated[str | None, Query()] = None,
    label: Annotated[str | None, Query()] = None,
    due_before: Annotated[dt.date | None, Query()] = None,
    include_archived: Annotated[bool, Query()] = False,
) -> dict:
    entity_type = type_named(type) if type else None
    found = entities.list_entities(
        ws,
        type=entity_type,
        notes=type == "note",
        status=status,
        theme=theme,
        project=project,
        person=person,
        label=label,
        due_before=due_before,
        include_archived=include_archived,
    )
    return {"entities": [summary(f) for f in found]}


@router.get("/entities/{id}")
def entity_detail(ws: WS, id: str, response: Response) -> dict:
    detail = entities.entity_detail(ws, id)
    response.headers["ETag"] = f'"{detail.file.hash}"'
    return detail_json(ws, detail)


def detail_json(ws: Workspace, detail: entities.EntityDetail) -> dict:
    """The Entity page's data (§11.5); the Person View carries it too (§11.6)."""
    return {
        **summary(detail.file, detail.warnings),
        "body": detail.file.body,
        "read_only": detail.file.read_only or ws.read_only,
        "broken": [_broken(b) for b in detail.broken],
        "names": dict(detail.names),
        "children": [summary(f) for f in detail.children],
        "todos": [summary(f) for f in detail.todos],
        "notes": [summary(f) for f in detail.notes],
        "mentioned_in": [
            {**summary(f), "context": entities.mention_context(f.body, detail.file.id)}
            for f in detail.mentioned_in
        ],
        # Mentioned To-dos, so a converted task item renders as a live To-do row (§6.4).
        "mentioned_todos": [summary(f) for f in _mentioned_todos(ws, detail.file)],
        # Archive (§8.3): Themes and Persons, and what it would leave hanging.
        "archivable": detail.file.type in lifecycle.ARCHIVABLE,
        "loose_ends": [
            {"label": e.label, "items": [summary(f) for f in e.items]}
            for e in lifecycle.loose_ends(ws, detail.file.id)
        ],
        # Notes: task items "Create N To-dos" would offer (§6.4).
        **(
            {"unconverted_todos": len(capture.task_items(ws, detail.file.body))}
            if detail.file.type is None
            else {}
        ),
    }


@router.post("/entities", status_code=201)
def create_entity(ws: WS, body: NewEntity, response: Response) -> dict:
    entity_type = type_named(body.type)
    return saved_json(
        response,
        entities.create_entity(ws, entity_type, body.fields, body.body, body.template, body.folder),
    )


@router.post("/entities/placement")
def entity_placement(ws: WS, body: NewEntity) -> dict:
    """Where + New… would put the file: the form's live Id/path preview (§11.7)."""
    id, rel = entities.placement(ws, type_named(body.type), body.fields, body.folder)
    return {"id": id, "path": rel, "created": ws.clock.today().isoformat()}


@router.patch("/entities/{id}")
def update_fields(
    ws: WS,
    id: str,
    body: FieldChanges,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> dict:
    saved = entities.update_fields(ws, id, expected_hash(if_match), body.set, body.unset)
    return saved_json(response, saved)


@router.put("/entities/{id}/body")
def replace_body(
    ws: WS,
    id: str,
    body: NewBody,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> dict:
    return saved_json(response, entities.replace_body(ws, id, body.body, expected_hash(if_match)))


@router.get("/templates")
def list_templates(ws: WS, type: Annotated[str, Query()]) -> dict:
    found = templates_for(ws.root, type_named(type), ws.config.hidden_templates)
    me = ws.me()
    return {
        "templates": [_template(t, ws, me.id if me else None) for t in found.templates],
        "default": found.default.key,
        "warnings": list(found.warnings),
    }


@router.post("/templates/customise", status_code=201)
def customise(ws: WS, body: TemplateName) -> dict:
    return {"path": customise_template(ws, type_named(body.type), body.name)}


def summary(f: CachedFile, warnings: tuple = ()) -> dict:
    return {
        "id": f.id,
        "type": f.type.value if f.type else "note",
        "path": f.rel,
        "title": f.title,
        "hash": f.hash,
        "fields": jsonable(f.fields),
        "ambiguous": f.ambiguous,
        "warnings": [
            {"kind": w.kind, "message": w.message, "line": w.line} for w in (warnings or f.warnings)
        ],
    }


def jsonable(value: Any) -> Any:
    """YAML values as JSON: dates become `YYYY-MM-DD`."""
    if isinstance(value, Mapping):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(v) for v in value]
    if isinstance(value, dt.date | dt.datetime):
        return value.isoformat()
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _template(t: Template, ws: Workspace, me: str | None) -> dict:
    """A Template as the form shows it: placeholders filled, except `{{title}}` (and
    `{{me}}` while Me isn't set)."""
    fields, body = render(t, "{{title}}", ws.clock.today(), me or "{{me}}")
    return {
        "key": t.key,
        "name": t.name,
        "display_name": t.display_name,
        "source": t.source,
        "default": t.default,
        "hidden": t.hidden,
        "overrides": t.overrides,
        "error": t.error,
        "path": t.path,
        "fields": jsonable(fields),
        "body": body,
    }


def _mentioned_todos(ws: Workspace, f: CachedFile) -> list[CachedFile]:
    found = (ws.cache.resolve(m).file for m in dict.fromkeys(m.casefold() for m in f.mentions))
    return [t for t in found if t is not None and t.type is EntityType.TODO]


def _broken(b: BrokenReference) -> dict:
    return {"field": b.field, "id": b.id, "status": b.status}


def saved_json(response: Response, saved: Saved) -> dict:
    response.headers["ETag"] = f'"{saved.hash}"'
    return {"id": saved.id, "path": saved.rel, "hash": saved.hash}
