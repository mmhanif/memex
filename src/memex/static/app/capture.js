// @ts-check
// Inline To-do capture (SPEC §6.4): "Create N To-dos" on a Note opens a preview of its
// unchecked task items, each parsed by the quick-add parser. Rows can be unticked and
// their parties, due and About edited; rows with errors block until fixed or unticked.
// Confirm is all-or-nothing on the server, against the hash the preview recorded.

import { signal } from "@preact/signals";
import { useEffect, useRef, useState } from "preact/hooks";
import { ApiError, describe, request } from "./api.js";
import { shortDate } from "./dates.js";
import { BodyDoc } from "./doc.js";
import { FIELDS, FieldInput, initials, typeLabel, useCandidates } from "./fields.js";
import { Icon } from "./icons.js";
import { Avatar, PersonPicker } from "./picker.js";
import { entityHref } from "./router.js";
import { html, meId, openDoc, reloadTree, sameId, viewVersion } from "./state.js";

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
/** What fixing a row's error means, by field. */
const FIX = /** @type {Record<string, string>} */ ({
  owner: "pick an Owner or untick",
  requester: "pick a Requester or untick",
  due: "pick a date or untick",
  about: "pick one or untick",
});

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

/**
 * The bar over a Note's body while it has task items that aren't To-dos yet (§6.4).
 * @param {{count: number, onOpen: () => void}} props
 */
export function CaptureBar({ count, onOpen }) {
  const one = count === 1;
  return html`
    <div class="capture-bar">
      <span class="capture-bar-box" aria-hidden="true"></span>
      <p>${count} task ${one ? "item isn't a To-do" : "items aren't To-dos"} yet</p>
      <button type="button" class="primary" onClick=${onOpen}>Create ${count} To-do${one ? "" : "s"}</button>
    </div>
  `;
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
        <${CaptureForm} key=${target.id} target=${target} />
      </div>
    </div>
  `;
}

/** @param {number} n */
const todos = (n) => `${n} To-do${n === 1 ? "" : "s"}`;

/**
 * The preview as a table: tick, To-do (with its body line and any error), Owner,
 * Requester, Due and About. A cell shows its value; clicking it opens its editor. A cell
 * with an error shows its editor at once, outlined in rust.
 * @param {{target: CaptureTarget}} props
 */
function CaptureForm({ target }) {
  const { id } = target;
  const candidates = useCandidates();
  const people = candidates.filter((c) => c.type === "person");
  const [preview, setPreview] = useState(/** @type {Preview | null} */ (null));
  const [ticked, setTicked] = useState(/** @type {Set<number>} */ (new Set()));
  const [edits, setEdits] = useState(/** @type {Record<number, Record<string, any>>} */ ({}));
  const [editing, setEditing] = useState(/** @type {string | null} */ (null)); // "<index>:<field>"
  const [showArchived, setShowArchived] = useState(false);
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
      setEditing(null);
      setError(null);
    } catch (e) {
      setError(describe(e));
    }
  }

  useEffect(() => {
    void load();
  }, [id]);

  const head = (/** @type {number} */ n) => html`
    <header class="capture-head">
      <div>
        <h2>Create ${todos(n)}</h2>
        ${preview && html`<p class="capture-from">${from(preview, target, candidates)}</p>`}
      </div>
      <button type="button" class="icon-button" aria-label="Close" onClick=${close}><${Icon} name="x" /></button>
    </header>
  `;

  if (!preview) {
    return html`${head(0)}<div class="capture-wait">
      ${error ? html`<p class="error-text" role="alert">${error}</p>` : html`<p class="hint">Loading…</p>`}
    </div>`;
  }
  if (!preview.rows.length) {
    return html`${head(0)}<p class="capture-wait muted">This Note has no To-dos to create.</p>
      <div class="capture-actions"><button type="button" onClick=${close}>Close</button></div>`;
  }

  /** The errors a row still has: those on fields not edited since. @param {Row} row */
  const unfixedErrors = (row) => row.errors.filter((e) => !(e.field in (edits[row.index] ?? {})));
  const chosen = preview.rows.filter((r) => ticked.has(r.index));
  const blocked = chosen.filter((r) => unfixedErrors(r).length > 0).length;
  const names = preview.names;

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

  /**
   * One editable cell of a row.
   * @param {Row} row
   * @param {string} name
   * @param {boolean} on
   */
  function cell(row, name, on) {
    const rowEdits = edits[row.index] ?? {};
    const value = name in rowEdits ? rowEdits[name] : /** @type {any} */ (row)[name];
    const bad = on ? unfixedErrors(row).find((er) => er.field === name) : undefined;
    const key = `${row.index}:${name}`;
    const label = `${SPECS[name].label} of ${row.title || row.text}`;
    if (!bad && editing !== key) {
      return html`<button type="button" class="capture-cell ${name}" aria-label=${label}
        onClick=${() => setEditing(key)}>${shown(name, value, names, candidates)}</button>`;
    }
    /** @param {any} v */
    const set = (v) => {
      edit(row.index, name, v);
      if (name !== "due") setEditing(null);
    };
    const inputId = `capture-${row.index}-${name}`;
    return html`
      <${CellEditor} bad=${Boolean(bad)} focus=${!bad} onDone=${() => setEditing((k) => (k === key ? null : k))}>
        ${name === "owner" || name === "requester"
          ? html`<${PersonPicker} id=${inputId} label=${label} multiple=${false} value=${value} onChange=${set}
              people=${people} showArchived=${showArchived} onShowArchived=${setShowArchived}
              placeholder=${bad?.token ?? "—"} />`
          : html`<${FieldInput} spec=${{ ...SPECS[name], required: false }} value=${value} inputId=${inputId}
              ariaLabel=${label} candidates=${candidates} names=${names} onChange=${set} />`}
      <//>
    `;
  }

  return html`
    ${head(chosen.length)}
    <form onSubmit=${submit}>
      ${notice && html`<div class="banner info capture-notice" role="status">${notice}</div>`}
      <div class="capture-scroll">
        <table class="capture-table">
          <thead>
            <tr>
              <td class="capture-tick"></td>
              <th scope="col">To-do</th>
              <th scope="col" class="capture-party">Owner</th>
              <th scope="col" class="capture-party">Requester</th>
              <th scope="col" class="capture-due">Due</th>
              <th scope="col" class="capture-about">About</th>
            </tr>
          </thead>
          <tbody>
            ${preview.rows.map((row) => {
              const errors = unfixedErrors(row);
              const on = ticked.has(row.index);
              return html`
                <tr key=${row.index} class="capture-row ${on && errors.length ? "has-errors" : ""} ${on ? "" : "unticked"}">
                  <td class="capture-tick">
                    <input type="checkbox" class="checkbox pick" checked=${on} onChange=${() => toggle(row.index)}
                      aria-label="Create: ${row.title || row.text}" />
                  </td>
                  <td class="capture-todo" title="Line ${row.line}">
                    <span class="capture-title">${row.title || html`<span class="muted">(no title)</span>`}</span>
                    ${row.body.trim() && html` <span class="capture-body">body: ${row.body.trim()}</span>`}
                    ${on && errors.map((er) => html`<${ErrorLine} error=${er} />`)}
                  </td>
                  <td class="capture-party">${cell(row, "owner", on)}</td>
                  <td class="capture-party">${cell(row, "requester", on)}</td>
                  <td class="capture-due">${cell(row, "due", on)}</td>
                  <td class="capture-about">${cell(row, "about", on)}</td>
                </tr>
              `;
            })}
          </tbody>
        </table>
      </div>
      ${error && html`<p class="error-text capture-error" role="alert">${error}</p>`}
      <div class="capture-actions">
        <div class="capture-foot">
          ${blocked > 0 &&
          html`<p class="capture-blocked" role="status">Fix or untick ${blocked} row${blocked === 1 ? "" : "s"} to continue</p>`}
          <p>All or nothing: on confirm each item in the Note becomes <code>- [ ] [[todo-id]]</code></p>
        </div>
        <button type="button" onClick=${close}>Cancel</button>
        <button type="submit" class="primary" disabled=${busy || blocked > 0 || !chosen.length}>Create ${todos(chosen.length)}</button>
      </div>
    </form>
  `;
}

/**
 * Wraps a cell's editor: focuses it when opened by a click, and closes it when focus leaves
 * or on Escape.
 * @param {{bad: boolean, focus: boolean, onDone: () => void, children: any}} props
 */
function CellEditor({ bad, focus, onDone, children }) {
  const box = useRef(/** @type {HTMLSpanElement | null} */ (null));
  useEffect(() => {
    if (focus) /** @type {HTMLElement | null | undefined} */ (box.current?.querySelector("input, select"))?.focus();
  }, []);
  return html`<span class="capture-edit ${bad ? "bad" : ""}" ref=${box}
    onFocusOut=${(/** @type {FocusEvent} */ e) => {
      const next = /** @type {Node | null} */ (e.relatedTarget);
      if (!next || !box.current?.contains(next)) onDone();
    }}
    onKeyDown=${(/** @type {KeyboardEvent} */ e) => {
      if (e.key === "Escape" && !bad) {
        e.stopPropagation();
        onDone();
      }
    }}>${children}</span>`;
}

/**
 * The header's second line: the Note, the `source:` every To-do gets, and where `about`
 * came from when the Note names one Project or Deliverable.
 * @param {Preview} preview
 * @param {CaptureTarget} target
 * @param {import("./fields.js").Summary[]} candidates
 */
function from(preview, target, candidates) {
  const about = preview.rows[0]?.about;
  const type = about ? candidates.find((c) => sameId(c.id, about))?.type : undefined;
  return html`From <a href=${entityHref(target.id)} onClick=${close}>${target.title}</a> · each gets${" "}
    <code>source: ${preview.id}</code>${about && ` · about pre-filled from the Note's one ${type ? typeLabel(type) : "Project"}`}`;
}

/**
 * A cell's value: a person with their avatar ("Me" for Me), a due date, or an About.
 * @param {string} name
 * @param {any} value
 * @param {Record<string, string>} names
 * @param {import("./fields.js").Summary[]} candidates
 */
function shown(name, value, names, candidates) {
  if (value == null || value === "") return html`<span class="capture-none">—</span>`;
  const found = candidates.find((c) => sameId(c.id, value));
  const title = names[value] ?? found?.title ?? value;
  if (name === "due") return shortDate(value);
  if (name === "about") return html`<span class="capture-ref">${title}</span>`;
  const me = sameId(value, meId());
  return html`${found ? html`<${Avatar} person=${found} />` : html`<span class="avatar ${me ? "me" : ""}">${initials(title)}</span>`}${" "}<span
    class="capture-name ${me ? "me" : ""}">${me ? "Me" : title}</span>`;
}

/**
 * An error under a row's title, its bad token in a rust code span.
 * @param {{error: RowError}} props
 */
function ErrorLine({ error }) {
  const { token, message } = error;
  const at = token ? message.indexOf(token) : -1;
  const text =
    token && at >= 0
      ? html`${message.slice(0, at)}<code>${token}</code>${message.slice(at + token.length)}`
      : token
        ? html`<code>${token}</code>: ${message}`
        : message;
  const fix = FIX[error.field];
  return html`<span class="field-error capture-row-error">${text}${fix ? ` — ${fix}` : ""}</span>`;
}
