// @ts-check
// Portfolio (SPEC §11.3): the board (status columns of Projects or Deliverables, a status
// control on each card) and the outline (Theme → Project → Deliverable, with Status, Lead,
// Team, Stakeholders and Due edited in place, and inline create rows). Theme chips filter both.
// The page's settings live in the route (`?kind=deliverable&themes=a,b&archived=1`), not in
// client state (§11.1), so a filtered view is a link.

import { useState } from "preact/hooks";
import { describe, request } from "./api.js";
import { FIELDS, FieldInput, WORK_STATUSES, initials, useCandidates, writeField } from "./fields.js";
import { Icon } from "./icons.js";
import { entityHref, navigate } from "./router.js";
import { html, tree, useView, viewVersion } from "./state.js";
import { isOverdue } from "./todos.js";

/**
 * @typedef {import("./fields.js").Summary} Summary
 * @typedef {import("./fields.js").FieldSpec} FieldSpec
 * @typedef {{status: string | null, items: Summary[]}} Column
 * @typedef {{mode: "board", kind: string, columns: Column[], chips: Summary[], names: Record<string, string>}} BoardData
 * @typedef {{project: Summary, deliverables: Summary[]}} OutlineProject
 * @typedef {{theme: Summary | null, projects: OutlineProject[]}} OutlineTheme
 * @typedef {{mode: "outline", themes: OutlineTheme[], without_project: Summary[], chips: Summary[],
 *   names: Record<string, string>}} OutlineData
 * @typedef {{kind: string, themes: string[], archived: boolean}} Settings
 */

/** @param {URLSearchParams | undefined} query @returns {Settings} */
function settingsFrom(query) {
  return {
    kind: query?.get("kind") === "deliverable" ? "deliverable" : "project",
    themes: (query?.get("themes") ?? "").split(",").filter(Boolean),
    archived: query?.get("archived") === "1",
  };
}

/** @param {string} mode @param {Settings} settings */
function portfolioHref(mode, settings) {
  const query = new URLSearchParams();
  if (settings.kind !== "project") query.set("kind", settings.kind);
  if (settings.themes.length) query.set("themes", settings.themes.join(","));
  if (settings.archived) query.set("archived", "1");
  const text = query.toString();
  return `#/portfolio/${mode}${text ? `?${text}` : ""}`;
}

const STATUS_LABELS = /** @type {Record<string, string>} */ ({
  "not-started": "Not started",
  active: "Active",
  "on-hold": "On hold",
  blocked: "Blocked",
  done: "Done",
  cancelled: "Cancelled",
});

/** @param {{view: string, query?: URLSearchParams}} props */
export function PortfolioPage({ view, query: routeQuery }) {
  const mode = view === "outline" ? "outline" : "board";
  const settings = settingsFrom(routeQuery);
  const go = (/** @type {Partial<Settings>} */ change) => navigate(portfolioHref(mode, { ...settings, ...change }));
  const query = new URLSearchParams({
    mode,
    kind: settings.kind,
    themes: settings.themes.join(","),
    include_archived: String(settings.archived),
  });
  const { data, error } = useView(`/api/views/portfolio?${query}`);
  const shown = /** @type {BoardData | OutlineData | null} */ (data);
  const readOnly = tree.value?.workspace.read_only ?? false;

  return html`
    <section class="page portfolio-page">
      <header class="page-head">
        <h1>Portfolio</h1>
        ${mode === "board" &&
        html`<nav class="switch" aria-label="Show">
          ${[
            { key: "project", label: "Projects" },
            { key: "deliverable", label: "Deliverables" },
          ].map(
            (k) => html`<a href=${portfolioHref("board", { ...settings, kind: k.key })}
              class=${settings.kind === k.key ? "active" : ""}
              aria-current=${settings.kind === k.key ? "true" : undefined}>${k.label}</a>`,
          )}
        </nav>`}
        <nav class="switch" aria-label="Portfolio views">
          <a href=${portfolioHref("board", settings)} class=${mode === "board" ? "active" : ""}>Board</a>
          <a href=${portfolioHref("outline", settings)} class=${mode === "outline" ? "active" : ""}>Outline</a>
        </nav>
      </header>
      ${shown && html`<${Chips} chips=${shown.chips} settings=${settings} go=${go} />`}
      ${error
        ? html`<p class="error-text" role="alert">${describe(error)}</p>`
        : !shown || shown.mode !== mode || (shown.mode === "board" && shown.kind !== settings.kind)
          ? html`<p class="hint">Loading…</p>`
          : shown.mode === "board"
            ? html`<${Board} board=${shown} readOnly=${readOnly} />`
            : html`<${Outline} outline=${shown} readOnly=${readOnly} showArchived=${settings.archived} />`}
    </section>
  `;
}

/**
 * Theme filter chips: none picked shows everything.
 * @param {{chips: Summary[], settings: Settings, go: (change: Partial<Settings>) => void}} props
 */
function Chips({ chips, settings, go }) {
  const chosen = settings.themes;
  const picked = new Set(chosen.map((t) => t.toLowerCase()));
  /** @param {string} id */
  const toggle = (id) => {
    const key = id.toLowerCase();
    go({ themes: picked.has(key) ? chosen.filter((t) => t.toLowerCase() !== key) : [...chosen, id] });
  };
  // A picked Theme stays offered even when it's no longer a chip (archived since).
  const offered = [
    ...chips.map((c) => ({ id: c.id, title: c.title, archived: Boolean(c.fields.archived) })),
    ...chosen
      .filter((t) => !chips.some((c) => c.id.toLowerCase() === t.toLowerCase()))
      .map((t) => ({ id: t, title: t, archived: false })),
  ];
  return html`
    <div class="theme-chips" role="group" aria-label="Themes">
      ${offered.map(
        (t) => html`<button type="button" class="theme-chip" aria-pressed=${picked.has(t.id.toLowerCase())}
          onClick=${() => toggle(t.id)}>${t.title}${t.archived ? " (archived)" : ""}</button>`,
      )}
      ${chosen.length > 0 &&
      html`<button type="button" class="link-button" onClick=${() => go({ themes: [] })}>Show all</button>`}
      <label class="check"><input type="checkbox" checked=${settings.archived}
        onChange=${(/** @type {Event} */ e) => go({ archived: /** @type {HTMLInputElement} */ (e.currentTarget).checked })} />
        Show archived</label>
    </div>
  `;
}

/**
 * Write one field, show what went wrong on the row, and refetch the view.
 * @param {Summary} item
 * @param {string} name
 * @param {any} value null to unset
 * @param {(message: string | null) => void} setError
 */
async function saveField(item, name, value, setError) {
  setError(await writeField(item, name, value));
  viewVersion.value += 1;
}

/** @param {{board: BoardData, readOnly: boolean}} props */
function Board({ board, readOnly }) {
  return html`
    <div class="board">
      ${board.columns.map((c) => {
        const label = c.status ? STATUS_LABELS[c.status] : "Invalid status";
        return html`<section class="board-column ${c.status ? "" : "invalid"}" aria-label=${label} key=${c.status ?? "-"}>
          <h2>${label} <span class="muted">${c.items.length}</span></h2>
          ${c.items.map((item) => html`<${Card} key=${item.id} item=${item} names=${board.names} readOnly=${readOnly} />`)}
        </section>`;
      })}
    </div>
  `;
}

/** @param {{item: Summary, names: Record<string, string>, readOnly: boolean}} props */
function Card({ item, names, readOnly }) {
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const { status, due, lead, theme, project } = item.fields;
  const parent = item.type === "deliverable" ? project : theme;
  const finished = status === "done" || status === "cancelled";
  return html`
    <article class="card board-card">
      <a class="card-title" href=${entityHref(item.id)}>${item.title}</a>
      ${parent && html`<div class="muted card-parent">${names[parent] ?? parent}</div>`}
      <div class="card-meta">
        <select aria-label="Status of ${item.title}" value=${status ?? ""} disabled=${readOnly || item.ambiguous}
          onChange=${(/** @type {Event} */ e) =>
            void saveField(item, "status", /** @type {HTMLSelectElement} */ (e.currentTarget).value, setError)}>
          ${!WORK_STATUSES.includes(status) && html`<option value=${status ?? ""}>${status ?? "—"} (invalid)</option>`}
          ${WORK_STATUSES.map((s) => html`<option value=${s}>${STATUS_LABELS[s]}</option>`)}
        </select>
        ${typeof lead === "string" && html`<span class="avatar" title="Lead: ${names[lead] ?? lead}">${initials(names[lead] ?? lead)}</span>`}
        ${typeof due === "string" && html`<span class="due ${!finished && isOverdue(due) ? "overdue" : ""}">due ${due}</span>`}
        ${item.warnings.length > 0 && html`<span class="broken" title=${item.warnings.map((w) => w.message).join("; ")}>!</span>`}
      </div>
      ${error && html`<span class="field-error">${error}</span>`}
    </article>
  `;
}

const COLUMNS = ["status", "lead", "team", "stakeholders", "due"];

/** The outline's editable fields for a type, in column order; a Theme has no status or due. */
function columnSpecs(/** @type {string} */ type) {
  const specs = FIELDS[type] ?? [];
  return COLUMNS.map((name) => specs.find((s) => s.name === name) ?? null);
}

/** @param {{outline: OutlineData, readOnly: boolean, showArchived: boolean}} props */
function Outline({ outline, readOnly, showArchived }) {
  const candidates = useCandidates();
  const [collapsed, setCollapsed] = useState(/** @type {Set<string>} */ (new Set()));
  /** @param {string} key */
  const toggle = (key) => {
    const next = new Set(collapsed);
    if (!next.delete(key)) next.add(key);
    setCollapsed(next);
  };
  const row = { candidates, names: outline.names, readOnly, showArchived };

  return html`
    <table class="table outline">
      <thead>
        <tr><th>Name</th><th>Status</th><th>Lead</th><th>Team</th><th>Stakeholders</th><th>Due</th></tr>
      </thead>
      <tbody>
        ${outline.themes.map((g) => {
          const key = g.theme ? `t:${g.theme.id}` : "t:";
          const open = !collapsed.has(key);
          return html`
            <${Row} ...${row} key=${key} depth=${0} item=${g.theme} label="No theme"
              open=${open} onToggle=${() => toggle(key)} />
            ${open &&
            g.projects.map((p) => {
              const pkey = `p:${p.project.id}`;
              const popen = !collapsed.has(pkey);
              return html`
                <${Row} ...${row} key=${pkey} depth=${1} item=${p.project}
                  open=${popen} onToggle=${p.deliverables.length ? () => toggle(pkey) : undefined} />
                ${popen && p.deliverables.map((d) => html`<${Row} ...${row} key=${`d:${d.id}`} depth=${2} item=${d} />`)}
                ${popen && !readOnly &&
                html`<${CreateRow} key=${`nd:${p.project.id}`} depth=${2} type="deliverable" label="Deliverable"
                  parent=${p.project} fields=${{ project: p.project.id }} />`}
              `;
            })}
            ${open && !readOnly &&
            html`<${CreateRow} key=${`np:${key}`} depth=${1} type="project" label="Project"
              parent=${g.theme} fields=${g.theme ? { theme: g.theme.id } : {}} />`}
          `;
        })}
      </tbody>
    </table>
    ${outline.themes.length === 0 && html`<p class="muted">Nothing here yet: start with + New… Theme or Project.</p>`}
    ${outline.without_project.length > 0 &&
    html`<section>
      <h2>Deliverables without a Project</h2>
      <p class="muted">Their <code>project</code> names nothing: open each to fix it.</p>
      <table class="table outline">
        <tbody>${outline.without_project.map((d) => html`<${Row} ...${row} key=${`wp:${d.id}`} depth=${0} item=${d} />`)}</tbody>
      </table>
    </section>`}
  `;
}

/**
 * @param {{
 *   item: Summary | null, label?: string, depth: number, candidates: Summary[],
 *   names: Record<string, string>, readOnly: boolean, showArchived: boolean, open?: boolean,
 *   onToggle?: () => void,
 * }} props
 */
function Row({ item, label, depth, candidates, names, readOnly, showArchived, open, onToggle }) {
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const title = item?.title ?? label ?? "";
  return html`
    <tr class="outline-row depth-${depth} ${item?.type ?? "no-theme"}">
      <td class="outline-name">
        ${onToggle
          ? html`<button type="button" class="icon-button" aria-expanded=${open} aria-label="${open ? "Collapse" : "Expand"} ${title}"
              onClick=${onToggle}><${Icon} name=${open ? "chevron-down" : "chevron-right"} /></button>`
          : html`<span class="icon-spacer"></span>`}
        ${item ? html`<a href=${entityHref(item.id)}>${title}</a>` : html`<span class="muted">${title}</span>`}
        ${item?.fields.archived && html`<span class="status status-cancelled">archived</span>`}
        ${item && item.warnings.length > 0 &&
        html`<span class="broken" title=${item.warnings.map((w) => w.message).join("; ")}>!</span>`}
        ${error && html`<span class="field-error">${error}</span>`}
      </td>
      ${columnSpecs(item?.type ?? "").map(
        (spec) => html`<td>
          ${item && spec &&
          html`<${FieldInput}
            spec=${spec}
            value=${item.fields[spec.name]}
            onChange=${(/** @type {any} */ v) => void saveField(item, spec.name, v, setError)}
            candidates=${candidates}
            names=${names}
            showArchived=${showArchived}
            disabled=${readOnly || item.ambiguous}
            inputId=${`${item.id}-${spec.name}`}
            ariaLabel="${spec.label} of ${title}"
          />`}
        </td>`,
      )}
    </tr>
  `;
}

/**
 * "+ Project" / "+ Deliverable": a title box that creates on Enter with the default Template.
 * @param {{depth: number, type: string, label: string, parent: Summary | null, fields: Record<string, string>}} props
 */
function CreateRow({ depth, type, label, parent, fields }) {
  const [title, setTitle] = useState("");
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const where = parent ? ` in ${parent.title}` : "";

  /** @param {Event} e */
  async function create(e) {
    e.preventDefault();
    if (!title.trim()) return;
    try {
      await request("POST", "/api/entities", { json: { type, fields: { ...fields, title: title.trim() } } });
      setTitle("");
      setError(null);
    } catch (err) {
      setError(describe(err));
    }
    viewVersion.value += 1;
  }

  return html`
    <tr class="outline-row depth-${depth} create-row">
      <td colspan="6">
        <form class="outline-name" onSubmit=${create}>
          <span class="icon-spacer"><${Icon} name="plus" /></span>
          <input aria-label="New ${label}${where}" placeholder="+ ${label}" value=${title}
            onInput=${(/** @type {Event} */ e) => setTitle(/** @type {HTMLInputElement} */ (e.currentTarget).value)} />
          ${error && html`<span class="field-error" role="alert">${error}</span>`}
        </form>
      </td>
    </tr>
  `;
}
