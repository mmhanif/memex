// @ts-check
// The Dashboard (SPEC §11.4): today's date over outline blocks. Blocks that need Me show
// a dashed "Paused until Me is set" note while Me isn't set (§3.5).

import { useState } from "preact/hooks";
import { describe } from "./api.js";
import { daysLate, dueLabel, longDate, noteDay, shortDate } from "./dates.js";
import { typeLabel } from "./fields.js";
import { Icon } from "./icons.js";
import { openNew } from "./newform.js";
import { entityHref, personHref } from "./router.js";
import { html, meId, sameId, useView } from "./state.js";
import { PersonRef, isOverdue, today, toggleTodo } from "./todos.js";

/**
 * @typedef {import("./fields.js").Summary} Summary
 * @typedef {import("./todos.js").TodoGroup} TodoGroup
 * @typedef {{
 *   due_soon: Summary[],
 *   waiting_on_them: TodoGroup[] | null,
 *   waiting_on_me: Summary[] | null,
 *   blocked: Summary[],
 *   directs: {person: Summary, waiting_on_them: number, waiting_on_me: number}[] | null,
 *   recent_notes: Summary[],
 *   capture_notes: Summary[],
 *   to_create: Record<string, number>,
 *   get_started: boolean,
 *   names: Record<string, string>,
 * }} DashboardData
 * @typedef {Record<string, string>} Names
 */

const PAUSED = "Paused until Me is set.";

export function Dashboard() {
  const { data, error } = useView("/api/views/dashboard");
  const d = /** @type {DashboardData | null} */ (data);
  if (error) return html`<section class="page"><p class="error-text" role="alert">${describe(error)}</p></section>`;
  if (!d) return html`<p class="hint">Loading…</p>`;
  const now = today();
  const meSet = d.waiting_on_me !== null;
  return html`
    <section class="page home dashboard">
      <header class="home-head">
        <p class="eyebrow">${summaryLine(d.due_soon, now)}</p>
        <h1 class="title">${longDate(now)}</h1>
      </header>
      ${d.get_started && html`<${GetStarted} />`}
      ${d.capture_notes.length > 0 && html`<${CaptureReminder} notes=${d.capture_notes} />`}

      <${Block} title="Due within 7 days">
        ${d.due_soon.map((f) => html`<${DueRow} key=${f.id} item=${f} names=${d.names} now=${now} />`)}
        ${!meSet && html`<${Paused}>Paused until Me is set: To-dos Me owns aren't listed.<//>`}
        ${meSet && !d.due_soon.length && html`<p class="muted block-empty">Nothing due</p>`}
      <//>

      <${Block} title="Waiting on them" href="#/todos/waiting-on-them">
        ${d.waiting_on_them === null
          ? html`<${Paused}>${PAUSED}<//>`
          : d.waiting_on_them.length
            ? d.waiting_on_them.map((g) => html`<${PersonGroup} key=${g.label} group=${g} names=${d.names} />`)
            : html`<p class="muted block-empty">Nobody owes you anything</p>`}
      <//>

      <${Block} title="Waiting on me" href="#/todos/waiting-on-me">
        ${d.waiting_on_me === null
          ? html`<${Paused}>${PAUSED}<//>`
          : d.waiting_on_me.length
            ? d.waiting_on_me.map((t) => html`<${TodoBlock} key=${t.id} todo=${t} names=${d.names} party="requester" />`)
            : html`<p class="muted block-empty">Nobody is waiting on you</p>`}
      <//>

      <${Block} title="Blocked work" href="#/portfolio/board">
        ${d.blocked.length
          ? d.blocked.map((f) => html`<div class="block-row" key=${f.id}>
              <span class="bullet"></span>
              <span class="when late blocked-tag">Blocked</span>
              <span class="block-text"><${WorkText} item=${f} names=${d.names} lead /></span>
            </div>`)
          : html`<p class="muted block-empty">Nothing blocked</p>`}
      <//>

      <${Block} title="Directs" href="#/people" flat>
        ${d.directs === null
          ? html`<${Paused}>Paused until Me is set: Directs are Persons whose manager is Me.<//>`
          : d.directs.length
            ? html`<${DirectsTable} directs=${d.directs} />`
            : html`<p class="muted block-empty">No Directs yet</p>`}
      <//>

      <${Block} title="Recent notes" flat>
        ${d.recent_notes.length
          ? d.recent_notes.map((n) => html`<${NoteRow} key=${n.id} note=${n} names=${d.names}
              toCreate=${d.to_create[n.id] ?? 0} now=${now} />`)
          : html`<p class="muted block-empty">No Notes yet</p>`}
      <//>
    </section>
  `;
}

/**
 * "Today · 2 overdue · 2 due this week": the Due block in one line.
 * @param {Summary[]} due
 * @param {string} now
 */
function summaryLine(due, now) {
  const overdue = due.filter((f) => typeof f.fields.due === "string" && daysLate(f.fields.due, now) > 0).length;
  const parts = ["Today"];
  if (overdue) parts.push(`${overdue} overdue`);
  if (due.length - overdue) parts.push(`${due.length - overdue} due this week`);
  return parts.join(" · ");
}

/**
 * A heading block with its children hanging off the guide (or, `flat`, just indented).
 * @param {{title: string, href?: string, flat?: boolean, children?: any}} props
 */
function Block({ title, href, flat, children }) {
  return html`
    <section class="block block-heading home-block" aria-label=${title}>
      <div class="block-row">
        <span class="bullet"></span>
        <h2 class="block-text">${href ? html`<a href=${href}>${title}</a>` : title}</h2>
      </div>
      <div class=${flat ? "home-flat" : "block-children"}>${children}</div>
    </section>
  `;
}

/** The dashed note a Me-dependent block shows while Me isn't set (§3.5). @param {{children?: any}} props */
function Paused({ children }) {
  return html`<p class="paused">${children}</p>`;
}

/**
 * One row of the Due block: the lateness or date, then the To-do or the work item.
 * @param {{item: Summary, names: Names, now: string}} props
 */
function DueRow({ item, names, now }) {
  const due = /** @type {string} */ (item.fields.due ?? "");
  const late = due !== "" && daysLate(due, now) > 0;
  const when = html`<span class="when ${late ? "late" : ""}">${due && dueLabel(due, now)}</span>`;
  if (item.type === "todo") return html`<${TodoBlock} todo=${item} names=${names} party="requester" word="for" when=${when} />`;
  return html`
    <div class="block-row">
      <span class="bullet"></span>
      ${when}
      <span class="block-text"><${WorkText} item=${item} names=${names} status /></span>
    </div>
  `;
}

/**
 * "Cutover Runbook · Deliverable of Data Migration · active · lead @alice-smith".
 * @param {{item: Summary, names: Names, status?: boolean, lead?: boolean}} props
 */
function WorkText({ item, names, status, lead }) {
  const parent = item.type === "deliverable" ? item.fields.project : null;
  const leader = lead ? item.fields.lead : null;
  return html`
    <a href=${entityHref(item.id)}>${item.title}</a>
    <span class="muted"> · ${typeLabel(item.type)}${parent ? " of " : ""}</span>
    ${parent && html`<a href=${entityHref(parent)}>${names[parent] ?? parent}</a>`}
    ${status && item.fields.status && html`<span class="muted"> · ${item.fields.status}</span>`}
    ${leader && html`<span class="muted"> · lead </span><${PersonRef} id=${leader} names=${names} />`}
  `;
}

/**
 * A To-do as an outline row: tick box, title, the other party ("from @ben") and due.
 * @param {{todo: Summary, names: Names, party?: "owner" | "requester", word?: string, when?: any}} props
 */
function TodoBlock({ todo, names, party, word = "from", when }) {
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const other = party ? todo.fields[party] : null;
  const { due } = todo.fields;
  return html`
    <div class="block-row todo-block">
      <span class="bullet"></span>
      ${when}
      <span class="check-slot">
        <input type="checkbox" class="checkbox" aria-label="Done: ${todo.title}"
          onChange=${async () => setError(await toggleTodo(todo))} />
      </span>
      <span class="block-text">
        <a class="todo-title" href=${entityHref(todo.id)}>${todo.title}</a>
        ${other && !sameId(other, meId()) && html` <span class="muted">${word}</span> <${PersonRef} id=${other} names=${names} />`}
        ${!when && due && html` <span class="due ${isOverdue(due) ? "overdue" : ""}">due ${shortDate(due)}</span>`}
        ${todo.warnings.length > 0 && html` <span class="broken" title=${todo.warnings.map((w) => w.message).join("; ")}>!</span>`}
        ${error && html`<span class="field-error">${error}</span>`}
      </span>
    </div>
  `;
}

/** A Person (or "No owner") with the To-dos waiting on them. @param {{group: TodoGroup, names: Names}} props */
function PersonGroup({ group, names }) {
  return html`
    <div class="block">
      <div class="block-row">
        <span class="bullet"></span>
        <span class="block-text group-name">
          ${group.person ? html`<a href=${personHref(group.person)}>${group.label}</a>` : group.label}
        </span>
      </div>
      <div class="block-children">
        ${group.todos.map((t) => html`<${TodoBlock} key=${t.id} todo=${t} names=${names} />`)}
      </div>
    </div>
  `;
}

/** @param {{directs: NonNullable<DashboardData["directs"]>}} props */
function DirectsTable({ directs }) {
  return html`
    <table class="data-table directs-table">
      <thead><tr>
        <th scope="col">Person</th>
        <th scope="col" class="num" title="Open To-dos waiting on them">Waiting on them</th>
        <th scope="col" class="num" title="Open To-dos they're waiting on from Me">Waiting on me</th>
      </tr></thead>
      <tbody>
        ${directs.map(
          (c) => html`<tr key=${c.person.id}>
            <td><a href=${personHref(c.person.id)}>${c.person.title}</a>${c.person.fields.role &&
              html`<span class="muted role"> · ${c.person.fields.role}</span>`}</td>
            <td class="num">${c.waiting_on_them}</td>
            <td class="num">${c.waiting_on_me}</td>
          </tr>`,
        )}
      </tbody>
    </table>
  `;
}

/**
 * A recent Note: its day, title, then "N To-dos to create" (§6.4) or its labels and about.
 * @param {{note: Summary, names: Names, toCreate: number, now: string}} props
 */
function NoteRow({ note, names, toCreate, now }) {
  const day = note.fields.date ?? note.fields.created;
  const labels = /** @type {string[]} */ (note.fields.labels ?? []);
  const about = /** @type {string[]} */ ([note.fields.about ?? []].flat());
  return html`
    <div class="note-row">
      <span class="note-day">${typeof day === "string" && noteDay(day, now)}</span>
      <a href=${entityHref(note.id)}>${note.title}</a>
      ${toCreate > 0 && html`<span class="to-create">${toCreate} To-do${toCreate === 1 ? "" : "s"} to create</span>`}
      ${labels.length > 0 && html`<span class="muted">${labels.map((l) => `#${l}`).join(" ")}</span>`}
      ${about.length > 0 &&
      html`<span class="muted">about ${about.map((a, i) => html`${i ? ", " : ""}<a href=${entityHref(a)}>${names[a] ?? a}</a>`)}</span>`}
    </div>
  `;
}

/**
 * A quiet line: "N Notes have To-dos to create", linking to them (§6.4).
 * @param {{notes: Summary[]}} props
 */
function CaptureReminder({ notes }) {
  const n = notes.length;
  return html`
    <p class="muted capture-reminder">
      ${n} Note${n === 1 ? " has" : "s have"} To-dos to create:
      ${notes.map((note, i) => html`${i ? ", " : " "}<a href=${entityHref(note.id)}>${note.title}</a>`)}
    </p>
  `;
}

/** Shown on an empty Workspace until any Entity besides Me exists (§3.4). */
function GetStarted() {
  return html`
    <section class="card get-started">
      <h2>Get started</h2>
      <p>Your Workspace is empty. Add the people you work with and the work you track:</p>
      <p class="actions">
        ${["person", "theme", "project"].map(
          (t) => html`<button type="button" onClick=${() => openNew(t)}><${Icon} name="plus" /> ${typeLabel(t)}</button>`,
        )}
      </p>
    </section>
  `;
}
