"""Read-only views over the parse cache: To-dos, Dashboard, People, Person View,
Portfolio (SPEC §6.2, §11.3, §11.4, §11.6).

Views read leniently (§4.5): a To-do with a bad `status` counts as open and a bad
`due` as undated. Ids compare ignoring case (§4.1).
"""

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, cast

from memex.core.cache import CachedFile
from memex.core.entities import find, refers
from memex.core.errors import NotFound, Validation
from memex.core.schema import FINISHED_TODO, WORK_STATUSES, EntityType, parse_date
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
        picked = [t for t in todos(ws) if refers(t, ["owner"], me)]
        return TodoView("mine", _by_due(ws, picked, include_done))
    if view == "waiting-on-them":
        picked = [
            t for t in todos(ws) if refers(t, ["requester"], me) and not refers(t, ["owner"], me)
        ]
        return TodoView("waiting-on-them", _by_party(ws, picked, "owner", include_done))
    picked = [t for t in todos(ws) if refers(t, ["owner"], me) and not refers(t, ["requester"], me)]
    return TodoView("waiting-on-me", _by_party(ws, picked, "requester", include_done))


def todos(ws: Workspace) -> list[CachedFile]:
    return [f for f in ws.cache.files() if f.type is EntityType.TODO]


def is_open(todo: CachedFile) -> bool:
    return todo.fields.get("status") not in FINISHED_TODO


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
    """Group by the Person in `field`. Ids written in different case are one group (§4.1)."""
    by_person: dict[str, list[CachedFile]] = {}
    for t in filter(is_open, picked):
        by_person.setdefault(str(t.fields.get(field) or "").casefold(), []).append(t)
    groups = []
    for ts in by_person.values():
        written = str(ts[0].fields.get(field) or "")
        found = ws.cache.resolve(written).file if written else None
        person = found.id if found else written
        label = found.title if found else (written or "(no one)")
        groups.append(TodoGroup(label, tuple(sorted(ts, key=by_due)), person or None))
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
    owned = [t for t in todos(ws) if refers(t, ["owner"], pid)]
    requested = [
        t for t in todos(ws) if refers(t, ["requester"], pid) and not refers(t, ["owner"], pid)
    ]
    return PersonView(
        person=person,
        manager=_manager_of(ws, person),
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


def _manager_of(ws: Workspace, person: CachedFile) -> CachedFile | None:
    manager = person.fields.get("manager")
    return ws.cache.resolve(manager).file if isinstance(manager, str) else None


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
            and refers(f, ["manager"], id)
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
    directs: tuple[OrgNode, ...]  # their Directs, each with theirs


@dataclass(frozen=True)
class Stakeholder:
    file: CachedFile
    tags: int  # work items they're Tagged on (team or stakeholders; Lead isn't a Tag)


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
        manager = _manager_of(ws, me)
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
            Stakeholder(p, sum(1 for t in tagged_on(ws, p.id) if t.roles != ("Lead",)))
            for p in persons
            if _kind(p, "stakeholder")
        ),
    )


def _org_tree(ws: Workspace, person: CachedFile, shown: set[str]) -> OrgNode:
    shown.add(person.id.casefold())
    directs = [d for d in directs_of(ws, person.id) if d.id.casefold() not in shown]
    shown.update(d.id.casefold() for d in directs)
    return OrgNode(person, tuple(_org_tree(ws, d, shown) for d in directs))


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
        mine = [t for t in open_todos if refers(t, ["owner"], me.id)]
        due_soon += [t for t in mine if soon(t)]
        waiting_on_them = todo_view(ws, "waiting-on-them").groups
        waiting_on_me = tuple(
            sorted((t for t in mine if not refers(t, ["requester"], me.id)), key=by_due)
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
        1 for t in open_todos if refers(t, ["owner"], owner) and refers(t, ["requester"], requester)
    )


# Portfolio (§11.3)

BOARD_STATUSES = tuple(s for s in WORK_STATUSES if s != "cancelled")
BoardKind = Literal["project", "deliverable"]
BOARD_KINDS: dict[str, EntityType] = {
    "project": EntityType.PROJECT,
    "deliverable": EntityType.DELIVERABLE,
}


@dataclass(frozen=True)
class BoardColumn:
    status: str | None  # None: items whose status is missing or not a valid value
    items: tuple[CachedFile, ...]


@dataclass(frozen=True)
class Board:
    kind: BoardKind
    columns: tuple[BoardColumn, ...]
    chips: tuple[CachedFile, ...]  # the Theme filter chips


def portfolio_board(
    ws: Workspace,
    kind: str = "project",
    themes: Iterable[str] = (),
    include_archived: bool = False,
) -> Board:
    """Projects or Deliverables in status columns, soonest due first. Cancelled isn't a
    column. Items with a bad status get a flagged column of their own, first (§4.5)."""
    if kind not in BOARD_KINDS:
        raise Validation(f"Unknown board kind {kind!r}: one of {', '.join(BOARD_KINDS)}")
    items = _under_themes(ws, BOARD_KINDS[kind], themes)
    by_status: dict[str | None, list[CachedFile]] = {s: [] for s in BOARD_STATUSES}
    invalid: list[CachedFile] = []
    for f in items:
        status = f.fields.get("status")
        if status in WORK_STATUSES:
            by_status.get(status, []).append(f)  # cancelled ones fall away here
        else:
            invalid.append(f)
    columns = [BoardColumn(s, tuple(sorted(fs, key=by_due))) for s, fs in by_status.items()]
    if invalid:
        columns.insert(0, BoardColumn(None, tuple(sorted(invalid, key=by_due))))
    return Board(cast(BoardKind, kind), tuple(columns), theme_chips(ws, include_archived))


def theme_chips(ws: Workspace, include_archived: bool = False) -> tuple[CachedFile, ...]:
    """Themes by name; archived ones only when asked (§8.3)."""
    return tuple(
        sorted(
            (
                f
                for f in ws.cache.files()
                if f.type is EntityType.THEME and (include_archived or not f.fields.get("archived"))
            ),
            key=_by_title,
        )
    )


def _under_themes(ws: Workspace, kind: EntityType, themes: Iterable[str]) -> list[CachedFile]:
    """Every item of `kind`, or with `themes`, those whose Theme is one of them."""
    items = [f for f in ws.cache.files() if f.type is kind]
    wanted = {t.casefold() for t in themes}
    if not wanted:
        return items
    return [f for f in items if (t := theme_of(ws, f)) is not None and t.id.casefold() in wanted]


def theme_of(ws: Workspace, f: CachedFile) -> CachedFile | None:
    """A Project's Theme, or a Deliverable's Project's Theme, if it resolves."""
    if f.type is EntityType.DELIVERABLE:
        project = _resolved(ws, f.fields.get("project"), EntityType.PROJECT)
        return theme_of(ws, project) if project else None
    return _resolved(ws, f.fields.get("theme"), EntityType.THEME)


def _resolved(ws: Workspace, ref: object, kind: EntityType) -> CachedFile | None:
    found = ws.cache.resolve(ref).file if isinstance(ref, str) and ref else None
    return found if found is not None and found.type is kind else None


@dataclass(frozen=True)
class OutlineProject:
    project: CachedFile
    deliverables: tuple[CachedFile, ...]


@dataclass(frozen=True)
class OutlineTheme:
    theme: CachedFile | None  # None: "No theme"
    projects: tuple[OutlineProject, ...]


@dataclass(frozen=True)
class Outline:
    themes: tuple[OutlineTheme, ...]
    orphans: tuple[CachedFile, ...]  # Deliverables whose Project doesn't resolve
    chips: tuple[CachedFile, ...]


def portfolio_outline(
    ws: Workspace, themes: Iterable[str] = (), include_archived: bool = False
) -> Outline:
    """Theme → Project → Deliverable, each level by title so rows stay put while edited.

    Archived Themes come after the others; they're only left out of the chips (§8.3).
    Projects whose Theme doesn't resolve go under "No theme", last. With `themes`, only
    those Themes' groups are shown.
    """
    wanted = {t.casefold() for t in themes}
    files = ws.cache.files()
    deliverables: dict[str, list[CachedFile]] = {}
    orphans: list[CachedFile] = []
    for d in (f for f in files if f.type is EntityType.DELIVERABLE):
        project = _resolved(ws, d.fields.get("project"), EntityType.PROJECT)
        if project is None:
            orphans.append(d)
        else:
            deliverables.setdefault(project.rel, []).append(d)
    projects: dict[str | None, list[OutlineProject]] = {}
    for p in sorted((f for f in files if f.type is EntityType.PROJECT), key=_by_title):
        theme = theme_of(ws, p)
        kids = tuple(sorted(deliverables.get(p.rel, ()), key=_by_title))
        projects.setdefault(theme.rel if theme else None, []).append(OutlineProject(p, kids))
    all_themes = sorted(
        (f for f in files if f.type is EntityType.THEME),
        key=lambda t: (bool(t.fields.get("archived")), *_by_title(t)),
    )
    groups = [
        OutlineTheme(t, tuple(projects.get(t.rel, ())))
        for t in all_themes
        if not wanted or t.id.casefold() in wanted
    ]
    if not wanted and projects.get(None):
        groups.append(OutlineTheme(None, tuple(projects[None])))
    return Outline(
        tuple(groups),
        () if wanted else tuple(sorted(orphans, key=_by_title)),
        theme_chips(ws, include_archived),
    )
