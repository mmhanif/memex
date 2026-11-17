"""Lifecycle routes (SPEC §17.2): Rename id, guided delete, trash, Broken references."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from memex.core import lifecycle
from memex.core.lifecycle import BrokenGroup, Impact, Outcome, Trashed, Use
from memex.core.schema import type_named
from memex.core.store import WORKSPACE_CONFIG
from memex.web.api import WS

router = APIRouter(prefix="/api")


class Rename(BaseModel):
    new_id: str
    dry_run: bool = True
    hashes: dict[str, str] = Field(default_factory=dict)  # the preview's, by path


class Delete(BaseModel):
    mode: lifecycle.DeleteMode = "plain"
    replacement: str | None = None
    dry_run: bool = True
    hashes: dict[str, str] = Field(default_factory=dict)


class Restore(BaseModel):
    entry: str


class Repair(BaseModel):
    id: str
    action: lifecycle.RepairAction
    replacement: str | None = None
    type: str | None = None  # for Create when the references allow several types
    dry_run: bool = False
    hashes: dict[str, str] = Field(default_factory=dict)


@router.post("/entities/{id}/rename")
def rename(ws: WS, id: str, body: Rename) -> dict:
    return outcome_json(lifecycle.rename_id(ws, id, body.new_id, body.dry_run, body.hashes))


@router.post("/entities/{id}/delete")
def delete(ws: WS, id: str, body: Delete) -> dict:
    found = lifecycle.delete_entity(ws, id, body.mode, body.replacement, body.dry_run, body.hashes)
    return outcome_json(found)


@router.get("/trash")
def trash(ws: WS) -> dict:
    return {"entries": [_trashed(t) for t in lifecycle.list_trash(ws)]}


@router.post("/trash/restore")
def restore(ws: WS, body: Restore) -> dict:
    return _trashed(lifecycle.restore(ws, body.entry))


@router.get("/broken-references")
def broken_references(ws: WS) -> dict:
    return {"groups": [_group(g) for g in lifecycle.broken_references(ws)]}


@router.post("/broken-references/repair")
def repair(ws: WS, body: Repair) -> dict:
    kind = "infer" if body.type is None else type_named(body.type)
    found = lifecycle.repair(
        ws, body.id, body.action, body.replacement, kind, body.dry_run, body.hashes
    )
    return outcome_json(found)


def outcome_json(o: Outcome) -> dict:
    return {
        "impact": _impact(o.impact),
        "hashes": o.hashes,
        "applied": o.applied,
        "skipped": [{"path": s.rel, "code": s.code, "message": s.message} for s in o.skipped],
        "id": o.id,
        "path": o.rel,
        "trash": o.trash,
    }


def _impact(i: Impact) -> dict:
    return {
        "summary": i.summary,
        "references": i.references,
        "edits": [
            {
                "path": e.rel,
                "title": e.title,
                "hash": e.hash,
                "fields": list(e.fields),
                "count": e.count,
            }
            for e in i.edits
        ],
        "blocked": [{"path": b.rel, "title": b.title, "field": b.field} for b in i.blocked],
    }


def _trashed(t: Trashed) -> dict:
    return {
        "entry": t.entry,
        "path": t.path,
        "files": list(t.files),
        "deleted": t.deleted and t.deleted.isoformat(),
    }


def _group(g: BrokenGroup) -> dict:
    return {
        "id": g.id,
        "status": g.status,
        "uses": [
            {"path": u.rel, "title": u.title, "type": _use_type(u), "field": u.field}
            for u in g.uses
        ],
        "types": [t or "note" for t in g.types],
        "create_types": [t or "note" for t in g.create_types],
    }


def _use_type(u: Use) -> str | None:
    """The referring file's type; None for the Workspace config."""
    return None if u.rel == WORKSPACE_CONFIG else (u.type or "note")
