// @ts-check
// The People page (SPEC §11.3: org tree from Me, other Team Members, Stakeholders) and
// the Person View (§11.6: header, properties well, Tagged on, the two To-do columns,
// Notes with them and New 1:1, the body as outline blocks).

import { useEffect, useState } from "preact/hooks";
import { describe } from "./api.js";
import { Avatar } from "./avatar.js";
import { dueLabel, isLate, lateLabel, noteDay, shortDate } from "./dates.js";
import { BodySection, Properties, Title, Warnings, closeBody } from "./entity.js";
import { isFinished, typeLabel, useCandidates, writeField } from "./fields.js";
import { Icon } from "./icons.js";
import { Actions, ArchivedBar } from "./lifecycle.js";
import { openNew } from "./newform.js";
import { entityHref, fileHref, personHref } from "./router.js";
import { html, meId, resolveMention, sameId, tree, useView, viewVersion } from "./state.js";
import { QuickAdd, today, toggleTodo } from "./todos.js";

/**
 * @typedef {import("./fields.js").Summary} Summary
 * @typedef {import("./entity.js").Detail} Detail
 * @typedef {import("./todos.js").TodoGroup} TodoGroup
 * @typedef {{person: Summary, directs: OrgNode[]}} OrgNode
 * @typedef {{manager: Summary | null, me: OrgNode | null, others: Summary[],
 *   stakeholders: {person: Summary, tags: number}[],
 *   waiting: Record<string, {on_them: number, on_me: number}>}} People
 * @typedef {{
 *   person: Detail,
 *   manager: Summary | null,
 *   directs: Summary[],
 *   tagged_on: {item: Summary, roles: string[]}[],
 *   waiting_on_them: TodoGroup[],
 *   waiting_on_me: TodoGroup[],
 *   notes: Summary[],
 *   names: Record<string, string>,
 * }} PersonData
 */

/**
 * `#/people` (§11.3), per "People" in Paper: the org tree from Me as outline blocks (Me's
 * Manager above Me, Directs and their reports below, each collapsible), other Team
 * Members, and the Stakeholders table. Show archived brings archived Persons back (§8.3).
 */
export function PeoplePage() {
  const [showArchived, setShowArchived] = useState(false);
  const { data, error } = useView(
    /** @type {string} */ (`/api/views/people?include_archived=${showArchived}`),
  );
  const people = /** @type {People | null} */ (data);
  return html`
    <section class="page people-page">
      <header class="people-head">
        <p class="eyebrow">${people ? peopleEyebrow(people) : " "}</p>
        <div class="people-title">
          <h1 class="title">People</h1>
          <label class="toggle"><input type="checkbox" role="switch" checked=${showArchived}
            onChange=${(/** @type {Event} */ e) => setShowArchived(/** @type {HTMLInputElement} */ (e.currentTarget).checked)} />
            Show archived</label>
        </div>
      </header>
      ${error
        ? html`<p class="error-text" role="alert">${describe(error)}</p>`
        : people
          ? html`<${PeopleBody} people=${people} />`
          : html`<p class="hint">Loading…</p>`}
    </section>
  `;
}

/** @param {{people: People}} props */
function PeopleBody({ people }) {
  const [collapsed, setCollapsed] = useState(/** @type {Set<string>} */ (new Set()));
  /** @param {string} id */
  const toggle = (id) => {
    const next = new Set(collapsed);
    if (!next.delete(id)) next.add(id);
    setCollapsed(next);
  };
  return html`
    ${people.me
      ? html`<section class="org" aria-label="Org">
          ${people.manager &&
          html`<div class="block org-person manager">
              <div class="block-row">
                <span class="bullet"></span>
                <${OrgPerson} person=${people.manager} waiting=${people.waiting} />
                <span class="org-tag">Manager</span>
              </div>
            </div>
            <div class="org-stub" aria-hidden="true"></div>`}
          <${OrgBlock} node=${people.me} depth=${0} waiting=${people.waiting} collapsed=${collapsed} toggle=${toggle} />
        </section>`
      : html`<p class="people-note muted">Me isn't set, so there is no org tree: pick your Person in Settings.</p>`}
    ${(people.others.length > 0 || !people.me) &&
    html`<section class="block block-heading people-section" aria-label=${people.me ? "Other Team Members" : "Team Members"}>
      <div class="block-row">
        <span class="bullet"></span>
        <h2 class="block-text">${people.me ? "Other Team Members" : "Team Members"}</h2>
        ${people.me && html`<span class="group-note">not under Me</span>`}
        <button type="button" class="link-button add-person" onClick=${() => openNew("person", { kind: ["team-member"] })}>
          <${Icon} name="plus" /> Team Member</button>
      </div>
      <div class="block-children">
        ${people.others.length === 0 && html`<p class="block-empty">No Team Members yet</p>`}
        ${people.others.map(
          (p) => html`<div class="block org-person" key=${p.id}>
            <div class="block-row">
              <span class="bullet"></span>
              <${OrgPerson} person=${p} waiting=${people.waiting} reportsTo />
            </div>
          </div>`,
        )}
      </div>
    </section>`}
    <section class="block block-heading people-section" aria-label="Stakeholders">
      <div class="block-row">
        <span class="bullet"></span>
        <h2 class="block-text">Stakeholders</h2>
        <button type="button" class="link-button add-person" onClick=${() => openNew("person", { kind: ["stakeholder"] })}>
          <${Icon} name="plus" /> Stakeholder</button>
      </div>
      ${people.stakeholders.length
        ? html`<table class="data-table stakeholders-table">
            <thead><tr><th>Name</th><th class="col-org">Organisation</th><th class="col-role">Role</th><th class="tags">Tags</th></tr></thead>
            <tbody>
              ${people.stakeholders.map(
                (s) => html`<tr key=${s.person.id}>
                  <td>
                    <span class="stakeholder-name">
                      <${Avatar} person=${s.person} kind="stakeholder" />
                      <a href=${personHref(s.person.id)}>${s.person.title}</a>
                      ${s.person.fields.archived && html`<span class="status status-cancelled">archived</span>`}
                    </span>
                  </td>
                  <td class="col-org">${s.person.fields.organisation ?? ""}</td>
                  <td class="col-role">${s.person.fields.role ?? ""}</td>
                  <td class="tags ${s.tags ? "" : "none"}">${s.tags}</td>
                </tr>`,
              )}
            </tbody>
          </table>`
        : html`<p class="block-empty">No Stakeholders yet</p>`}
    </section>
  `;
}

/**
 * A Person in the org tree and their reports. Me is the root; anyone with reports can be
 * collapsed to a count of them.
 * @param {{node: OrgNode, depth: number, waiting: People["waiting"], collapsed: Set<string>,
 *   toggle: (id: string) => void}} props
 */
function OrgBlock({ node, depth, waiting, collapsed, toggle }) {
  const { person, directs } = node;
  const me = depth === 0;
  const open = me || !collapsed.has(person.id);
  const reports = directs.length;
  return html`
    <div class="block org-person depth-${Math.min(depth, 2)} ${me ? "me" : ""} ${open ? "" : "collapsed"}">
      <div class="block-row">
        ${reports > 0 && !me
          ? html`<button type="button" class="bullet" aria-expanded=${open}
              aria-label="${open ? "Collapse" : "Expand"} ${person.title}" onClick=${() => toggle(person.id)}></button>`
          : html`<span class="bullet"></span>`}
        <${OrgPerson} person=${person} waiting=${waiting} me=${me}
          reports=${open ? 0 : reports} />
      </div>
      ${reports > 0 &&
      open &&
      html`<div class="block-children">
        ${directs.map(
          (d) => html`<${OrgBlock} key=${d.person.id} node=${d} depth=${depth + 1} waiting=${waiting}
            collapsed=${collapsed} toggle=${toggle} />`,
        )}
      </div>`}
    </div>
  `;
}

/**
 * One Person's line: avatar, name, role (and "Me", or who they report to), then the open
 * To-dos between them and Me.
 * @param {{person: Summary, waiting: People["waiting"], me?: boolean, reports?: number,
 *   reportsTo?: boolean}} props
 */
function OrgPerson({ person, waiting, me = false, reports = 0, reportsTo = false }) {
  const { role, manager, archived } = person.fields;
  const managerName = reportsTo && typeof manager === "string" ? resolveMention(manager)?.title : undefined;
  const meta = [typeof role === "string" && role, me && "Me", managerName && `reports to ${managerName}`]
    .filter(Boolean)
    .join(" · ");
  const counts = waiting[person.id];
  return html`
    <${Avatar} person=${person} />
    <a class="org-name" href=${personHref(person.id)}>${person.title}</a>
    ${meta && html`<span class="org-meta">${meta}</span>`}
    ${archived && html`<span class="status status-cancelled">archived</span>`}
    ${reports > 0 && html`<span class="org-reports">· ${reports} ${reports === 1 ? "report" : "reports"}</span>`}
    ${counts &&
    html`<span class="org-counts">
      ${counts.on_them > 0 && `${counts.on_them} waiting on them`}${counts.on_them > 0 && counts.on_me > 0 && " · "}
      ${counts.on_me > 0 && html`<strong>${counts.on_me} on me</strong>`}
    </span>`}
  `;
}

/**
 * "10 Team Members · 3 Stakeholders": everyone above the Stakeholders table, and the table.
 * @param {People} people
 */
function peopleEyebrow(people) {
  /** @type {(n: OrgNode) => number} */
  const size = (n) => 1 + n.directs.reduce((sum, d) => sum + size(d), 0);
  const team = (people.manager ? 1 : 0) + (people.me ? size(people.me) : 0) + people.others.length;
  const stakeholders = people.stakeholders.length;
  return `${team} Team ${team === 1 ? "Member" : "Members"} · ${stakeholders} ${stakeholders === 1 ? "Stakeholder" : "Stakeholders"}`;
}

/** `#/people/<id>` (§11.6), per "Person — Alice Smith" in Paper. @param {{id: string}} props */
export function PersonPage({ id }) {
  const [showDone, setShowDone] = useState(false);
  const [editing, setEditing] = useState(false);
  const { data, error, reload } = useView(
    /** @type {string} */ (`/api/views/person/${encodeURIComponent(id)}?include_done=${showDone}`),
  );
  useEffect(() => setEditing(false), [id]);
  const view = /** @type {PersonData | null} */ (data);
  if (error) return html`<section class="entity"><p class="error-text" role="alert">${describe(error)}</p></section>`;
  if (!view || view.person.id.toLowerCase() !== id.toLowerCase()) return html`<p class="hint">Loading…</p>`;
  const person = view.person;
  const name = person.title;
  const first = name.split(/\s+/)[0] || name;
  const readOnly = person.read_only || (tree.value?.workspace.read_only ?? false);
  const open = (/** @type {TodoGroup[]} */ groups) =>
    groups.flatMap((g) => g.todos).filter((t) => !finished(t)).length;

  return html`
    <article class="entity person-view">
      <header class="entity-head person-head">
        <${Avatar} person=${person} size="large" />
        <div class="person-name">
          <p class="eyebrow">${personEyebrow(person)}</p>
          <${Title} detail=${person} readOnly=${readOnly} onSaved=${reload} />
        </div>
        <div class="entity-tools">
          <a class="tool" href=${fileHref(person.path)} title="Open the raw file"><${Icon} name="file-text" /> Open file</a>
          <${Actions} detail=${person} readOnly=${readOnly} />
        </div>
      </header>
      <${ArchivedBar} detail=${person} readOnly=${readOnly} onSaved=${reload} />
      <${Warnings} detail=${person} />
      <${Properties} detail=${person} readOnly=${readOnly} onSaved=${reload}>
        ${view.directs.length > 0 &&
        html`<div class="prop">
          <span class="prop-key">directs</span>
          <span class="prop-value directs">
            ${view.directs.map((d, i) => html`${i > 0 && ", "}<a key=${d.id} href=${personHref(d.id)}>${d.title}</a>`)}
          </span>
        </div>`}
      <//>

      <div class="person-columns">
        <${Column} title="Tagged on" count=${view.tagged_on.length}>
          ${view.tagged_on.length === 0 && html`<p class="section-empty">Not Tagged on anything yet</p>`}
          ${view.tagged_on.map((t) => html`<${TaggedRow} key=${t.item.id} tagged=${t} />`)}
          ${!readOnly && html`<${TagPicker} person=${person.id} name=${name} />`}
        <//>
        <${Column} title="Waiting on ${name}" count=${open(view.waiting_on_them)}>
          <${PersonTodos} groups=${view.waiting_on_them} names=${view.names} hide="owner"
            empty="Nothing waiting on ${name}" />
          ${!readOnly &&
          html`<${QuickAdd} boxed label="Add a To-do waiting on ${name}" defaults=${{ owner: person.id }}
            placeholder="Add for ${first}…" />`}
        <//>
        <${Column} title="${name} is waiting on me" count=${open(view.waiting_on_me)}>
          <${PersonTodos} groups=${view.waiting_on_me} names=${view.names} hide="requester"
            empty="${name} isn't waiting on anything" />
          ${!readOnly &&
          html`<${QuickAdd} boxed label="Add a To-do ${name} is waiting on" defaults=${{ requester: person.id }}
            placeholder="Promise ${first}…" />`}
        <//>
      </div>
      <div class="person-done">
        <button type="button" class="link-button" aria-pressed=${showDone} onClick=${() => setShowDone(!showDone)}>
          ${showDone ? "Hide" : "Show"} completed</button>
      </div>

      <${PersonNotes} person=${person} notes=${view.notes} readOnly=${readOnly} />

      <div class="person-body">
        ${!readOnly &&
        html`<div class="person-body-tools">
          <button type="button" class="link-button" aria-pressed=${editing} onClick=${() => {
            if (editing) closeBody(person.id);
            setEditing(!editing);
          }}>
            <${Icon} name="pencil" /> ${editing ? "Done" : "Edit body"}</button>
        </div>`}
        <${BodySection} detail=${person} readOnly=${readOnly} editing=${editing} />
      </div>
    </article>
  `;
}

/**
 * The line over a Person's name: "Person", their kinds, and "Direct" when Me is their Manager.
 * @param {Detail} person
 */
function personEyebrow(person) {
  const kinds = Array.isArray(person.fields.kind) ? person.fields.kind : [person.fields.kind];
  const parts = ["Person"];
  if (kinds.includes("team-member")) parts.push("Team Member");
  if (kinds.includes("stakeholder")) parts.push("Stakeholder");
  const me = meId();
  if (me && !sameId(me, person.id) && sameId(person.fields.manager, me)) parts.push("Direct");
  return parts.join(" · ");
}

/** @param {Summary} item */
function finished(item) {
  return isFinished(item.fields.status);
}

/**
 * One of the three columns: a heading with a count over a dark rule.
 * @param {{title: string, count: number, children?: any}} props
 */
function Column({ title, count, children }) {
  return html`
    <section class="person-column" aria-label=${title}>
      <h2 class="column-header"><span class="column-title">${title}</span><span class="count">${count}</span></h2>
      ${children}
    </section>
  `;
}

/**
 * A work item they're Tagged on: its title, type and status (or lateness), and the role.
 * @param {{tagged: {item: Summary, roles: string[]}}} props
 */
function TaggedRow({ tagged }) {
  const { item, roles } = tagged;
  const { status, due } = item.fields;
  const now = today();
  const late = !finished(item) && isLate(due, now);
  const state =
    status === "blocked"
      ? html`<span class="alarm">blocked</span>`
      : late
        ? html`<span class="alarm">${lateLabel(due, now)}</span>`
        : typeof status === "string" && status.replace(/-/g, " ");
  return html`
    <div class="person-row">
      <div class="person-row-text">
        <a href=${entityHref(item.id, item.type)}>${item.title}</a>
        <span class="person-row-meta">${typeLabel(item.type)}${state && html` · ${state}`}</span>
      </div>
      <span class="person-role ${roles.includes("Lead") ? "lead" : ""}">${roles.join(", ")}</span>
    </div>
  `;
}

/**
 * A To-do column's rows, open and (with Show completed) finished, ticked in place.
 * @param {{groups: TodoGroup[], names: Record<string, string>, hide: "owner" | "requester", empty: string}} props
 */
function PersonTodos({ groups, names, hide, empty }) {
  const todos = groups.flatMap((g) => g.todos);
  if (!todos.length) return html`<p class="section-empty">${empty}</p>`;
  return html`${todos.map((t) => html`<${PersonTodo} key=${t.id} todo=${t} names=${names} hide=${hide} />`)}`;
}

/** @param {{todo: Summary, names: Record<string, string>, hide: "owner" | "requester"}} props */
function PersonTodo({ todo, names, hide }) {
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const { owner, requester, status, due, completed, source } = todo.fields;
  const done = finished(todo);
  const now = today();
  const me = meId();
  const name = (/** @type {string} */ id) => names[id] ?? resolveMention(id)?.title ?? id;
  const late = !done && isLate(due, now);
  /** @type {any[]} */
  const meta = [];
  if (done) {
    const day = typeof completed === "string" ? (completed === now ? "today" : shortDate(completed)) : "";
    meta.push(status === "cancelled" ? "cancelled" : `done ${day}`.trim());
  } else if (typeof due === "string") {
    meta.push(late ? html`<span class="alarm">${lateLabel(due, now)}</span>` : `due ${dueLabel(due, now)}`);
  }
  if (hide !== "owner" && typeof owner === "string" && !sameId(owner, me)) {
    meta.push(html`→ <a href=${personHref(owner)}>${name(owner)}</a>`);
  }
  if (hide !== "requester" && typeof requester === "string" && !sameId(requester, me)) {
    meta.push(html`for <a href=${personHref(requester)}>${name(requester)}</a>`);
  }
  if (typeof source === "string") meta.push(html`from <a href=${entityHref(source)}>${name(source)}</a>`);
  return html`
    <div class="person-row person-todo ${done ? "finished" : ""}">
      <input type="checkbox" class="checkbox" checked=${done} aria-label="Done: ${todo.title}"
        onChange=${async () => setError(await toggleTodo(todo))} />
      <div class="person-row-text">
        <a class="todo-title" href=${entityHref(todo.id)}>${todo.title}</a>
        ${meta.length > 0 && html`<span class="person-row-meta">${meta.map((m, i) => html`${i > 0 && " · "}${m}`)}</span>`}
        ${todo.warnings.length > 0 && html`<span class="broken" title=${todo.warnings.map((w) => w.message).join("; ")}>!</span>`}
        ${error && html`<span class="field-error">${error}</span>`}
      </div>
    </div>
  `;
}

const RECENT_NOTES = 5;

/**
 * Notes with them, newest first: day, title, the other Participants and Labels; the
 * older ones behind "Show N older". New 1:1 sits on the header.
 * @param {{person: Detail, notes: Summary[], readOnly: boolean}} props
 */
function PersonNotes({ person, notes, readOnly }) {
  const [all, setAll] = useState(false);
  const me = meId();
  const now = today();
  const name = person.title;
  const shown = all ? notes : notes.slice(0, RECENT_NOTES);
  const older = notes.length - RECENT_NOTES;
  return html`
    <section class="person-notes" aria-label="Notes with ${name}">
      <h2 class="column-header">
        <span>Notes with ${name}</span><span class="count column-title">${notes.length}</span>
        <button type="button" class="primary new-one-on-one" disabled=${readOnly}
          onClick=${() => openNew("note", { people: me && !sameId(me, person.id) ? [me, person.id] : [person.id] }, "one-on-one")}>
          <${Icon} name="plus" /> New 1:1
        </button>
      </h2>
      ${notes.length === 0 && html`<p class="section-empty">No Notes with ${name} yet</p>`}
      ${shown.map((n) => {
        const day = [n.fields.date, n.fields.created].find((d) => typeof d === "string" && ISO_DAY.test(d));
        const others = (Array.isArray(n.fields.people) ? n.fields.people : []).filter(
          (/** @type {unknown} */ p) => typeof p === "string" && !sameId(p, person.id) && !sameId(p, me),
        );
        const names = others.slice(0, 2).map((/** @type {string} */ p) => resolveMention(p)?.title ?? p);
        const labels = Array.isArray(n.fields.labels) ? n.fields.labels : [];
        return html`<div class="person-note" key=${n.id}>
          <span class="note-day">${day ? noteDay(day, now) : ""}</span>
          <a href=${entityHref(n.id, n.type)}>${n.title}</a>
          <span class="note-with">${names.length > 0 &&
          `with ${names.join(", ")}${others.length > 2 ? ` +${others.length - 2}` : ""}`}</span>
          <span class="note-labels">${labels.map((/** @type {string} */ l) => `#${l}`).join(" ")}</span>
        </div>`;
      })}
      ${older > 0 &&
      html`<button type="button" class="link-button show-older" aria-expanded=${all} onClick=${() => setAll(!all)}>
        ${all ? "Show fewer" : html`Show ${older} older <${Icon} name="chevron-down" />`}</button>`}
    </section>
  `;
}

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;

const TAG_ROLES = [
  { field: "team", label: "Team" },
  { field: "stakeholders", label: "Stakeholder" },
];

/**
 * "Tag <name> to…": pick a work item and a role; writes the Tag on that item (§11.7).
 * Offers the items they don't already have that role on.
 * @param {{person: string, name: string}} props
 */
function TagPicker({ person, name }) {
  const candidates = useCandidates();
  const [item, setItem] = useState("");
  const [role, setRole] = useState("team");
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const has = (/** @type {Summary} */ c) =>
    Array.isArray(c.fields[role]) && c.fields[role].some((/** @type {unknown} */ v) => sameId(v, person));
  const options = candidates.filter(
    (c) => ["theme", "project", "deliverable"].includes(c.type) && !c.fields.archived && !has(c),
  );

  /** @param {Event} e */
  async function tag(e) {
    e.preventDefault();
    const target = options.find((c) => c.id === item);
    if (!target) return;
    const current = Array.isArray(target.fields[role]) ? target.fields[role] : [];
    const failed = await writeField(target, role, [...current, person]);
    if (!failed) setItem("");
    setError(failed);
    viewVersion.value += 1;
  }

  return html`
    <form class="tag-picker" onSubmit=${tag}>
      <select aria-label="Tag ${name} to…" value=${item}
        onChange=${(/** @type {Event} */ e) => setItem(/** @type {HTMLSelectElement} */ (e.currentTarget).value)}>
        <option value="">Tag ${name} to…</option>
        ${options.map((c) => html`<option value=${c.id}>${c.title} (${typeLabel(c.type)})</option>`)}
      </select>
      <select aria-label="Role" value=${role}
        onChange=${(/** @type {Event} */ e) => setRole(/** @type {HTMLSelectElement} */ (e.currentTarget).value)}>
        ${TAG_ROLES.map((r) => html`<option value=${r.field}>${r.label}</option>`)}
      </select>
      <button type="submit" disabled=${!item}>Tag</button>
      ${error && html`<span class="field-error">${error}</span>`}
    </form>
  `;
}
