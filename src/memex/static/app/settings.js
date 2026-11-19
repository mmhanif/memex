// @ts-check
// Settings (SPEC §3.6): the Workspace config (Me, ignore, polling), this computer's app
// config (Workspace path, port), the Templates (§7.4) and About. Saves to the Workspace
// config are hash-checked like any write (§5.3). Polling and the app config take effect
// after a relaunch; Memex can't restart itself, so the bar says to quit and run it again.

import { useEffect, useState } from "preact/hooks";
import { ApiError, describe, quitMemex, request } from "./api.js";
import { Avatar } from "./avatar.js";
import { Section } from "./entity.js";
import { TYPES, useCandidates } from "./fields.js";
import { Icon } from "./icons.js";
import { PersonPicker } from "./picker.js";
import { fileHref, navigate } from "./router.js";
import { html, viewVersion } from "./state.js";

/**
 * @typedef {"polling" | "workspace" | "port"} RelaunchKey
 * @typedef {{hash: string, workspace: {me: string | null, polling: boolean, ignore: string[],
 *   hidden_templates: string[]}, app: {workspace: string, port: number},
 *   running: {workspace: string, port: number, polling: boolean}, relaunch: RelaunchKey[],
 *   config_error: string | null, read_only: boolean,
 *   about: {version: string, format: number, address: string, logs: string}}} Settings
 * @typedef {{key: string, name: string, display_name: string, source: "blank" | "builtin" | "custom",
 *   default: boolean, hidden: boolean, overrides: boolean, error: string | null,
 *   path: string | null}} TemplateRow
 * @typedef {{type: string, label: string, row: TemplateRow}} TableRow
 */

export function SettingsPage() {
  const [settings, setSettings] = useState(/** @type {Settings | null} */ (null));
  const [rows, setRows] = useState(/** @type {TableRow[]} */ ([]));
  const [warnings, setWarnings] = useState(/** @type {string[]} */ ([]));
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const [notice, setNotice] = useState(/** @type {string | null} */ (null));
  const version = viewVersion.value;

  async function load() {
    try {
      const [loaded, ...perType] = await Promise.all([
        request("GET", "/api/settings"),
        ...TYPES.map((t) => request("GET", `/api/templates?type=${t.key}`)),
      ]);
      setSettings(loaded);
      setRows(TYPES.flatMap((t, i) => perType[i].templates.map((/** @type {TemplateRow} */ row) => ({ type: t.key, label: t.label, row }))));
      setWarnings(perType.flatMap((p) => p.warnings));
    } catch (e) {
      setError(describe(e));
    }
  }

  useEffect(() => {
    void load();
  }, [version]);

  /**
   * Save Workspace or app config keys, then reload.
   * @param {{workspace?: Record<string, unknown>, app?: Record<string, unknown>}} changes
   */
  async function save(changes) {
    if (!settings) return;
    try {
      await request("PUT", "/api/settings", { json: changes, ifMatch: settings.hash });
      setNotice(null);
      setError(null);
    } catch (e) {
      if (e instanceof ApiError && e.code === "conflict") {
        setNotice("The Workspace config changed on disk, so Settings reloaded. Try again.");
      } else {
        setError(describe(e));
      }
    }
    await load();
  }

  /** Hide or Show a built-in: edit `hidden_templates` (§7.4). @param {TemplateRow} row */
  function toggleHidden(row) {
    if (!settings) return;
    const hidden = new Set(settings.workspace.hidden_templates);
    if (row.hidden) hidden.delete(row.key);
    else hidden.add(row.key);
    void save({ workspace: { hidden_templates: [...hidden].sort() } });
  }

  /** Customise: copy the built-in into the Workspace and open it raw. @param {string} type @param {TemplateRow} row */
  async function customise(type, row) {
    try {
      const { path } = await request("POST", "/api/templates/customise", { json: { type, name: row.name } });
      navigate(fileHref(path));
    } catch (e) {
      setError(describe(e));
    }
  }

  if (!settings) {
    return html`<section class="page settings-page">
      ${error ? html`<p class="error-text" role="alert">${error}</p>` : html`<p class="hint">Loading…</p>`}
    </section>`;
  }
  const locked = settings.read_only;
  const { about } = settings;
  return html`
    <section class="page settings-page">
      <header class="settings-head">
        <p class="eyebrow">Memex ${about.version} · Workspace format ${about.format}</p>
        <h1 class="title">Settings</h1>
      </header>
      ${settings.config_error &&
      html`<div class="validation-bar settings-bar"><${Icon} name="triangle-alert" />
        <p>The Workspace config doesn't parse, so this section is read-only until it is fixed by hand.</p></div>`}
      ${notice && html`<div class="validation-bar warn settings-bar" role="alert"><${Icon} name="refresh-cw" /><p>${notice}</p></div>`}
      ${error && html`<p class="error-text settings-error" role="alert">${error}</p>`}

      <${Section} title="Workspace" action=${html`<code class="settings-file">.memex/config.yaml</code>`}>
        <${WorkspaceWell} settings=${settings} locked=${locked} save=${save} />
      <//>

      <${Section} title="This computer" action=${html`<code class="settings-file">Memex/config.yaml (app config)</code>`}>
        <${ComputerWell} settings=${settings} save=${save} />
        ${settings.relaunch.length > 0 && html`<${RelaunchBar} count=${settings.relaunch.length} />`}
      <//>

      <${Section} title="Templates" count=${templateCounts(rows)}
        action=${html`<code class="settings-file">.memex/templates/</code>`}>
        <${TemplatesTable} rows=${rows} warnings=${warnings} locked=${locked}
          onCustomise=${customise} onToggleHidden=${toggleHidden} />
      <//>

      <${Section} title="About">
        <dl class="about">
          <div><dt>Version</dt><dd>${about.version}</dd></div>
          <div><dt>Running at</dt><dd>${about.address}</dd></div>
          <div><dt>Logs</dt><dd class="about-logs">${about.logs}</dd></div>
        </dl>
      <//>
    </section>
  `;
}

/**
 * One label column, then the control.
 * @param {{label: string, hint: string, children?: any}} props
 */
function SettingRow({ label, hint, children }) {
  return html`
    <div class="setting">
      <div class="setting-label"><span class="setting-name">${label}</span><span class="setting-hint">${hint}</span></div>
      <div class="setting-value">${children}</div>
    </div>
  `;
}

/** "relaunch" until edited, then "relaunch needed". @param {{pending: boolean}} props */
function RelaunchTag({ pending }) {
  return pending ? html`<span class="tag pending">relaunch needed</span>` : html`<span class="tag">relaunch</span>`;
}

/**
 * Me, ignore globs and polling: `.memex/config.yaml`.
 * @param {{settings: Settings, locked: boolean, save: (changes: any) => Promise<void>}} props
 */
function WorkspaceWell({ settings, locked, save }) {
  const { me, ignore, polling } = settings.workspace;
  const people = useCandidates().filter((c) => c.type === "person");
  const [showArchived, setShowArchived] = useState(false);
  const [glob, setGlob] = useState("");
  const chosen = people.find((p) => p.id === me);

  function addGlob() {
    const value = glob.trim();
    if (!value) return;
    setGlob("");
    if (!ignore.includes(value)) void save({ workspace: { ignore: [...ignore, value] } });
  }

  return html`
    <div class="well settings-well">
      <${SettingRow} label="Me" hint='who "Me" means everywhere'>
        <span class="me-picker">
          ${chosen && html`<${Avatar} person=${chosen} />`}
          <${PersonPicker} id="setting-me" label="Me" multiple=${false} value=${me} people=${people}
            onChange=${(/** @type {string | null} */ id) => id && id !== me && save({ workspace: { me: id } })}
            showArchived=${showArchived} onShowArchived=${setShowArchived} placeholder="Pick a Person" />
          ${me && html`<code class="me-id">${me}</code>`}
          <${Icon} name="chevron-down" />
        </span>
      <//>
      <${SettingRow} label="Ignore" hint="hidden from tree, search, views">
        <span class="globs">
          ${ignore.map(
            (g) => html`<span class="glob-chip"><code>${g}</code>
              <button type="button" class="chip-remove" aria-label="Remove ${g}" disabled=${locked}
                onClick=${() => save({ workspace: { ignore: ignore.filter((x) => x !== g) } })}><${Icon} name="x" /></button></span>`,
          )}
          <input class="glob-add" aria-label="Add an ignore glob" placeholder="add glob…" value=${glob} disabled=${locked}
            onInput=${(/** @type {Event} */ e) => setGlob(/** @type {HTMLInputElement} */ (e.currentTarget).value)}
            onKeyDown=${(/** @type {KeyboardEvent} */ e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addGlob();
              }
            }}
            onBlur=${addGlob} />
        </span>
      <//>
      <${SettingRow} label="Polling" hint="for network or synced drives">
        <label class="toggle">
          <input type="checkbox" role="switch" aria-label="Polling" checked=${polling} disabled=${locked}
            onChange=${(/** @type {Event} */ e) => save({ workspace: { polling: /** @type {HTMLInputElement} */ (e.currentTarget).checked } })} />
          ${polling ? "On · poll for changes" : "Off · watch for changes natively"}
        </label>
        <${RelaunchTag} pending=${settings.relaunch.includes("polling")} />
      <//>
    </div>
  `;
}

/**
 * The Workspace path and port: the app config in the per-user Memex folder.
 * @param {{settings: Settings, save: (changes: any) => Promise<void>}} props
 */
function ComputerWell({ settings, save }) {
  const { app, running, relaunch } = settings;
  return html`
    <div class="well settings-well">
      <${SettingRow} label="Workspace path" hint="switching means a relaunch">
        <${SavedInput} label="Workspace path" className="path-input" value=${app.workspace}
          onSave=${(/** @type {string} */ v) => save({ app: { workspace: v } })} />
        <${RelaunchTag} pending=${relaunch.includes("workspace")} />
      <//>
      <${SettingRow} label="Port" hint="local only, 127.0.0.1">
        <${SavedInput} label="Port" className="port-input" value=${String(app.port)} inputMode="numeric"
          onSave=${(/** @type {string} */ v) => save({ app: { port: /^\d+$/.test(v.trim()) ? Number(v) : v } })} />
        ${relaunch.includes("port") && html`<span class="setting-was">was ${running.port}</span>`}
        <${RelaunchTag} pending=${relaunch.includes("port")} />
      <//>
    </div>
  `;
}

/**
 * A text box that saves on Enter or when it loses focus, if its value changed.
 * @param {{label: string, className: string, value: string, inputMode?: string, onSave: (value: string) => void}} props
 */
function SavedInput({ label, className, value, inputMode, onSave }) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const commit = () => draft.trim() !== value && onSave(draft.trim());
  return html`<input class="settings-input ${className}" aria-label=${label} value=${draft} inputmode=${inputMode}
    spellcheck=${false} autocomplete="off"
    onInput=${(/** @type {Event} */ e) => setDraft(/** @type {HTMLInputElement} */ (e.currentTarget).value)}
    onKeyDown=${(/** @type {KeyboardEvent} */ e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        commit();
      } else if (e.key === "Escape") setDraft(value);
    }}
    onBlur=${commit} />`;
}

/** Memex can't restart itself: say what a relaunch is and offer Quit. @param {{count: number}} props */
function RelaunchBar({ count }) {
  const changes = count === 1 ? "1 change takes" : `${count} changes take`;
  return html`
    <div class="relaunch-bar" role="status">
      <${Icon} name="refresh-cw" />
      <p><strong>Saved.</strong> ${changes} effect after a relaunch: quit Memex, then run <code>memex</code> again.</p>
      <button type="button" class="solid" onClick=${() => void quitMemex()}>Quit Memex</button>
    </div>
  `;
}

/** "14 built-in · 2 custom · 1 hidden · 1 broken". @param {TableRow[]} rows */
function templateCounts(rows) {
  const custom = rows.filter((r) => r.row.source === "custom").length;
  const hidden = rows.filter((r) => r.row.hidden).length;
  const broken = rows.filter((r) => r.row.error).length;
  return [
    `${rows.length - custom} built-in`,
    `${custom} custom`,
    hidden && `${hidden} hidden`,
    broken && `${broken} broken`,
  ]
    .filter(Boolean)
    .join(" · ");
}

/**
 * Every Template in one table. A Blank that isn't its type's default waits behind Show all.
 * @param {{rows: TableRow[], warnings: string[], locked: boolean,
 *   onCustomise: (type: string, row: TemplateRow) => void, onToggleHidden: (row: TemplateRow) => void}} props
 */
function TemplatesTable({ rows, warnings, locked, onCustomise, onToggleHidden }) {
  const [all, setAll] = useState(false);
  const shown = all ? rows : rows.filter((r) => r.row.source !== "blank" || r.row.default);
  return html`
    ${warnings.map((w) => html`<div class="validation-bar warn settings-bar"><${Icon} name="triangle-alert" /><p>${w}</p></div>`)}
    <table class="data-table templates-table" aria-label="Templates">
      <thead><tr><th class="col-type">Type</th><th>Template</th><th class="col-source">Source</th><th class="col-actions">Actions</th></tr></thead>
      <tbody>
        ${shown.map(({ type, label, row }) => {
          const off = row.hidden || row.error;
          return html`
            <tr key=${`${type}/${row.name}/${row.source}`} class=${off ? "inactive" : ""}>
              <td class="col-type">${label}</td>
              <td>
                <span class="template-cell">
                  <span class="template-title">${row.default ? "★ " : ""}${row.display_name}</span>
                  ${row.source === "blank"
                    ? html`<span class="template-note">always available</span>`
                    : html`<code class="template-key">${row.key}</code>`}
                  ${row.hidden && html`<span class="tag">hidden</span>`}
                  ${row.error && html`<span class="tag broken-tag">broken</span>`}
                </span>
                ${row.error && html`<span class="template-error">${row.error.replace(/\.$/, "")}. Left out of pickers until fixed.</span>`}
              </td>
              <td class="col-source ${row.source === "custom" ? "custom" : ""}">
                ${row.source === "custom" ? "custom" : "built-in"}
                ${row.overrides && html`<span class="template-note">replaces the built-in</span>`}
              </td>
              <td class="col-actions">
                ${row.source === "blank" && html`<span class="template-note">can't be hidden</span>`}
                ${row.source === "builtin" &&
                !row.hidden &&
                html`<button type="button" class="link-button" disabled=${locked} onClick=${() => onCustomise(type, row)}>Customise</button>`}
                ${row.source === "builtin" &&
                html`<button type="button" class="link-button" disabled=${locked} onClick=${() => onToggleHidden(row)}>
                  ${row.hidden ? "Show" : "Hide"}
                </button>`}
                ${row.path && html`<a href=${fileHref(row.path)}>Edit raw</a>`}
              </td>
            </tr>
          `;
        })}
      </tbody>
    </table>
    <p class="templates-foot">
      ${all
        ? html`Showing all ${rows.length} · <button type="button" class="link-button" onClick=${() => setAll(false)}>Show fewer</button>`
        : shown.length < rows.length &&
          html`Showing ${shown.length} of ${rows.length} · <button type="button" class="link-button" onClick=${() => setAll(true)}>Show all</button>`}
    </p>
    <p class="templates-lede">One with a built-in's name replaces it; deleting it brings the built-in back.</p>
  `;
}
