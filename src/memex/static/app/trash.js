// @ts-check
// `#/trash` (SPEC §8.4): deletes, newest first, with Restore.

import { useState } from "preact/hooks";
import { describe, request } from "./api.js";
import { html, reloadTree, tree, useView } from "./state.js";

/** @typedef {{entry: string, path: string, files: string[], deleted: string | null}} Trashed */

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
      await reload();
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
      ${entries &&
      entries.length > 0 &&
      html`<table class="trash">
        <thead><tr><th>Deleted</th><th>Path</th><th>Files</th><th></th></tr></thead>
        <tbody>
          ${entries.map(
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
