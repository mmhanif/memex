// @ts-check
// `#/broken` (SPEC §8.5): every Broken Reference and ambiguous reference, grouped by Id,
// each with Replace with…, Remove and Create. `#/trash` (§8.4): deletes, with Restore.

import { useState } from "preact/hooks";
import { describe, request } from "./api.js";
import { typeLabel, useCandidates } from "./fields.js";
import { entityHref, fileHref } from "./router.js";
import { html, reloadTree, tree, useView, viewVersion } from "./state.js";

/**
 * @typedef {{path: string, title: string, type: string | null, field: string}} Use
 * @typedef {{id: string, status: "missing" | "ambiguous", uses: Use[], create_types: string[],
 *   types: string[]}} Group
 * @typedef {{entry: string, path: string, files: string[], deleted: string | null}} Trashed
 */

export function BrokenPage() {
  const { data, error, reload } = useView("/api/broken-references");
  const groups = /** @type {{groups: Group[]} | null} */ (data)?.groups;
  const readOnly = tree.value?.workspace.read_only ?? false;
  return html`
    <section class="repair-page">
      <h1>Broken references</h1>
      <p class="hint">References and [[Mentions]] whose Id names no file, or more than one. Nothing is fixed
        automatically: pick a repair for each.</p>
      ${error && html`<p class="error-text" role="alert">${describe(error)}</p>`}
      ${groups && !groups.length && html`<p class="muted">No broken references.</p>`}
      ${groups?.map((g) => html`<${BrokenGroup} key=${g.id} group=${g} readOnly=${readOnly} onDone=${reload} />`)}
    </section>
  `;
}

/** @param {Use} use */
function useHref(use) {
  if (use.type === null) return "#/settings";
  return entityHref(use.path.split("/").pop()?.replace(/\.md$/, "") ?? "", use.type);
}

/** @param {{group: Group, readOnly: boolean, onDone: () => void}} props */
function BrokenGroup({ group, readOnly, onDone }) {
  const candidates = useCandidates();
  const [replacement, setReplacement] = useState("");
  const [createType, setCreateType] = useState(group.create_types[0] ?? "");
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const [busy, setBusy] = useState(false);
  const fits = candidates.filter((c) => group.types.includes(c.type) && c.id.toLowerCase() !== group.id.toLowerCase());

  /** @param {"replace" | "remove" | "create"} action */
  async function repair(action) {
    if (action === "remove" && !window.confirm(`Remove every reference to ${group.id}?`)) return;
    setBusy(true);
    try {
      await request("POST", "/api/broken-references/repair", {
        json: {
          id: group.id,
          action,
          replacement: action === "replace" ? replacement : null,
          type: action === "create" ? createType : null,
        },
      });
      setError(null);
      await reloadTree();
      viewVersion.value += 1;
      onDone();
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  }

  const creatable = group.create_types.length > 0;
  return html`
    <article class="broken-group" aria-label=${`Broken reference ${group.id}`}>
      <h2><code>${group.id}</code> <span class="status status-blocked">${group.status === "ambiguous" ? "ambiguous" : "missing"}</span></h2>
      <ul>
        ${group.uses.map(
          (u) => html`<li><a href=${useHref(u)}>${u.title}</a> <span class="muted">${u.field === "mention" ? "[[Mention]]" : u.field}</span>
            ${u.type !== null && html` · <a class="muted" href=${fileHref(u.path)}>${u.path}</a>`}</li>`,
        )}
      </ul>
      ${!readOnly &&
      html`<div class="repair-actions">
        <span>
          <select aria-label="Replace with" value=${replacement}
            onChange=${(/** @type {Event} */ e) => setReplacement(/** @type {HTMLSelectElement} */ (e.currentTarget).value)}>
            <option value="">Replace with…</option>
            ${fits.map((c) => html`<option value=${c.id}>${c.title} (${typeLabel(c.type)})</option>`)}
          </select>
          <button type="button" disabled=${busy || !replacement} onClick=${() => repair("replace")}>Replace</button>
        </span>
        <button type="button" disabled=${busy} onClick=${() => repair("remove")}>Remove</button>
        <span title=${creatable ? "" : group.status === "ambiguous" ? "A file already has this Id" : "The references disagree about the type"}>
          ${group.create_types.length > 1 &&
          html`<select aria-label="Type to create" value=${createType}
            onChange=${(/** @type {Event} */ e) => setCreateType(/** @type {HTMLSelectElement} */ (e.currentTarget).value)}>
            ${group.create_types.map((t) => html`<option value=${t}>${typeLabel(t)}</option>`)}
          </select>`}
          <button type="button" disabled=${busy || !creatable} onClick=${() => repair("create")}>
            Create${group.create_types.length === 1 ? ` ${typeLabel(group.create_types[0])}` : ""}
          </button>
        </span>
      </div>`}
      ${error && html`<p class="error-text" role="alert">${error}</p>`}
    </article>
  `;
}

export function TrashPage() {
  const { data, error, reload } = useView("/api/trash");
  const entries = /** @type {{entries: Trashed[]} | null} */ (data)?.entries;
  const [problem, setProblem] = useState(/** @type {string | null} */ (null));
  const readOnly = tree.value?.workspace.read_only ?? false;

  /** @param {Trashed} t */
  async function restore(t) {
    try {
      await request("POST", "/api/trash/restore", { json: { entry: t.entry } });
      setProblem(null);
      await reloadTree();
      reload();
    } catch (e) {
      setProblem(`Can't restore ${t.path}: ${describe(e)}`);
    }
  }

  return html`
    <section class="repair-page">
      <h1>Trash</h1>
      <p class="hint">Deleted files, newest first. Restore puts a file back where it was if its path and Id are
        still free; references rewritten when it was deleted stay as they are. Trash is never emptied automatically.</p>
      ${(error || problem) && html`<p class="error-text" role="alert">${problem ?? describe(error)}</p>`}
      ${entries && !entries.length && html`<p class="muted">The trash is empty.</p>`}
      ${entries && entries.length > 0 &&
      html`<table class="trash">
        <thead><tr><th>Deleted</th><th>Path</th><th>Files</th><th></th></tr></thead>
        <tbody>
          ${entries?.map(
            (t) => html`<tr key=${t.entry}>
              <td>${t.deleted ? t.deleted.replace("T", " ") : t.entry}</td>
              <td>${t.path}</td>
              <td>${t.files.length}</td>
              <td>${!readOnly && html`<button type="button" onClick=${() => restore(t)}>Restore</button>`}</td>
            </tr>`,
          )}
        </tbody>
      </table>`}
    </section>
  `;
}
