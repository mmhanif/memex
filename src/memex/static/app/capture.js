// @ts-check
// Inline To-do capture (SPEC §6.4): "Create N To-dos" on a Note opens a preview of its
// unchecked task items, each parsed by the quick-add parser. Rows can be unticked and
// their parties, due and About edited; rows with errors block until fixed or unticked.
// Confirm is all-or-nothing on the server, against the hash the preview recorded.

import { signal } from "@preact/signals";
import { useEffect, useState } from "preact/hooks";
import { ApiError, describe, request } from "./api.js";
import { BodyDoc } from "./doc.js";
import { FIELDS, FieldInput, useCandidates } from "./fields.js";
import { html, openDoc, reloadTree, viewVersion } from "./state.js";

/**
 * @typedef {{field: string, token: string | null, message: string, candidates: string[]}} RowError
 * @typedef {{index: number, line: number, text: string, title: string, owner: string | null,
 *   requester: string | null, due: string | null, about: string | null, body: string,
 *   errors: RowError[]}} Row
 * @typedef {{id: string, hash: string, rows: Row[], names: Record<string, string>}} Preview
 * @typedef {{id: string, title: string}} CaptureTarget
 */

const EDITABLE = ["owner", "requester", "due", "about"];
const SPECS = Object.fromEntries((FIELDS.todo ?? []).filter((s) => EDITABLE.includes(s.name)).map((s) => [s.name, s]));
const CHANGED = "This Note changed, review again.";

/** The Note whose capture preview is open, if any. */
export const captureDialog = signal(/** @type {CaptureTarget | null} */ (null));

/**
 * Open the preview: save any pending edits to the Note first (§6.4 step 1).
 * @param {CaptureTarget} target
 */
export async function openCapture(target) {
  const doc = openDoc.value;
  if (doc instanceof BodyDoc && doc.id === target.id) await doc.flush();
  captureDialog.value = target;
}

function close() {
  captureDialog.value = null;
}

/** Mounted once in the shell. */
export function CaptureDialog() {
  const target = captureDialog.value;
  if (!target) return null;
  return html`
    <div class="dialog-backdrop" onClick=${(/** @type {Event} */ e) => e.target === e.currentTarget && close()}>
      <div class="dialog capture" role="dialog" aria-label="Create To-dos from ${target.title}"
        onKeyDown=${(/** @type {KeyboardEvent} */ e) => e.key === "Escape" && close()}>
        <h2>Create To-dos from ${target.title}</h2>
        <${CaptureForm} key=${target.id} id=${target.id} />
      </div>
    </div>
  `;
}

/** @param {{id: string}} props */
function CaptureForm({ id }) {
  const candidates = useCandidates();
  const [preview, setPreview] = useState(/** @type {Preview | null} */ (null));
  const [ticked, setTicked] = useState(/** @type {Set<number>} */ (new Set()));
  const [edits, setEdits] = useState(/** @type {Record<number, Record<string, any>>} */ ({}));
  const [notice, setNotice] = useState(/** @type {string | null} */ (null));
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const [busy, setBusy] = useState(false);
  const url = `/api/notes/${encodeURIComponent(id)}/capture`;

  async function load() {
    try {
      const next = /** @type {Preview} */ (await request("GET", url));
      setPreview(next);
      setTicked(new Set(next.rows.map((r) => r.index)));
      setEdits({});
      setError(null);
    } catch (e) {
      setError(describe(e));
    }
  }

  useEffect(() => {
    void load();
  }, [id]);

  if (!preview) return error ? html`<p class="error-text" role="alert">${error}</p>` : html`<p class="hint">Loading…</p>`;
  if (!preview.rows.length) {
    return html`<p class="muted">This Note has no To-dos to create.</p>
      <div class="dialog-actions"><button type="button" onClick=${close}>Close</button></div>`;
  }

  /** The errors a row still has: those on fields not edited since. @param {Row} row */
  const unfixedErrors = (row) => row.errors.filter((e) => !(e.field in (edits[row.index] ?? {})));
  const chosen = preview.rows.filter((r) => ticked.has(r.index));
  const blocked = chosen.some((r) => unfixedErrors(r).length > 0);

  /** @param {number} index @param {string} name @param {any} value */
  function edit(index, name, value) {
    setEdits({ ...edits, [index]: { ...edits[index], [name]: value } });
  }

  /** @param {number} index */
  function toggle(index) {
    const next = new Set(ticked);
    if (next.has(index)) next.delete(index);
    else next.add(index);
    setTicked(next);
  }

  /** @param {Event} e */
  async function submit(e) {
    e.preventDefault();
    if (!preview || blocked || !chosen.length || busy) return;
    setBusy(true);
    try {
      const rows = chosen.map((r) => ({ index: r.index, edits: edits[r.index] ?? {} }));
      await request("POST", url, { json: { hash: preview.hash, rows } });
      close();
      viewVersion.value += 1;
      void reloadTree();
    } catch (err) {
      if (err instanceof ApiError && err.code === "conflict") {
        setNotice(CHANGED);
        await load();
      } else {
        setError(describe(err));
      }
    } finally {
      setBusy(false);
    }
  }

  return html`
    <form onSubmit=${submit}>
      ${notice && html`<div class="banner info" role="status">${notice}</div>`}
      <ul class="capture-rows">
        ${preview.rows.map((row) => {
          const rowEdits = edits[row.index] ?? {};
          const errors = unfixedErrors(row);
          const on = ticked.has(row.index);
          /** @param {string} name */
          const value = (name) => (name in rowEdits ? rowEdits[name] : /** @type {any} */ (row)[name]);
          return html`
            <li key=${row.index} class="capture-row ${on && errors.length ? "has-errors" : ""} ${on ? "" : "unticked"}">
              <label class="check capture-title">
                <input type="checkbox" checked=${on} onChange=${() => toggle(row.index)}
                  aria-label="Create: ${row.title || row.text}" />
                <strong>${row.title || html`<span class="muted">(no title)</span>`}</strong>
                <span class="muted">line ${row.line}</span>
              </label>
              ${on &&
              html`<div class="form-grid">
                ${EDITABLE.map(
                  (name) => html`
                    <label for="capture-${row.index}-${name}">${SPECS[name].label}</label>
                    <${FieldInput} spec=${{ ...SPECS[name], required: false }} value=${value(name)}
                      inputId="capture-${row.index}-${name}" candidates=${candidates} names=${preview.names}
                      onChange=${(/** @type {any} */ v) => edit(row.index, name, v)} />
                  `,
                )}
              </div>`}
              ${on && row.body && html`<pre class="capture-body">${row.body}</pre>`}
              ${on &&
              errors.map(
                (er) => html`<span class="field-error">${er.token ? `${er.token}: ` : ""}${er.message}${
                  er.candidates.length ? ` (${er.candidates.join(", ")})` : ""
                }</span>`,
              )}
            </li>
          `;
        })}
      </ul>
      ${blocked && html`<p class="error-text">Fix or untick the rows in red to continue.</p>`}
      ${error && html`<p class="error-text" role="alert">${error}</p>`}
      <div class="dialog-actions">
        <button type="button" onClick=${close}>Cancel</button>
        <button type="submit" class="primary" disabled=${busy || blocked || !chosen.length}>
          Create ${chosen.length} To-do${chosen.length === 1 ? "" : "s"}
        </button>
      </div>
    </form>
  `;
}
