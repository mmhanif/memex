// @ts-check
// Portfolio (SPEC §11.3), per "Portfolio — Board" and "Portfolio — Outline" in Paper: the
// board (status columns of Projects or Deliverables, a status menu on each card) and the
// outline (Theme → Project → Deliverable, cells edited in place, inline create rows). Theme
// chips filter both. The page's settings live in the route
// (`?kind=deliverable&themes=a,b&archived=1`, `-` for "No theme"), not in client state
// (§11.1), so a filtered view is a link.

import { useEffect, useRef, useState } from "preact/hooks";
import { describe, request } from "./api.js";
import { daysBetween, dayMonth, dueLabel, shortDate } from "./dates.js";
import { useDismiss } from "./dismiss.js";
import { FIELDS, FieldInput, WORK_STATUSES, initials, useCandidates, writeField } from "./fields.js";
import { Icon } from "./icons.js";
import { entityHref, navigate } from "./router.js";
import { html, meId, sameId, tree, useView, viewVersion } from "./state.js";
import { today } from "./todos.js";

/**
 * @typedef {import("./fields.js").Summary} Summary
 * @typedef {import("./fields.js").FieldSpec} FieldSpec
 * @typedef {{status: string | null, items: Summary[]}} Column
 * @typedef {{mode: "board", kind: string, columns: Column[], chips: Summary[],
 *   attention: Record<string, Summary[]>, names: Record<string, string>}} BoardData
 * @typedef {{project: Summary, deliverables: Summary[]}} OutlineProject
 * @typedef {{theme: Summary | null, projects: OutlineProject[]}} OutlineTheme
 * @typedef {{mode: "outline", themes: OutlineTheme[], without_project: Summary[], chips: Summary[],
 *   names: Record<string, string>}} OutlineData
 * @typedef {{kind: string, themes: string[], archived: boolean}} Settings
 */

/** The route's stand-in for "No theme" among the chosen Themes. */
const NO_THEME = "-";

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
  const text = query.toString().replace(/%2C/g, ",");
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

const FINISHED = ["done", "cancelled"];

/** @param {number} n @param {string} one */
function count(n, one) {
  return `${n} ${one}${n === 1 ? "" : "s"}`;
}

/** @param {{view: string, query?: URLSearchParams}} props */
export function PortfolioPage({ view, query: routeQuery }) {
  const mode = view === "outline" ? "outline" : "board";
  const settings = settingsFrom(routeQuery);
  const go = (/** @type {Partial<Settings>} */ change) => navigate(portfolioHref(mode, { ...settings, ...change }));
  const query = new URLSearchParams({
    mode,
    kind: settings.kind,
    themes: settings.themes.filter((t) => t !== NO_THEME).join(","),
    include_archived: String(settings.archived),
    unthemed: String(settings.themes.includes(NO_THEME)),
  });
  const { data, error } = useView(`/api/views/portfolio?${query}`);
  const shown = /** @type {BoardData | OutlineData | null} */ (data);
  const ready = shown && shown.mode === mode && (shown.mode !== "board" || shown.kind === settings.kind) ? shown : null;
  const readOnly = tree.value?.workspace.read_only ?? false;

  return html`
    <section class="page portfolio-page">
      <header class="portfolio-head">
        <p class="eyebrow">${ready ? summaryLine(ready) : " "}</p>
        <h1 class="title">Portfolio</h1>
      </header>
      <div class="portfolio-controls">
        ${mode === "board" &&
        html`<nav class="segmented" aria-label="Show">
          ${[
            { key: "project", label: "Projects" },
            { key: "deliverable", label: "Deliverables" },
          ].map(
            (k) => html`<a href=${portfolioHref("board", { ...settings, kind: k.key })}
              class=${settings.kind === k.key ? "active" : ""}
              aria-current=${settings.kind === k.key ? "true" : undefined}>${k.label}</a>`,
          )}
        </nav>`}
        ${shown && html`<${Chips} chips=${shown.chips} settings=${settings} go=${go} />`}
        <nav class="view-toggle" aria-label="Portfolio views">
          <a href=${portfolioHref("board", settings)} class=${mode === "board" ? "active" : ""}
            aria-current=${mode === "board" ? "page" : undefined}><${Icon} name="columns-3" />Board</a>
          <a href=${portfolioHref("outline", settings)} class=${mode === "outline" ? "active" : ""}
            aria-current=${mode === "outline" ? "page" : undefined}><${Icon} name="list-tree" />Outline</a>
        </nav>
      </div>
      ${error
        ? html`<p class="error-text" role="alert">${describe(error)}</p>`
        : !ready
          ? html`<p class="hint">Loading…</p>`
          : ready.mode === "board"
            ? html`<${Board} board=${ready} readOnly=${readOnly} />`
            : html`<${Outline} outline=${ready} readOnly=${readOnly} showArchived=${settings.archived} />`}
    </section>
  `;
}

/**
 * The eyebrow: "7 Projects · 1 blocked · 1 due this week" on the board, "2 Themes ·
 * 7 Projects · 5 Deliverables" on the outline.
 * @param {BoardData | OutlineData} data
 */
function summaryLine(data) {
  if (data.mode === "outline") {
    const projects = data.themes.flatMap((g) => g.projects);
    const deliverables = projects.reduce((n, p) => n + p.deliverables.length, 0) + data.without_project.length;
    return [
      count(data.themes.filter((g) => g.theme).length, "Theme"),
      count(projects.length, "Project"),
      count(deliverables, "Deliverable"),
    ].join(" · ");
  }
  const items = data.columns.flatMap((c) => c.items);
  const now = today();
  const open = items.filter((i) => !FINISHED.includes(i.fields.status));
  const dueIn = (/** @type {Summary} */ i) => typeof i.fields.due === "string" ? daysBetween(now, i.fields.due) : null;
  const late = open.filter((i) => (dueIn(i) ?? 0) < 0).length;
  const soon = open.filter((i) => { const d = dueIn(i); return d !== null && d >= 0 && d <= 7; }).length;
  return [
    count(items.length, data.kind === "deliverable" ? "Deliverable" : "Project"),
    `${open.filter((i) => i.fields.status === "blocked").length} blocked`,
    ...(late ? [`${late} overdue`] : []),
    `${soon} due this week`,
  ].join(" · ");
}

/**
 * Theme filter chips: All, each Theme, and No theme. None picked shows everything.
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
      .filter((t) => t !== NO_THEME && !chips.some((c) => c.id.toLowerCase() === t.toLowerCase()))
      .map((t) => ({ id: t, title: t, archived: false })),
  ];
  return html`
    <div class="theme-chips" role="group" aria-label="Themes">
      <span class="chips-label">Theme</span>
      <button type="button" class="theme-chip" aria-pressed=${chosen.length === 0} onClick=${() => go({ themes: [] })}>All</button>
      ${offered.map(
        (t) => html`<button type="button" class="theme-chip" aria-pressed=${picked.has(t.id.toLowerCase())}
          onClick=${() => toggle(t.id)}>${t.title}${t.archived ? " (archived)" : ""}</button>`,
      )}
      <button type="button" class="theme-chip no-theme" aria-pressed=${picked.has(NO_THEME)}
        onClick=${() => toggle(NO_THEME)}>No theme</button>
      <label class="check archived-check"><input type="checkbox" class="checkbox" checked=${settings.archived}
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

/** @param {{status: unknown}} props */
function StatusDot({ status }) {
  return html`<span class="dot ${typeof status === "string" ? `dot-${status}` : ""}" aria-hidden="true"></span>`;
}

/** @param {unknown} status */
function statusText(status) {
  if (typeof status === "string" && STATUS_LABELS[status]) return STATUS_LABELS[status];
  return `${status ?? "—"} (invalid)`;
}

/**
 * A work item's status as a button that opens the status menu (the board card's pill,
 * the outline's Status cell). Cancelled is offered last: it takes the card off the board.
 * @param {{item: Summary, readOnly: boolean, onPick: (status: string) => void, variant: "pill" | "cell"}} props
 */
function StatusMenu({ item, readOnly, onPick, variant }) {
  const [open, setOpen] = useState(false);
  const box = useRef(/** @type {HTMLDivElement | null} */ (null));
  const status = item.fields.status;
  useDismiss(box, open, () => setOpen(false));
  useEffect(() => {
    if (open) box.current?.querySelector(/** @type {"button"} */ ('[aria-checked="true"]'))?.focus();
  }, [open]);
  const label = `Status of ${item.title}`;
  /** @param {string} s */
  const pick = (s) => {
    setOpen(false);
    if (s !== status) onPick(s);
  };
  /** @param {string} s */
  const option = (s) => html`<li role="none"><button type="button" role="menuitemradio" class="popover-item"
    aria-checked=${s === status ? "true" : "false"} onClick=${() => pick(s)}>
    ${s === "cancelled" ? html`<${Icon} name="x" />` : html`<${StatusDot} status=${s} />`}
    <span class="grow">${STATUS_LABELS[s]}</span>
    ${s === status && html`<${Icon} name="check" />`}
    ${s === "cancelled" && variant === "pill" && html`<span class="item-hint">hides card</span>`}
  </button></li>`;
  return html`
    <div class="status-menu ${variant}" ref=${box}>
      <button type="button" class="status-button ${status === "blocked" ? "blocked" : ""}" aria-label=${label}
        aria-haspopup="menu" aria-expanded=${open} disabled=${readOnly || item.ambiguous}
        onClick=${() => setOpen(!open)}>
        <${StatusDot} status=${status} />${statusText(status)}
        ${variant === "pill" && html`<${Icon} name="chevron-down" />`}
      </button>
      ${open &&
      html`<ul class="popover status-popover" role="menu" aria-label=${label}>
        ${WORK_STATUSES.filter((s) => s !== "cancelled").map(option)}
        <li class="popover-sep" role="separator"></li>
        ${option("cancelled")}
      </ul>`}
    </div>
  `;
}

/** @param {{id: string, names: Record<string, string>, kind?: "stakeholder"}} props */
function Avatar({ id, names, kind }) {
  const name = names[id] ?? id;
  const me = sameId(id, meId());
  return html`<span class="avatar ${me ? "me" : ""} ${kind ?? ""}" title=${name}>${initials(name)}</span>`;
}

/** @param {{board: BoardData, readOnly: boolean}} props */
function Board({ board, readOnly }) {
  return html`
    <div class="board">
      ${board.columns.map((c) => {
        const label = c.status ? STATUS_LABELS[c.status] : "Invalid status";
        return html`<section class="board-column ${c.status ? "" : "invalid"}" aria-label=${label} key=${c.status ?? "-"}>
          <h2><${StatusDot} status=${c.status} /><span class="column-label">${label}</span>${" "}<span class="count">${c.items.length}</span></h2>
          ${c.items.map(
            (item) => html`<${Card} key=${item.id} item=${item} names=${board.names}
              attention=${board.attention?.[item.id] ?? []} readOnly=${readOnly} />`,
          )}
        </section>`;
      })}
    </div>
  `;
}

/** @param {{item: Summary, names: Record<string, string>, attention: Summary[], readOnly: boolean}} props */
function Card({ item, names, attention, readOnly }) {
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const { status, due, lead, theme, project } = item.fields;
  const parent = item.type === "deliverable" ? project : theme;
  const finished = FINISHED.includes(status);
  const now = today();
  const dueIn = typeof due === "string" ? daysBetween(now, due) : null;
  const late = dueIn !== null && dueIn < 0 && !finished;
  const soon = dueIn !== null && dueIn >= 0 && dueIn <= 7 && !finished;
  return html`
    <article class="card board-card ${status === "blocked" ? "blocked" : ""} ${finished ? "finished" : ""}">
      <div class="card-head">
        <a class="card-title" href=${entityHref(item.id, item.type)}>${item.title}</a>
        <div class="card-parent">${typeof parent === "string" && parent ? names[parent] ?? parent : item.type === "project" ? "No theme" : ""}</div>
      </div>
      ${attention.length > 0 &&
      html`<ul class="card-attention">
        ${attention.map((d) => {
          const blocked = d.fields.status === "blocked";
          const days = typeof d.fields.due === "string" ? daysBetween(d.fields.due, now) : 0;
          return html`<li key=${d.id}>
            <span class="mini-bullet" aria-hidden="true"></span>
            <a href=${entityHref(d.id, d.type)}>${d.title}</a>${" "}
            <span class=${blocked ? "blocked-tag" : "late"}>${blocked ? "blocked" : `${days}d late`}</span>
          </li>`;
        })}
      </ul>`}
      <div class="card-meta">
        <${StatusMenu} item=${item} readOnly=${readOnly} variant="pill"
          onPick=${(/** @type {string} */ s) => void saveField(item, "status", s, setError)} />
        <span class="card-due ${late ? "late" : soon ? "soon" : ""}">
          ${typeof due === "string" && (late ? dueLabel(due, now) : soon ? shortDate(due) : dayMonth(due))}
        </span>
        ${typeof lead === "string" && lead && html`<${Avatar} id=${lead} names=${names} />`}
        ${item.warnings.length > 0 && html`<span class="broken" title=${item.warnings.map((w) => w.message).join("; ")}>!</span>`}
      </div>
      ${error && html`<span class="field-error">${error}</span>`}
    </article>
  `;
}

const CELLS = ["lead", "team", "stakeholders", "due"];

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
    <table class="data-table portfolio-outline">
      <thead>
        <tr><th class="col-name">Name</th><th class="col-status">Status</th><th class="col-lead">Lead</th>
          <th class="col-team">Team</th><th class="col-stakeholders">Stakeholders</th><th class="col-due">Due</th></tr>
      </thead>
      <tbody>
        ${outline.themes.map((g) => {
          const key = g.theme ? `t:${g.theme.id}` : "t:";
          const open = !collapsed.has(key);
          return html`
            <${ThemeRow} ...${row} key=${key} theme=${g.theme} open=${open} onToggle=${() => toggle(key)}
              projects=${g.projects.length} />
            ${open &&
            g.projects.map((p) => {
              const pkey = `p:${p.project.id}`;
              const popen = !collapsed.has(pkey);
              const kids = p.deliverables.length;
              return html`
                <${Row} ...${row} key=${pkey} depth=${1} item=${p.project}
                  open=${popen} onToggle=${kids ? () => toggle(pkey) : undefined}
                  meta=${!popen ? count(kids, "Deliverable") : ""} />
                ${popen && p.deliverables.map((d) => html`<${Row} ...${row} key=${`d:${d.id}`} depth=${2} item=${d} />`)}
                ${popen && !readOnly &&
                html`<${CreateRow} key=${`nd:${p.project.id}`} depth=${2} type="deliverable"
                  label="Deliverable" parent=${p.project} fields=${{ project: p.project.id }} />`}
              `;
            })}
            ${open && !readOnly &&
            html`<${CreateRow} key=${`np:${key}`} depth=${1} type="project"
              label=${g.theme ? `Project in ${g.theme.title}` : "Project"}
              parent=${g.theme} fields=${g.theme ? { theme: g.theme.id } : {}} />`}
          `;
        })}
      </tbody>
    </table>
    ${outline.themes.length === 0 && html`<p class="section-empty">Nothing here yet: start with + New… Theme or Project.</p>`}
    ${outline.without_project.length > 0 &&
    html`<section class="without-project">
      <h2 class="section-header">Deliverables without a Project</h2>
      <p class="section-empty">Their <code>project</code> names nothing: open each to fix it.</p>
      <table class="data-table portfolio-outline">
        <tbody>${outline.without_project.map((d) => html`<${Row} ...${row} key=${`wp:${d.id}`} depth=${1} item=${d} />`)}</tbody>
      </table>
    </section>`}
  `;
}

/**
 * A Theme's group header: caret, name and Project count, then its Lead, Team and
 * Stakeholders edited in place like a Project's (a Theme has no Status or Due). "No theme"
 * is a header only.
 * @param {{
 *   theme: Summary | null, projects: number, candidates: Summary[], names: Record<string, string>,
 *   readOnly: boolean, showArchived: boolean, open: boolean, onToggle: () => void,
 * }} props
 */
function ThemeRow({ theme, projects, candidates, names, readOnly, showArchived, open, onToggle }) {
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const title = theme?.title ?? "No theme";
  const specs = FIELDS.theme;
  const cell = { candidates, names, locked: readOnly || !!theme?.ambiguous, showArchived };
  /** @param {string} name @param {any} value */
  const save = (name, value) => {
    if (theme) void saveField(theme, name, value, setError);
  };
  return html`
    <tr class="theme-row ${theme ? "" : "no-theme"}">
      <td class="col-name" colspan=${theme ? 1 : 6}>
        <div class="outline-name">
          <button type="button" class="caret" aria-expanded=${open} aria-label="${open ? "Collapse" : "Expand"} ${title}"
            onClick=${onToggle}><span class="tri ${open ? "open" : ""}"></span></button>
          ${theme ? html`<a class="theme-title" href=${entityHref(theme.id, "theme")}>${title}</a>` : html`<span class="theme-title">${title}</span>`}
          ${theme?.fields.archived && html`<span class="status status-cancelled">archived</span>`}
          <span class="row-meta">${theme ? "Theme · " : ""}${count(projects, "Project")}</span>
          ${error && html`<span class="field-error" role="alert">${error}</span>`}
        </div>
      </td>
      ${theme &&
      html`<td class="col-status"></td>
        ${["lead", "team", "stakeholders"].map((name) => html`<td class="col-${name}">
          <${EditCell} item=${theme} spec=${specs.find((s) => s.name === name)} save=${save} ...${cell} />
        </td>`)}
        <td class="col-due"></td>`}
    </tr>
  `;
}

/**
 * A Project or Deliverable: bullet and name, then its Status, Lead, Team, Stakeholders and
 * Due, each shown as text until clicked.
 * @param {{
 *   item: Summary, depth: number, candidates: Summary[], names: Record<string, string>,
 *   readOnly: boolean, showArchived: boolean, open?: boolean, onToggle?: () => void, meta?: string,
 * }} props
 */
function Row({ item, depth, candidates, names, readOnly, showArchived, open, onToggle, meta }) {
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const specs = FIELDS[item.type] ?? [];
  const finished = FINISHED.includes(item.fields.status);
  const locked = readOnly || item.ambiguous;
  /** @param {string} name @param {any} value */
  const save = (name, value) => void saveField(item, name, value, setError);
  const cell = { candidates, names, locked, showArchived };
  return html`
    <tr class="outline-row depth-${depth} ${item.type} ${finished ? "finished" : ""} ${open === false ? "collapsed" : ""}">
      <td class="col-name">
        <div class="outline-name">
          ${onToggle
            ? html`<button type="button" class="caret" aria-expanded=${open} aria-label="${open ? "Collapse" : "Expand"} ${item.title}"
                onClick=${onToggle}><span class="tri ${open ? "open" : ""}"></span></button>`
            : html`<span class="caret" aria-hidden="true"></span>`}
          <span class="row-bullet" aria-hidden="true"></span>
          <a class="row-title" href=${entityHref(item.id, item.type)}>${item.title}</a>
          ${item.type === "deliverable" && html`<span class="type-tag">Deliverable</span>`}
          ${meta && html`<span class="row-meta">${meta}</span>`}
          ${item.fields.archived && html`<span class="status status-cancelled">archived</span>`}
          ${item.warnings.length > 0 &&
          html`<span class="broken" title=${item.warnings.map((w) => w.message).join("; ")}>!</span>`}
          ${error && html`<span class="field-error" role="alert">${error}</span>`}
        </div>
      </td>
      <td class="col-status">
        <${StatusMenu} item=${item} readOnly=${readOnly} variant="cell" onPick=${(/** @type {string} */ s) => save("status", s)} />
      </td>
      ${CELLS.map((name) => html`<td class="col-${name}">
        <${EditCell} item=${item} spec=${specs.find((s) => s.name === name)} save=${save} ...${cell} />
      </td>`)}
    </tr>
  `;
}

/**
 * A field's outline cell: its value until clicked, then its FieldInput. Empty for a field
 * the type doesn't have.
 * @param {{
 *   item: Summary, spec: FieldSpec | undefined, save: (name: string, value: any) => void,
 *   candidates: Summary[], names: Record<string, string>, locked: boolean, showArchived: boolean,
 * }} props
 */
function EditCell({ item, spec, save, candidates, names, locked, showArchived }) {
  if (!spec) return null;
  return html`<${Cell} item=${item} spec=${spec} names=${names} locked=${locked}
    editor=${html`<${FieldInput}
      spec=${spec}
      value=${item.fields[spec.name]}
      onChange=${(/** @type {any} */ v) => save(spec.name, v)}
      candidates=${candidates}
      names=${names}
      showArchived=${showArchived}
      inputId=${`${item.id}-${spec.name}`}
      ariaLabel="${spec.label} of ${item.title}"
    />`} />`;
}

/**
 * One outline cell: its value as text (avatars, a date) until clicked, then its editor.
 * A click elsewhere, Escape, or tabbing out puts the text back.
 * @param {{item: Summary, spec: FieldSpec, names: Record<string, string>, locked: boolean, editor: any}} props
 */
function Cell({ item, spec, names, locked, editor }) {
  const [editing, setEditing] = useState(false);
  const box = useRef(/** @type {HTMLDivElement | null} */ (null));
  useEffect(() => {
    if (!editing) return;
    const el = box.current;
    const details = el?.querySelector("details");
    if (details) details.open = true;
    /** @type {HTMLElement | null | undefined} */ (el?.querySelector("input, select, summary"))?.focus();
  }, [editing]);
  useDismiss(box, editing, () => setEditing(false));
  const shown = html`<${CellValue} item=${item} name=${spec.name} names=${names} />`;
  if (locked) return html`<div class="cell-value">${shown}</div>`;
  if (!editing) {
    return html`<button type="button" class="cell-value" aria-label="Edit ${spec.label} of ${item.title}"
      onClick=${() => setEditing(true)}>${shown}</button>`;
  }
  return html`<div class="cell-editor" ref=${box}
    onFocusOut=${(/** @type {FocusEvent} */ e) => {
      const next = /** @type {Node | null} */ (e.relatedTarget);
      if (next && !box.current?.contains(next)) setEditing(false);
    }}>${editor}</div>`;
}

/** @param {{item: Summary, name: string, names: Record<string, string>}} props */
function CellValue({ item, name, names }) {
  const value = item.fields[name];
  const none = html`<span class="none">—</span>`;
  if (name === "lead") {
    if (typeof value !== "string" || !value) return none;
    return html`<span class="cell-person"><${Avatar} id=${value} names=${names} /><span class="cell-name">${names[value] ?? value}${sameId(value, meId()) && html` <span class="faint">(Me)</span>`}</span></span>`;
  }
  if (name === "team" || name === "stakeholders") {
    const list = Array.isArray(value) ? value.filter((v) => typeof v === "string") : [];
    if (!list.length) return none;
    return html`<span class="cell-avatars">${list.map(
      (v) => html`<${Avatar} id=${v} names=${names} kind=${name === "stakeholders" ? "stakeholder" : undefined} />`,
    )}</span>`;
  }
  if (name === "due") {
    if (typeof value !== "string" || !value) return none;
    const now = today();
    const late = daysBetween(value, now);
    if (late > 0 && !FINISHED.includes(item.fields.status)) {
      return html`<span class="cell-due late">${dayMonth(value)}<span class="late-by">${dueLabel(value, now)}</span></span>`;
    }
    return html`<span class="cell-due">${dayMonth(value)}</span>`;
  }
  return value == null ? none : String(value);
}

/**
 * "+ Deliverable" / "+ Project in Platform": a title box that creates on Enter with the
 * default Template.
 * @param {{depth: number, type: string, label: string, parent: Summary | null, fields: Record<string, string>}} props
 */
function CreateRow({ depth, type, label, parent, fields }) {
  const [title, setTitle] = useState("");
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const kind = type === "project" ? "Project" : "Deliverable";
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
          <span class="caret" aria-hidden="true"></span>
          <${Icon} name="plus" />
          <input aria-label="New ${kind}${where}" placeholder=${label} value=${title}
            onInput=${(/** @type {Event} */ e) => setTitle(/** @type {HTMLInputElement} */ (e.currentTarget).value)} />
          ${error && html`<span class="field-error" role="alert">${error}</span>`}
        </form>
      </td>
    </tr>
  `;
}
