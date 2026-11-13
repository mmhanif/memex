"""Entity and Template routes (SPEC §17.2): `/api/entities*` and `/api/templates*`."""

import datetime as dt
from collections.abc import Mapping
from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Response
from pydantic import BaseModel, Field

from memex.core import entities
from memex.core.cache import CachedFile
from memex.core.entities import BrokenReference, Saved
from memex.core.errors import Validation
from memex.core.schema import EntityType
from memex.core.templates import Template, customise_template, render, templates_for, type_for_key
from memex.web.api import WS, expected_hash

router = APIRouter(prefix="/api")


class NewEntity(BaseModel):
    type: str
    fields: dict[str, Any] = Field(default_factory=dict)
    body: str | None = None
    template: str | None = None


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
    entity_type = type_for_key(_template_key(type)) if type else None
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
    return {
        **summary(detail.file, detail.warnings),
        "body": detail.file.body,
        "read_only": detail.file.read_only or ws.read_only,
        "broken": [_broken(b) for b in detail.broken],
        "names": dict(detail.names),
        "children": [summary(f) for f in detail.children],
        "todos": [summary(f) for f in detail.todos],
        "notes": [summary(f) for f in detail.notes],
        "mentioned_in": [summary(f) for f in detail.mentioned_in],
    }


@router.post("/entities", status_code=201)
def create_entity(ws: WS, body: NewEntity, response: Response) -> dict:
    entity_type = type_for_key(_template_key(body.type))
    return _saved(
        response, entities.create_entity(ws, entity_type, body.fields, body.body, body.template)
    )


@router.patch("/entities/{id}")
def update_fields(
    ws: WS,
    id: str,
    body: FieldChanges,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> dict:
    saved = entities.update_fields(ws, id, expected_hash(if_match), body.set, body.unset)
    return _saved(response, saved)


@router.put("/entities/{id}/body")
def replace_body(
    ws: WS,
    id: str,
    body: NewBody,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> dict:
    return _saved(response, entities.replace_body(ws, id, body.body, expected_hash(if_match)))


@router.get("/templates")
def list_templates(ws: WS, type: Annotated[str, Query()]) -> dict:
    found = templates_for(ws.root, type_for_key(type), ws.config.hidden_templates)
    me = ws.me()
    return {
        "templates": [_template(t, ws, me.id if me else None) for t in found.templates],
        "default": found.default.key,
        "warnings": list(found.warnings),
    }


@router.post("/templates/customise", status_code=201)
def customise(ws: WS, body: TemplateName) -> dict:
    return {"path": customise_template(ws, type_for_key(body.type), body.name)}


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


def _template(t: Template, ws: Any, me: str | None) -> dict:
    fields, body = render(t, "{{title}}", ws.clock.today(), me)
    return {
        "key": t.key,
        "name": t.name,
        "label": t.label,
        "source": t.source,
        "default": t.default,
        "hidden": t.hidden,
        "overrides": t.overrides,
        "error": t.error,
        "path": t.path,
        "fields": jsonable(fields),
        "body": body,
    }


def _broken(b: BrokenReference) -> dict:
    return {"field": b.field, "id": b.id, "status": b.status}


def _saved(response: Response, saved: Saved) -> dict:
    response.headers["ETag"] = f'"{saved.hash}"'
    return {"id": saved.id, "path": saved.rel, "hash": saved.hash}


def _template_key(type: str) -> str:
    """API types are Entity types (`glossary-term`) or `note`; Template keys say `glossary`."""
    if type == EntityType.GLOSSARY_TERM.value:
        return "glossary"
    if type == "glossary":
        raise Validation("Unknown type 'glossary': use glossary-term")
    return type
