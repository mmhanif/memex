"""Lifecycle routes (SPEC §17.2): Rename id, guided delete, trash, Broken references."""

from typing import Annotated

from fastapi import APIRouter, Header, Response
from pydantic import BaseModel, Field

from memex.core import lifecycle
from memex.core.cache import CachedFile
from memex.core.lifecycle import BrokenGroup, Impact, Outcome, Trashed
from memex.core.schema import Target, type_named
from memex.web.api import WS, expected_hash
from memex.web.entities_routes import saved_json

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


class Archive(BaseModel):
    archived: bool


class Restore(BaseModel):
    entry: str


class Repair(BaseModel):
    id: str
    action: lifecycle.RepairAction
    replacement: str | None = None
    type: str | None = None  # for Create when the references allow several types
    dry_run: bool = True
    hashes: dict[str, str] = Field(default_factory=dict)


class RenameClaimant(BaseModel):
    id: str
    path: str
    new_id: str


@router.post("/entities/{id}/rename")
def rename(ws: WS, id: str, body: Rename) -> dict:
    return outcome_json(lifecycle.rename_id(ws, id, body.new_id, body.dry_run, body.hashes))


@router.post("/entities/{id}/delete")
def delete(ws: WS, id: str, body: Delete) -> dict:
    outcome = lifecycle.delete_entity(
        ws, id, body.mode, body.replacement, body.dry_run, body.hashes
    )
    return outcome_json(outcome)


@router.post("/entities/{id}/archive")
def archive(
    ws: WS,
    id: str,
    body: Archive,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> dict:
    """Archive (`archived: <today>`, Themes and Persons only) or Unarchive (§8.3)."""
    change = lifecycle.archive if body.archived else lifecycle.unarchive
    return saved_json(response, change(ws, id, expected_hash(if_match)))


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
    as_type = "infer" if body.type is None else type_named(body.type)
    outcome = lifecycle.repair(
        ws, body.id, body.action, body.replacement, as_type, body.dry_run, body.hashes
    )
    return outcome_json(outcome)


@router.post("/broken-references/rename")
def rename_claimant(ws: WS, body: RenameClaimant) -> dict:
    """Rename id… for one of the files sharing an ambiguous Id (§8.5)."""
    return {"path": lifecycle.rename_claimant(ws, body.id, body.path, body.new_id)}


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
    d, block = t.deletion, t.blocked
    return {
        "entry": t.entry,
        "path": t.path,
        "files": list(t.files),
        "deleted": t.deleted and t.deleted.isoformat(),
        "type": t.type,
        "id": t.id,
        "title": t.title,
        "deletion": d and d.record(),
        "blocked": block
        and {
            "reason": block.reason,
            "path": block.path,
            "id": block.id,
            "by": block.by and _file(block.by),
        },
    }


def _file(f: CachedFile) -> dict:
    return {"id": f.id, "title": f.title, "type": _type_name(f.type), "path": f.rel}


def _group(g: BrokenGroup) -> dict:
    return {
        "id": g.id,
        "status": g.status,
        "uses": [
            {
                "path": u.rel,
                "id": u.id,
                "title": u.title,
                "type": None if u.id is None else _type_name(u.type),
                "field": u.field,
                "snippet": u.snippet and list(u.snippet),
                "targets": [_type_name(t) for t in u.targets],
            }
            for u in g.uses
        ],
        "types": [_type_name(t) for t in g.types],
        "create_types": [_type_name(t) for t in g.create_types],
        "claimants": [_file(f) for f in g.claimants],
    }


def _type_name(t: Target) -> str:
    """A type as the API spells it: a Note is `note`."""
    return t or "note"
