"""Read-only views over the parse cache: To-dos, Dashboard, People, Person View
(SPEC §6.2, §11.3, §11.4, §11.6).

Views read leniently (§4.5): a To-do with a bad `status` counts as open and a bad
`due` as undated. Ids compare ignoring case (§4.1).
"""

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from memex.core.cache import CachedFile
from memex.core.entities import find, refers
from memex.core.errors import NotFound, Validation
from memex.core.schema import FINISHED_TODO, EntityType, parse_date
from memex.core.workspace import BOOKMARKS, Workspace

TodoViewName = Literal["mine", "waiting-on-them", "waiting-on-me"]
TODO_VIEWS: tuple[TodoViewName, ...] = ("mine", "waiting-on-them", "waiting-on-me")


@dataclass(frozen=True)
class TodoGroup:
    label: str
    todos: tuple[CachedFile, ...]
    person: str | None = None  # the Owner or Requester the group is for


@dataclass(frozen=True)
class TodoView:
    view: TodoViewName
    groups: tuple[TodoGroup, ...]


def todo_view(ws: Workspace, view: str, include_done: bool = False) -> TodoView:
    """One of Me's three To-do lists (§6.2). Raises MeNotSet without Me."""
    if view not in TODO_VIEWS:
        raise Validation(f"Unknown To-do view {view!r}: one of {', '.join(TODO_VIEWS)}")
    me = ws.require_me().id
    if view == "mine":
        picked = [t for t in todos(ws) if same(t.fields.get("owner"), me)]
        return TodoView("mine", _by_due(ws, picked, include_done))
    if view == "waiting-on-them":
        picked = [
            t
            for t in todos(ws)
            if same(t.fields.get("requester"), me) and not same(t.fields.get("owner"), me)
        ]
        return TodoView("waiting-on-them", _by_party(ws, picked, "owner", include_done))
    picked = [
        t
        for t in todos(ws)
        if same(t.fields.get("owner"), me) and not same(t.fields.get("requester"), me)
    ]
    return TodoView("waiting-on-me", _by_party(ws, picked, "requester", include_done))


def todos(ws: Workspace) -> list[CachedFile]:
    return [f for f in ws.cache.files() if f.type is EntityType.TODO]


def is_open(todo: CachedFile) -> bool:
    return todo.fields.get("status") not in FINISHED_TODO


def same(value: Any, id: str) -> bool:
    """Whether a reference field's value names `id`, ignoring case."""
    return isinstance(value, str) and value.casefold() == id.casefold()


def due_of(f: CachedFile) -> dt.date | None:
    return parse_date(f.fields.get("due"))


def by_due(f: CachedFile) -> tuple[dt.date, str, str]:
    """Soonest first, undated last, then by title."""
    return (due_of(f) or dt.date.max, f.title.casefold(), f.id)


def _by_due(ws: Workspace, picked: list[CachedFile], include_done: bool) -> tuple[TodoGroup, ...]:
    today = ws.clock.today()
    sunday = today + dt.timedelta(days=6 - today.weekday())
    buckets: dict[str, list[CachedFile]] = {
        "Overdue": [],
        "This week": [],
        "Later": [],
        "No date": [],
    }
    for t in filter(is_open, picked):
        due = due_of(t)
        if due is None:
            buckets["No date"].append(t)
        elif due < today:
            buckets["Overdue"].append(t)
        elif due <= sunday:
            buckets["This week"].append(t)
        else:
            buckets["Later"].append(t)
    groups = [TodoGroup(label, tuple(sorted(ts, key=by_due))) for label, ts in buckets.items()]
    return _with_completed(groups, picked, include_done)


def _by_party(
    ws: Workspace, picked: list[CachedFile], field: str, include_done: bool
) -> tuple[TodoGroup, ...]:
    by_person: dict[str, list[CachedFile]] = {}
    for t in filter(is_open, picked):
        by_person.setdefault(str(t.fields.get(field) or ""), []).append(t)
    groups = [
        TodoGroup(title_of(ws, person), tuple(sorted(ts, key=by_due)), person or None)
        for person, ts in by_person.items()
    ]
    groups.sort(key=lambda g: (g.label.casefold(), g.person or ""))
    return _with_completed(groups, picked, include_done)


def _with_completed(
    groups: Iterable[TodoGroup], picked: list[CachedFile], include_done: bool
) -> tuple[TodoGroup, ...]:
    """Drop empty groups; with Show completed, finished To-dos go last, newest first."""
    kept = [g for g in groups if g.todos]
    if include_done:
        done = sorted(
            (t for t in picked if not is_open(t)),
            key=_completed_key,
            reverse=True,
        )
        if done:
            kept.append(TodoGroup("Completed", tuple(done)))
    return tuple(kept)


def _completed_key(t: CachedFile) -> tuple[dt.date, str]:
    return (parse_date(t.fields.get("completed")) or dt.date.min, t.title.casefold())


def title_of(ws: Workspace, id: str | None) -> str:
    """A referenced file's title, or the Id as written when it doesn't resolve."""
    if not id:
        return "(nobody)"
    found = ws.cache.resolve(id).file
    return found.title if found else id


# Person View (§11.6)

_ROLES = (("lead", "Lead"), ("team", "Team"), ("stakeholders", "Stakeholder"))
WORK = (EntityType.THEME, EntityType.PROJECT, EntityType.DELIVERABLE)


@dataclass(frozen=True)
class Tagged:
    """A work item a Person is the Lead of or Tagged on, with their roles."""

    file: CachedFile
    roles: tuple[str, ...]


@dataclass(frozen=True)
class PersonView:
    person: CachedFile
    manager: CachedFile | None
    directs: tuple[CachedFile, ...]
    tagged_on: tuple[Tagged, ...]
    waiting_on_them: tuple[TodoGroup, ...]  # Owner is the Person
    waiting_on_me: tuple[TodoGroup, ...]  # Requester is the Person, Owner someone else
    notes: tuple[CachedFile, ...]  # Notes whose Participants include them, newest first


def person_view(ws: Workspace, id: str, include_done: bool = False) -> PersonView:
    person = _person(ws, id)
    pid = person.id
    owned = [t for t in todos(ws) if same(t.fields.get("owner"), pid)]
    requested = [
        t
        for t in todos(ws)
        if same(t.fields.get("requester"), pid) and not same(t.fields.get("owner"), pid)
    ]
    manager = person.fields.get("manager")
    found_manager = ws.cache.resolve(manager).file if isinstance(manager, str) else None
    return PersonView(
        person=person,
        manager=found_manager,
        directs=tuple(directs_of(ws, pid)),
        tagged_on=tuple(tagged_on(ws, pid)),
        waiting_on_them=_one_list(owned, include_done),
        waiting_on_me=_one_list(requested, include_done),
        notes=tuple(
            sorted(
                (f for f in ws.cache.files() if f.type is None and refers(f, ["people"], pid)),
                key=_note_order,
            )
        ),
    )


def _person(ws: Workspace, id: str) -> CachedFile:
    found = find(ws, id)
    if found.type is not EntityType.PERSON:
        raise NotFound(id)
    return found


def _one_list(picked: list[CachedFile], include_done: bool) -> tuple[TodoGroup, ...]:
    open_ones = TodoGroup("Open", tuple(sorted(filter(is_open, picked), key=by_due)))
    return _with_completed([open_ones], picked, include_done)


def directs_of(ws: Workspace, id: str) -> list[CachedFile]:
    """Persons whose `manager` is `id`, archived ones left out, by name."""
    return sorted(
        (
            f
            for f in ws.cache.files()
            if f.type is EntityType.PERSON
            and not f.fields.get("archived")
            and same(f.fields.get("manager"), id)
        ),
        key=_by_title,
    )


def tagged_on(ws: Workspace, id: str) -> list[Tagged]:
    found = []
    for f in ws.cache.files():
        if f.type not in WORK:
            continue
        roles = tuple(label for field, label in _ROLES if refers(f, [field], id))
        if roles:
            found.append(Tagged(f, roles))
    return sorted(found, key=lambda t: _by_title(t.file))


def _by_title(f: CachedFile) -> tuple[str, str]:
    return (f.title.casefold(), f.id)


def _note_order(f: CachedFile) -> tuple[int, float]:
    """Newest `date` first; undated Notes after, most recently modified first."""
    date = parse_date(f.fields.get("date"))
    return (-date.toordinal(), 0.0) if date else (1, -f.mtime)


# People page (§11.3)


@dataclass(frozen=True)
class OrgNode:
    person: CachedFile
    reports: tuple[OrgNode, ...]


@dataclass(frozen=True)
class Stakeholder:
    file: CachedFile
    tags: int  # work items they Lead or are Tagged on


@dataclass(frozen=True)
class PeopleView:
    manager: CachedFile | None  # Me's Manager, shown above Me
    me: OrgNode | None  # None while Me isn't set
    others: tuple[CachedFile, ...]  # Team Members outside Me's tree
    stakeholders: tuple[Stakeholder, ...]


def people_view(ws: Workspace) -> PeopleView:
    """The org tree from Me, other Team Members, and the Stakeholders table.

    Archived Persons are left out. A manager cycle is cut where it comes back round.
    """
    me = ws.me()
    shown: set[str] = set()
    root = manager = None
    if me is not None:
        root = _org_tree(ws, me, shown)
        boss = me.fields.get("manager")
        manager = ws.cache.resolve(boss).file if isinstance(boss, str) else None
        if manager is not None:
            shown.add(manager.id.casefold())
    persons = sorted(
        (
            f
            for f in ws.cache.files()
            if f.type is EntityType.PERSON and not f.fields.get("archived")
        ),
        key=_by_title,
    )
    return PeopleView(
        manager=manager,
        me=root,
        others=tuple(
            p
            for p in persons
            if (_kind(p, "team-member") or not _kind(p, "stakeholder"))
            and p.id.casefold() not in shown
        ),
        stakeholders=tuple(
            Stakeholder(p, len(tagged_on(ws, p.id))) for p in persons if _kind(p, "stakeholder")
        ),
    )


def _org_tree(ws: Workspace, person: CachedFile, shown: set[str]) -> OrgNode:
    shown.add(person.id.casefold())
    reports = [d for d in directs_of(ws, person.id) if d.id.casefold() not in shown]
    shown.update(d.id.casefold() for d in reports)
    return OrgNode(person, tuple(_org_tree(ws, d, shown) for d in reports))


def _kind(person: CachedFile, kind: str) -> bool:
    kinds = person.fields.get("kind")
    return isinstance(kinds, list) and kind in kinds


# Dashboard (§11.4)

RECENT_NOTES = 10
DUE_SOON_DAYS = 7
_FINISHED_WORK = ("done", "cancelled")


@dataclass(frozen=True)
class DirectCounts:
    person: CachedFile
    waiting_on_them: int  # open To-dos they owe Me
    waiting_on_me: int  # open To-dos they're waiting on from Me


@dataclass(frozen=True)
class Dashboard:
    """Cards that need Me are None while Me isn't set (§3.5)."""

    due_soon: tuple[CachedFile, ...]
    waiting_on_them: tuple[TodoGroup, ...] | None
    waiting_on_me: tuple[CachedFile, ...] | None
    blocked: tuple[CachedFile, ...]
    directs: tuple[DirectCounts, ...] | None
    recent_notes: tuple[CachedFile, ...]
    get_started: bool  # no Entity besides Me yet


def dashboard(ws: Workspace) -> Dashboard:
    me = ws.me()
    files = ws.cache.files()
    work = [f for f in files if f.type in (EntityType.PROJECT, EntityType.DELIVERABLE)]
    horizon = ws.clock.today() + dt.timedelta(days=DUE_SOON_DAYS)
    open_todos = [t for t in todos(ws) if is_open(t)]

    def soon(f: CachedFile) -> bool:
        due = due_of(f)
        return due is not None and due <= horizon

    due_soon = [f for f in work if f.fields.get("status") not in _FINISHED_WORK and soon(f)]
    waiting_on_them = waiting_on_me = directs = None
    if me is not None:
        mine = [t for t in open_todos if same(t.fields.get("owner"), me.id)]
        due_soon += [t for t in mine if soon(t)]
        waiting_on_them = todo_view(ws, "waiting-on-them").groups
        waiting_on_me = tuple(
            sorted((t for t in mine if not same(t.fields.get("requester"), me.id)), key=by_due)
        )
        directs = tuple(
            DirectCounts(
                d,
                _count(open_todos, owner=d.id, requester=me.id),
                _count(open_todos, owner=me.id, requester=d.id),
            )
            for d in directs_of(ws, me.id)
        )
    notes = sorted(
        (f for f in files if f.type is None and f.rel != BOOKMARKS), key=lambda f: -f.mtime
    )
    return Dashboard(
        due_soon=tuple(sorted(due_soon, key=by_due)),
        waiting_on_them=waiting_on_them,
        waiting_on_me=waiting_on_me,
        blocked=tuple(
            sorted((f for f in work if f.fields.get("status") == "blocked"), key=_by_title)
        ),
        directs=directs,
        recent_notes=tuple(notes[:RECENT_NOTES]),
        get_started=not any(f.type is not None and (me is None or f.rel != me.rel) for f in files),
    )


def _count(open_todos: list[CachedFile], owner: str, requester: str) -> int:
    return sum(
        1
        for t in open_todos
        if same(t.fields.get("owner"), owner) and same(t.fields.get("requester"), requester)
    )
