// @ts-check
// Entity lifecycle in the UI (SPEC §5.5, §8.3, §8.4): the Entity page's Actions menu,
// the "Archived on" bar, and the Rename id, Archive and Delete dialogs. Every change
// previews first (the impact preview), then applies against the preview's hashes.

import { signal } from "@preact/signals";
import { useEffect, useState } from "preact/hooks";
import { ApiError, describe, request } from "./api.js";
import { openCapture } from "./capture.js";
import { typeLabel, useCandidates } from "./fields.js";
import { Icon } from "./icons.js";
import { entityHref, fileHref, navigate } from "./router.js";
import { html, meId, reloadTree, sameId, viewVersion } from "./state.js";

/**
 * @typedef {import("./fields.js").Summary} Summary
 * @typedef {{label: string, items: Summary[]}} LooseEnd
 * @typedef {{id: string, title: string, type: string, path: string, hash?: string,
 *   fields?: Record<string, any>, archivable?: boolean, loose_ends?: LooseEnd[],
 *   unconverted_todos?: number}} Target
 * @typedef {{path: string, title: string, hash: string, fields: string[], count: number}} Edit
 * @typedef {{path: string, title: string, field: string}} Blocker
 * @typedef {{summary: string, references: number, edits: Edit[], blocked: Blocker[]}} Impact
 * @typedef {{impact: Impact, hashes: Record<string, string>, applied: boolean,
 *   skipped: {path: string, code: string, message: string}[], id: string | null,
 *   path: string | null, trash: string | null}} Outcome
 * @typedef {{kind: "rename" | "archive" | "delete", target: Target, after?: string}} LifecycleRequest
 */

/** The open lifecycle dialog, if any. */
export const lifecycleDialog = signal(/** @type {LifecycleRequest | null} */ (null));

/**
 * @param {LifecycleRequest["kind"]} kind
 * @param {Target} target
 * @param {string} [after] where to go once a delete is done (default: Home)
 */
export function openLifecycle(kind, target, after) {
  lifecycleDialog.value = { kind, target, after };
}

function close() {
  lifecycleDialog.value = null;
}

/**
 * Archive or Unarchive on the server, which sets today's date (§8.3).
 * @param {Target} target
 * @param {boolean} archived
 */
function setArchived(target, archived) {
  return request("POST", `${entityUrl(target)}/archive`, { json: { archived }, ifMatch: target.hash });
}

/** @param {Target} target */
function entityUrl(target) {
  return `/api/entities/${encodeURIComponent(target.id)}`;
}

/**
 * The Entity page's Actions menu (§11.5): Rename id, Archive/Unarchive, Delete.
 * @param {{detail: Target, readOnly: boolean}} props
 */
export function Actions({ detail, readOnly }) {
  const [open, setOpen] = useState(false);
  const isMe = sameId(meId() ?? "", detail.id);
  /** @param {LifecycleRequest["kind"]} kind */
  const pick = (kind) => {
    setOpen(false);
    openLifecycle(kind, detail);
  };
  if (readOnly) return null;
  return html`
    <div class="new-menu actions-menu">
      <button type="button" aria-haspopup="menu" aria-expanded=${open} onClick=${() => setOpen(!open)}>
        Actions <${Icon} name="chevron-down" />
      </button>
      ${open &&
      html`<ul class="menu" role="menu" onKeyDown=${(/** @type {KeyboardEvent} */ e) => e.key === "Escape" && setOpen(false)}>
        ${(detail.unconverted_todos ?? 0) > 0 &&
        html`<li><button type="button" role="menuitem" onClick=${() => {
          setOpen(false);
          void openCapture({ id: detail.id, title: detail.title });
        }}><${Icon} name="plus" /> Create ${detail.unconverted_todos} To-do${detail.unconverted_todos === 1 ? "" : "s"}…</button></li>`}
        <li><button type="button" role="menuitem" onClick=${() => pick("rename")}><${Icon} name="pencil" /> Rename id…</button></li>
        ${detail.archivable &&
        !detail.fields?.archived &&
        html`<li><button type="button" role="menuitem" disabled=${isMe} title=${isMe ? "Me can't be archived" : undefined}
          onClick=${() => pick("archive")}>Archive…</button></li>`}
        <li><button type="button" role="menuitem" disabled=${isMe}
          title=${isMe ? "Me can't be deleted: change Me in Settings first" : undefined}
          onClick=${() => pick("delete")}><${Icon} name="trash-2" /> Delete…</button></li>
      </ul>`}
    </div>
  `;
}

/**
 * "Archived on <date>" with **Unarchive** (§8.3).
 * @param {{detail: Target, readOnly: boolean, onSaved: () => Promise<void> | void}} props
 */
export function ArchivedBar({ detail, readOnly, onSaved }) {
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const archived = detail.fields?.archived;
  if (!archived) return null;
  async function unarchive() {
    try {
      await setArchived(detail, false);
      setError(null);
    } catch (e) {
      setError(describe(e));
    }
    await onSaved();
  }
  return html`
    <div class="banner info" role="status">
      <span>Archived on ${archived}${error ? ` · ${error}` : ""}</span>
      ${!readOnly && html`<button type="button" onClick=${unarchive}>Unarchive</button>`}
    </div>
  `;
}

/** The open lifecycle dialog, mounted once in the shell. */
export function LifecycleDialog() {
  const open = lifecycleDialog.value;
  if (!open) return null;
  const key = `${open.kind}:${open.target.id}`;
  const body =
    open.kind === "rename"
      ? html`<${RenameForm} key=${key} target=${open.target} />`
      : open.kind === "archive"
        ? html`<${ArchiveForm} key=${key} target=${open.target} />`
        : html`<${DeleteForm} key=${key} target=${open.target} after=${open.after ?? "#/home"} />`;
  return html`
    <div class="dialog-backdrop" onClick=${(/** @type {Event} */ e) => e.target === e.currentTarget && close()}>
      <div class="dialog" role="dialog" aria-label=${dialogTitle(open)}
        onKeyDown=${(/** @type {KeyboardEvent} */ e) => e.key === "Escape" && close()}>
        <h2>${dialogTitle(open)}</h2>
        ${body}
      </div>
    </div>
  `;
}

/** @param {LifecycleRequest} open */
function dialogTitle(open) {
  const verb = { rename: "Rename id of", archive: "Archive", delete: "Delete" }[open.kind];
  return `${verb} ${open.target.title}`;
}

/** The impact preview: which files change, and how. @param {{impact: Impact}} props */
export function ImpactList({ impact }) {
  if (!impact.edits.length) return html`<p class="muted">Nothing else refers to it.</p>`;
  return html`
    <p class="impact-summary">This ${impact.summary}:</p>
    <ul class="impact">
      ${impact.edits.map(
        (e) => html`<li><a href=${fileHref(e.path)} onClick=${close}>${e.title}</a>
          <span class="muted">${e.fields.join(", ")}${e.count > 1 ? ` (${e.count})` : ""}</span></li>`,
      )}
    </ul>
  `;
}

/** @param {{skipped: Outcome["skipped"]}} props */
function SkippedList({ skipped }) {
  return html`
    <div class="banner warn" role="alert">
      <span>${skipped.length} file${skipped.length === 1 ? " was" : "s were"} skipped; the rest were updated:
        ${skipped.map((s) => `${s.path} (${s.message})`).join("; ")}</span>
    </div>
  `;
}

/** Rename id (§5.5): preview the impact, then apply. @param {{target: Target}} props */
function RenameForm({ target }) {
  const [newId, setNewId] = useState(target.id);
  const [preview, setPreview] = useState(/** @type {Outcome | null} */ (null));
  const [done, setDone] = useState(/** @type {Outcome | null} */ (null));
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const [busy, setBusy] = useState(false);

  /** @param {Event} e */
  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    try {
      if (!preview) {
        setPreview(await request("POST", `${entityUrl(target)}/rename`, { json: { new_id: newId.trim() } }));
      } else {
        const outcome = /** @type {Outcome} */ (
          await request("POST", `${entityUrl(target)}/rename`, {
            json: { new_id: newId.trim(), dry_run: false, hashes: preview.hashes },
          })
        );
        await reloadTree();
        viewVersion.value += 1;
        if (outcome.skipped.length) setDone(outcome);
        else close();
        navigate(entityHref(outcome.id ?? newId, target.type));
      }
      setError(null);
    } catch (err) {
      setError(describe(err));
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return html`
      <${SkippedList} skipped=${done.skipped} />
      <div class="dialog-actions"><button type="button" class="primary" onClick=${close}>Close</button></div>
    `;
  }
  return html`
    <form onSubmit=${submit}>
      <div class="form-grid">
        <label for="rename-id">New Id</label>
        <input id="rename-id" value=${newId} autofocus spellcheck=${false}
          onInput=${(/** @type {Event} */ e) => {
            setNewId(/** @type {HTMLInputElement} */ (e.currentTarget).value);
            setPreview(null);
          }} />
      </div>
      <p class="hint">Lowercase letters, digits and -. Every reference and [[Mention]] is rewritten.</p>
      ${preview && html`<${ImpactList} impact=${preview.impact} />`}
      ${error && html`<p class="error-text" role="alert">${error}</p>`}
      <div class="dialog-actions">
        <button type="button" onClick=${close}>Cancel</button>
        <button type="submit" class="primary" disabled=${busy || !newId.trim() || newId.trim() === target.id}>
          ${preview ? "Rename" : "Preview"}
        </button>
      </div>
    </form>
  `;
}

/** Archive (§8.3): the loose-ends checklist, a warning only. @param {{target: Target}} props */
function ArchiveForm({ target }) {
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const ends = target.loose_ends ?? [];

  async function archive() {
    try {
      await setArchived(target, true);
      viewVersion.value += 1;
      close();
    } catch (e) {
      setError(e instanceof ApiError && e.code === "conflict" ? "It changed on disk: close and try again" : describe(e));
    }
  }

  return html`
    <p>It stays where it is, and every reference to it stays valid, with an <em>archived</em> badge.
      It's hidden from pickers${target.type === "person" ? " and the People page" : " and the Portfolio filter"}.</p>
    ${ends.length > 0 &&
    html`<div class="banner warn" role="status"><span>Loose ends:</span></div>
      <ul class="loose-ends">
        ${ends.map(
          (end) => html`<li>
            <details><summary>${end.label}</summary>
              <ul>${end.items.map((i) => html`<li><a href=${entityHref(i.id, i.type)} onClick=${close}>${i.title}</a></li>`)}</ul>
            </details>
          </li>`,
        )}
      </ul>`}
    ${error && html`<p class="error-text" role="alert">${error}</p>`}
    <div class="dialog-actions">
      <button type="button" onClick=${close}>Cancel</button>
      <button type="button" class="primary" onClick=${archive}>Archive</button>
    </div>
  `;
}

/**
 * Delete to trash (§8.4). With no incoming references: one confirmation. Otherwise the
 * impact preview and a choice: **Replace with…** or **Remove references**.
 * @param {{target: Target, after: string}} props
 */
function DeleteForm({ target, after }) {
  const candidates = useCandidates();
  const [preview, setPreview] = useState(/** @type {Outcome | null} */ (null));
  const [mode, setMode] = useState(/** @type {"replace" | "remove"} */ ("replace"));
  const [replacement, setReplacement] = useState("");
  const [done, setDone] = useState(/** @type {Outcome | null} */ (null));
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    request("POST", `${entityUrl(target)}/delete`, { json: { mode: "remove" } }).then(
      (/** @type {Outcome} */ p) => {
        setPreview(p);
        if (p.impact.blocked.length) setMode("replace");
      },
      (/** @type {unknown} */ e) => setError(describe(e)),
    );
  }, [target.id]);

  if (!preview) {
    return html`${error ? html`<p class="error-text" role="alert">${error}</p>` : html`<p class="hint">Checking references…</p>`}
      <div class="dialog-actions"><button type="button" onClick=${close}>Cancel</button></div>`;
  }
  const referred = preview.impact.edits.length > 0 || preview.impact.blocked.length > 0;
  const others = candidates.filter((c) => c.type === target.type && !sameId(c.id, target.id));

  async function remove() {
    setBusy(true);
    try {
      const chosen = referred ? mode : "plain";
      const outcome = /** @type {Outcome} */ (
        await request("POST", `${entityUrl(target)}/delete`, {
          json: { mode: chosen, replacement: chosen === "replace" ? replacement : null, dry_run: false, hashes: preview?.hashes ?? {} },
        })
      );
      await reloadTree();
      viewVersion.value += 1;
      if (outcome.skipped.length) {
        setDone(outcome);
      } else {
        close();
        navigate(after);
      }
      setError(null);
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return html`
      <${SkippedList} skipped=${done.skipped} />
      <p>${target.title} was not deleted, so nothing is left pointing at nothing. Try again once those files are free.</p>
      <div class="dialog-actions"><button type="button" class="primary" onClick=${close}>Close</button></div>
    `;
  }
  return html`
    ${!referred && html`<p>Move ${target.title} (${target.path}) to the trash?</p>`}
    ${referred &&
    html`
      <${ImpactList} impact=${preview.impact} />
      <fieldset class="delete-choice">
        <legend>Before deleting</legend>
        <label class="check"><input type="radio" name="delete-mode" checked=${mode === "replace"}
          onChange=${() => setMode("replace")} /> Replace with…</label>
        <select aria-label="Replacement" value=${replacement} disabled=${mode !== "replace"}
          onChange=${(/** @type {Event} */ e) => setReplacement(/** @type {HTMLSelectElement} */ (e.currentTarget).value)}>
          <option value="">Pick a ${typeLabel(target.type)}</option>
          ${others.map((c) => html`<option value=${c.id}>${c.title}${c.fields.archived ? " (archived)" : ""}</option>`)}
        </select>
        <br />
        <label class="check"><input type="radio" name="delete-mode" checked=${mode === "remove"}
          disabled=${preview.impact.blocked.length > 0}
          onChange=${() => setMode("remove")} /> Remove references</label>
        ${preview.impact.blocked.length > 0 &&
        html`<p class="hint">Remove is blocked by required references:
          ${preview.impact.blocked.map((b) => `${b.title} (${b.field})`).join(", ")}.</p>`}
      </fieldset>
    `}
    ${error && html`<p class="error-text" role="alert">${error}</p>`}
    <div class="dialog-actions">
      <button type="button" onClick=${close}>Cancel</button>
      <button type="button" class="primary danger"
        disabled=${busy || (referred && mode === "replace" && !replacement)} onClick=${remove}>
        Delete
      </button>
    </div>
  `;
}
