// @ts-check
// The Dashboard (SPEC §11.4). Cards that need Me say so while Me isn't set (§3.5).

import { describe } from "./api.js";
import { typeLabel } from "./fields.js";
import { Icon } from "./icons.js";
import { openNew } from "./newform.js";
import { entityHref, personHref } from "./router.js";
import { html, useView } from "./state.js";
import { TodoGroups, TodoRow, isOverdue } from "./todos.js";

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
 *   get_started: boolean,
 *   names: Record<string, string>,
 * }} DashboardData
 */

const NO_ME = "Me isn't set: pick or create your Person in Settings.";

export function Dashboard() {
  const { data, error } = useView("/api/views/dashboard");
  const d = /** @type {DashboardData | null} */ (data);
  if (error) return html`<section class="page"><p class="error-text" role="alert">${describe(error)}</p></section>`;
  if (!d) return html`<p class="hint">Loading…</p>`;
  return html`
    <section class="page dashboard">
      <header class="page-head"><h1>Home</h1></header>
      ${d.get_started && html`<${GetStarted} />`}
      ${d.capture_notes.length > 0 && html`<${CaptureReminder} notes=${d.capture_notes} />`}
      <div class="cards">
        <${Card} title="Due within 7 days">
          ${d.due_soon.length
            ? html`<ul class="todo-list">
                ${d.due_soon.map((f) =>
                  f.type === "todo"
                    ? html`<${TodoRow} key=${f.id} todo=${f} names=${d.names} />`
                    : html`<${WorkRow} key=${f.id} item=${f} />`,
                )}
              </ul>`
            : html`<p class="muted">Nothing due</p>`}
        <//>
        <${Card} title="Waiting on them" href="#/todos/waiting-on-them">
          ${d.waiting_on_them === null
            ? html`<p class="muted">${NO_ME}</p>`
            : html`<${TodoGroups} list=${{ groups: d.waiting_on_them, names: d.names }} hide="owner"
                empty="Nobody owes you anything" />`}
        <//>
        <${Card} title="Waiting on me" href="#/todos/waiting-on-me">
          ${d.waiting_on_me === null
            ? html`<p class="muted">${NO_ME}</p>`
            : d.waiting_on_me.length
              ? html`<ul class="todo-list">
                  ${d.waiting_on_me.map((t) => html`<${TodoRow} key=${t.id} todo=${t} names=${d.names} />`)}
                </ul>`
              : html`<p class="muted">Nobody is waiting on you</p>`}
        <//>
        <${Card} title="Blocked work" href="#/portfolio/board">
          ${d.blocked.length
            ? html`<ul class="todo-list">${d.blocked.map((f) => html`<${WorkRow} key=${f.id} item=${f} />`)}</ul>`
            : html`<p class="muted">Nothing blocked</p>`}
        <//>
        <${Card} title="Directs" href="#/people">
          ${d.directs === null
            ? html`<p class="muted">${NO_ME}</p>`
            : d.directs.length
              ? html`<table class="table directs-table">
                  <thead><tr><th>Name</th><th title="Open To-dos waiting on them">Owes me</th>
                    <th title="Open To-dos they're waiting on from me">I owe</th></tr></thead>
                  <tbody>
                    ${d.directs.map(
                      (c) => html`<tr key=${c.person.id}>
                        <td><a href=${personHref(c.person.id)}>${c.person.title}</a></td>
                        <td>${c.waiting_on_them}</td>
                        <td>${c.waiting_on_me}</td>
                      </tr>`,
                    )}
                  </tbody>
                </table>`
              : html`<p class="muted">No Directs yet</p>`}
        <//>
        <${Card} title="Recent Notes">
          ${d.recent_notes.length
            ? html`<ul class="todo-list">
                ${d.recent_notes.map((n) => html`<li key=${n.id}><a href=${entityHref(n.id)}>${n.title}</a></li>`)}
              </ul>`
            : html`<p class="muted">No Notes yet</p>`}
        <//>
      </div>
    </section>
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

/** @param {{title: string, href?: string, children?: any}} props */
function Card({ title, href, children }) {
  return html`
    <section class="card" aria-label=${title}>
      <h2>${href ? html`<a href=${href}>${title}</a>` : title}</h2>
      ${children}
    </section>
  `;
}

/** A Project or Deliverable row: title, type, status and due. @param {{item: Summary}} props */
function WorkRow({ item }) {
  return html`
    <li class="todo">
      <a href=${entityHref(item.id)}>${item.title}</a>
      <span class="muted">${typeLabel(item.type)}</span>
      ${item.fields.status && html`<span class="status status-${item.fields.status}">${item.fields.status}</span>`}
      ${item.fields.due &&
      html`<span class="due ${isOverdue(item.fields.due) ? "overdue" : ""}">due ${item.fields.due}</span>`}
    </li>
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
