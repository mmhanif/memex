// @ts-check
// The People page (SPEC §11.3: org tree from Me, other Team Members, Stakeholders) and
// the Person View (§11.6: header, Tagged on, the two To-do columns, 1:1s, the body).

import { useState } from "preact/hooks";
import { ApiError, describe, request } from "./api.js";
import { BodySection, LinkList, Properties, Title, Warnings } from "./entity.js";
import { initials, typeLabel, useCandidates } from "./fields.js";
import { Icon } from "./icons.js";
import { openNew } from "./newform.js";
import { entityHref, fileHref, personHref } from "./router.js";
import { html, meId, tree, useView, viewVersion } from "./state.js";
import { QuickAdd, TodoGroups } from "./todos.js";

/**
 * @typedef {import("./fields.js").Summary} Summary
 * @typedef {import("./entity.js").Detail} Detail
 * @typedef {import("./todos.js").TodoGroup} TodoGroup
 * @typedef {{person: Summary, reports: OrgNode[]}} OrgNode
 * @typedef {{manager: Summary | null, me: OrgNode | null, others: Summary[],
 *   stakeholders: {person: Summary, tags: number}[]}} People
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

/** @param {{person: Summary}} props */
function PersonLink({ person }) {
  return html`<a class="person-link" href=${personHref(person.id)}>
    <span class="avatar">${initials(person.title)}</span>${person.title}
    ${person.fields.role && html`<span class="muted">${person.fields.role}</span>`}
  </a>`;
}

/** @param {{node: OrgNode}} props */
function OrgBranch({ node }) {
  return html`
    <li>
      <${PersonLink} person=${node.person} />
      ${node.reports.length > 0 &&
      html`<ul>${node.reports.map((r) => html`<${OrgBranch} key=${r.person.id} node=${r} />`)}</ul>`}
    </li>
  `;
}

export function PeoplePage() {
  const { data, error } = useView("/api/views/people");
  const people = /** @type {People | null} */ (data);
  if (error) return html`<section class="page"><p class="error-text" role="alert">${describe(error)}</p></section>`;
  if (!people) return html`<p class="hint">Loading…</p>`;
  return html`
    <section class="page people-page">
      <header class="page-head">
        <h1>People</h1>
        <button type="button" onClick=${() => openNew("person")}><${Icon} name="plus" /> Person</button>
      </header>
      <h2>Org</h2>
      ${people.me
        ? html`<div class="org">
            ${people.manager && html`<div class="org-manager"><${PersonLink} person=${people.manager} /></div>`}
            <ul class="org-tree"><${OrgBranch} node=${people.me} /></ul>
          </div>`
        : html`<p class="muted">Me isn't set, so there is no org tree: pick your Person in Settings.</p>`}
      ${people.others.length > 0 &&
      html`<h2>Other Team Members</h2>
        <ul class="people-list">${people.others.map((p) => html`<li key=${p.id}><${PersonLink} person=${p} /></li>`)}</ul>`}
      <h2>Stakeholders</h2>
      ${people.stakeholders.length
        ? html`<table class="table">
            <thead><tr><th>Name</th><th>Organisation</th><th>Role</th><th>Tags</th></tr></thead>
            <tbody>
              ${people.stakeholders.map(
                (s) => html`<tr key=${s.person.id}>
                  <td><a href=${personHref(s.person.id)}>${s.person.title}</a></td>
                  <td>${s.person.fields.organisation ?? ""}</td>
                  <td>${s.person.fields.role ?? ""}</td>
                  <td>${s.tags}</td>
                </tr>`,
              )}
            </tbody>
          </table>`
        : html`<p class="muted">No Stakeholders yet</p>`}
    </section>
  `;
}

/** `#/people/<id>` (§11.6). @param {{id: string}} props */
export function PersonPage({ id }) {
  const [showDone, setShowDone] = useState(false);
  const { data, error, reload } = useView(
    /** @type {string} */ (`/api/views/person/${encodeURIComponent(id)}?include_done=${showDone}`),
  );
  const view = /** @type {PersonData | null} */ (data);
  if (error) return html`<section class="entity"><p class="error-text" role="alert">${describe(error)}</p></section>`;
  if (!view || view.person.id.toLowerCase() !== id.toLowerCase()) return html`<p class="hint">Loading…</p>`;
  const person = view.person;
  const name = person.title;
  const readOnly = person.read_only || (tree.value?.workspace.read_only ?? false);
  const me = meId();

  return html`
    <article class="entity person-view">
      <header class="entity-head">
        <span class="type-badge">Person</span>
        <${Title} detail=${person} readOnly=${readOnly} onSaved=${reload} />
        ${person.fields.archived && html`<span class="status status-cancelled">archived ${person.fields.archived}</span>`}
        <button type="button" disabled=${readOnly}
          onClick=${() => openNew("note", { people: me && me !== person.id ? [me, person.id] : [person.id] }, "one-on-one")}>
          <${Icon} name="plus" /> New 1:1
        </button>
        <a class="button" href=${fileHref(person.path)} title="Open the raw file"><${Icon} name="file-text" /> Open file</a>
      </header>
      <${Warnings} detail=${person} />
      <${Properties} detail=${person} readOnly=${readOnly} onSaved=${reload} />
      ${view.directs.length > 0 &&
      html`<p class="directs">Directs: ${view.directs.map((d) => html`<${PersonLink} key=${d.id} person=${d} />`)}</p>`}

      <div class="columns">
        <section class="column" aria-label="Tagged on">
          <h2>Tagged on</h2>
          ${view.tagged_on.length
            ? html`<ul class="tagged">
                ${view.tagged_on.map(
                  (t) => html`<li key=${t.item.id}>
                    <a href=${entityHref(t.item.id)}>${t.item.title}</a>
                    <span class="muted">${typeLabel(t.item.type)} · ${t.roles.join(", ")}</span>
                    ${t.item.fields.status && html`<span class="status status-${t.item.fields.status}">${t.item.fields.status}</span>`}
                  </li>`,
                )}
              </ul>`
            : html`<p class="muted">Not Tagged on anything yet</p>`}
          ${!readOnly && html`<${TagPicker} person=${person.id} name=${name} tagged=${view.tagged_on.map((t) => t.item.id)} />`}
        </section>
        <section class="column" aria-label="Waiting on ${name}">
          <h2>Waiting on ${name}</h2>
          <${QuickAdd} label="Add a To-do waiting on ${name}" defaults=${{ owner: person.id }}
            placeholder="What ${name} owes: Title due:YYYY-MM-DD" />
          <${TodoGroups} list=${{ groups: view.waiting_on_them, names: view.names }} hide="owner"
            headings=${showDone} empty="Nothing waiting on ${name}" />
        </section>
        <section class="column" aria-label="${name} is waiting on me">
          <h2>${name} is waiting on me</h2>
          <${QuickAdd} label="Add a To-do ${name} is waiting on" defaults=${{ requester: person.id }}
            placeholder="What I owe ${name}: Title due:YYYY-MM-DD" />
          <${TodoGroups} list=${{ groups: view.waiting_on_me, names: view.names }} hide="requester"
            headings=${showDone} empty="${name} isn't waiting on anything" />
        </section>
      </div>
      <label class="check"><input type="checkbox" checked=${showDone}
        onChange=${(/** @type {Event} */ e) => setShowDone(/** @type {HTMLInputElement} */ (e.currentTarget).checked)} />
        Show completed</label>

      <section class="related">
        <${LinkList} title="Notes with ${name}" items=${view.notes} />
      </section>
      <${BodySection} detail=${person} readOnly=${readOnly} />
    </article>
  `;
}

const TAG_ROLES = [
  { field: "team", label: "Team" },
  { field: "stakeholders", label: "Stakeholder" },
];

/**
 * "Tag <name> to…": pick a work item and a role; writes the Tag on that item (§11.7).
 * @param {{person: string, name: string, tagged: string[]}} props
 */
function TagPicker({ person, name, tagged }) {
  const candidates = useCandidates();
  const [item, setItem] = useState("");
  const [role, setRole] = useState("team");
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const options = candidates.filter(
    (c) => ["theme", "project", "deliverable"].includes(c.type) && !c.fields.archived && !tagged.includes(c.id),
  );

  /** @param {Event} e */
  async function tag(e) {
    e.preventDefault();
    const target = options.find((c) => c.id === item);
    if (!target) return;
    const current = Array.isArray(target.fields[role]) ? target.fields[role] : [];
    try {
      await request("PATCH", `/api/entities/${encodeURIComponent(target.id)}`, {
        json: { set: { [role]: [...current, person] }, unset: [] },
        ifMatch: target.hash,
      });
      setItem("");
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError && err.code === "conflict" ? "It changed on disk: try again" : describe(err));
    }
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
