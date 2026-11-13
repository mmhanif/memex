// @ts-check
// Settings (SPEC §3.6). So far: the Templates section (§7.4) and the running version.
// Saves to the Workspace config are hash-checked like any write (§5.3).

import { useEffect, useState } from "preact/hooks";
import { ApiError, describe, request } from "./api.js";
import { TYPES } from "./fields.js";
import { fileHref, navigate } from "./router.js";
import { html, viewVersion } from "./state.js";

/**
 * @typedef {{hash: string, workspace: {me: string | null, polling: boolean, ignore: string[],
 *   hidden_templates: string[]}, config_error: string | null, read_only: boolean,
 *   version: string}} Settings
 * @typedef {{key: string, name: string, display_name: string, source: "blank" | "builtin" | "custom",
 *   default: boolean, hidden: boolean, overrides: boolean, error: string | null,
 *   path: string | null}} TemplateRow
 * @typedef {{type: string, label: string, templates: TemplateRow[], warnings: string[]}} TypeTemplates
 */

export function SettingsPage() {
  const [settings, setSettings] = useState(/** @type {Settings | null} */ (null));
  const [groups, setGroups] = useState(/** @type {TypeTemplates[]} */ ([]));
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
      setGroups(
        TYPES.map((t, i) => ({
          type: t.key,
          label: t.label,
          templates: perType[i].templates,
          warnings: perType[i].warnings,
        })),
      );
      setError(null);
    } catch (e) {
      setError(describe(e));
    }
  }

  useEffect(() => {
    void load();
  }, [version]);

  /** Hide or Show a built-in: edit `hidden_templates` (§7.4). @param {TemplateRow} row */
  async function toggleHidden(row) {
    if (!settings) return;
    const hidden = new Set(settings.workspace.hidden_templates);
    if (row.hidden) hidden.delete(row.key);
    else hidden.add(row.key);
    try {
      await request("PUT", "/api/settings", {
        json: { workspace: { hidden_templates: [...hidden].sort() } },
        ifMatch: settings.hash,
      });
      setNotice(null);
    } catch (e) {
      if (e instanceof ApiError && e.code === "conflict") {
        setNotice("The Workspace config changed on disk, so Settings reloaded. Try again.");
      } else {
        setError(describe(e));
      }
    }
    await load();
  }

  /** Customise: copy the built-in into the Workspace and open it raw. @param {string} type @param {TemplateRow} row */
  async function customise(type, row) {
    try {
      const { path } = await request("POST", "/api/templates/customise", {
        json: { type, name: row.name },
      });
      navigate(fileHref(path));
    } catch (e) {
      setError(describe(e));
    }
  }

  if (!settings) {
    return html`<section class="settings">${error ? html`<p class="error-text" role="alert">${error}</p>` : html`<p class="hint">Loading…</p>`}</section>`;
  }
  const locked = settings.read_only;
  return html`
    <section class="settings">
      <h1>Settings</h1>
      ${settings.config_error &&
      html`<div class="banner warn">The Workspace config doesn't parse, so Settings is read-only until it is fixed by hand.</div>`}
      ${notice && html`<div class="banner info" role="status">${notice}</div>`}
      ${error && html`<p class="error-text" role="alert">${error}</p>`}

      <h2>Templates</h2>
      <p class="muted">
        Custom Templates live in <code>${".memex/templates/<type>/<name>.md"}</code>. One with a
        built-in's name replaces it; deleting it brings the built-in back.
      </p>
      ${groups.map(
        (group) => html`
          <div class="template-group" aria-label="${group.label} Templates">
            <h3>${group.label}</h3>
            ${group.warnings.map((w) => html`<div class="banner warn">${w}</div>`)}
            <table class="templates">
              <tbody>
                ${group.templates.map(
                  (row) => html`
                    <tr class=${row.hidden || row.error ? "inactive" : ""}>
                      <td class="template-name">
                        ${row.default ? html`<span title="Default" aria-label="Default">★ </span>` : ""}${row.display_name}
                        <span class="muted"> ${row.key}</span>
                      </td>
                      <td>${sourceLabel(row)}</td>
                      <td>
                        ${row.hidden && html`<span class="status">hidden</span>`}
                        ${row.error && html`<span class="status status-blocked" title=${row.error}>broken: ${row.error}</span>`}
                      </td>
                      <td class="template-actions">
                        ${row.source === "builtin" &&
                        !row.hidden &&
                        html`<button type="button" disabled=${locked} onClick=${() => customise(group.type, row)}>Customise</button>`}
                        ${row.source === "builtin" &&
                        html`<button type="button" disabled=${locked} onClick=${() => toggleHidden(row)}>
                          ${row.hidden ? "Show" : "Hide"}
                        </button>`}
                        ${row.path && html`<a class="button" href=${fileHref(row.path)}>Edit</a>`}
                      </td>
                    </tr>
                  `,
                )}
              </tbody>
            </table>
          </div>
        `,
      )}

      <h2>About</h2>
      <p>Memex ${settings.version}</p>
      <p class="muted">Me, polling, ignore patterns, the Workspace path and the port arrive with the rest of this page.</p>
    </section>
  `;
}

/** @param {TemplateRow} row */
function sourceLabel(row) {
  if (row.source === "blank") return "Always available";
  if (row.source === "builtin") return "Built-in";
  return row.overrides ? "Custom, replaces the built-in" : "Custom";
}
