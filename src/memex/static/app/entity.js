// @ts-check
// The Entity page (SPEC §11.5), also used for Notes: a properties card edited in place
// (one hash-checked field write per edit), the body in read mode with ✎ Edit, and what
// links here.

import { useEffect, useState } from "preact/hooks";
import { ApiError, describe, request } from "./api.js";
import { openCapture } from "./capture.js";
import { lineSuffix } from "./banners.js";
import { BodyDoc } from "./doc.js";
import { FIELDS, FieldInput, typeLabel, useCandidates, writeField } from "./fields.js";
import { RawText } from "./files.js";
import { Icon } from "./icons.js";
import { Actions, ArchivedBar } from "./lifecycle.js";
import { InlineRepairs } from "./repair.js";
import { renderMarkdown } from "./markdown.js";
import { openNew } from "./newform.js";
import { entityHref, fileHref, personHref } from "./router.js";
import { html, meId, openDoc, resolveMention, sameId, tree, viewVersion } from "./state.js";

/**
 * @typedef {import("./fields.js").Summary} Summary
 * @typedef {{field: string, id: string, status: "missing" | "ambiguous" | "wrong_type"}} Broken
 * @typedef {Summary & {
 *   body: string,
 *   read_only: boolean,
 *   broken: Broken[],
 *   names: Record<string, string>,
 *   children: Summary[],
 *   todos: Summary[],
 *   notes: Summary[],
 *   mentioned_in: Summary[],
 *   mentioned_todos: Summary[],
 *   unconverted_todos?: number,
 *   archivable: boolean,
 *   loose_ends: import("./lifecycle.js").LooseEnd[],
 * }} Detail
 */

/** @param {{id: string}} props */
export function EntityPage({ id }) {
  const [detail, setDetail] = useState(/** @type {Detail | null} */ (null));
  const [loadError, setLoadError] = useState(/** @type {string | null} */ (null));
  const version = viewVersion.value;

  async function load() {
    try {
      setDetail(await request("GET", `/api/entities/${encodeURIComponent(id)}`));
      setLoadError(null);
    } catch (e) {
      setLoadError(describe(e));
    }
  }

  useEffect(() => {
    void load();
  }, [id, version]);

  useEffect(() => {
    // A Person's page is their Person View (§11.3).
    if (detail?.type === "person") window.location.replace(personHref(detail.id));
  }, [detail?.type, detail?.id]);

  if (loadError) return html`<section class="entity"><p class="error-text" role="alert">${loadError}</p></section>`;
  if (!detail || detail.id.toLowerCase() !== id.toLowerCase()) return html`<p class="hint">Loading…</p>`;
  const readOnly = detail.read_only || (tree.value?.workspace.read_only ?? false);

  return html`
    <article class="entity">
      <header class="entity-head">
        <span class="type-badge">${typeLabel(detail.type)}</span>
        <${Title} detail=${detail} readOnly=${readOnly} onSaved=${load} />
        <a class="button" href=${fileHref(detail.path)} title="Open the raw file"><${Icon} name="file-text" /> Open file</a>
        <${Actions} detail=${detail} readOnly=${readOnly} />
      </header>
      <${ArchivedBar} detail=${detail} readOnly=${readOnly} onSaved=${load} />
      <${Warnings} detail=${detail} />
      <${Properties} detail=${detail} readOnly=${readOnly} onSaved=${load} />
      <${BodySection} detail=${detail} readOnly=${readOnly} />
      <${Related} detail=${detail} />
    </article>
  `;
}

/**
 * Validation warnings and Broken References, each in a bar; Broken References offer their
 * repairs inline (§8.5, §11.5).
 * @param {{detail: Detail}} props
 */
export function Warnings({ detail }) {
  const repairable = detail.broken.filter((b) => b.status !== "wrong_type").map((b) => b.id);
  return html`
    ${detail.warnings.map(
      (w) => html`<div class="banner warn" role="status">${w.message}${lineSuffix(w.line)}</div>`,
    )}
    ${detail.broken.length > 0 &&
    html`<div class="banner warn" role="status">
      <span>Broken references: ${detail.broken.map((b) => `${b.field} → ${b.id} (${brokenLabel(b.status)})`).join("; ")}</span>
    </div>
    <${InlineRepairs} ids=${repairable} />`}
  `;
}

/**
 * The body in read mode, or with ✎ Edit a raw textarea with auto-save.
 * @param {{detail: Detail, readOnly: boolean}} props
 */
export function BodySection({ detail, readOnly }) {
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const id = detail.id;
  useEffect(() => () => closeBody(id), [id]);
  const todos = new Map((detail.mentioned_todos ?? []).map((t) => [t.id.toLowerCase(), t]));
  const unconverted = detail.unconverted_todos ?? 0;

  /** Ticking a live To-do row edits the To-do file, never the Note (§6.4). @param {Event} e */
  async function tick(e) {
    const box = /** @type {HTMLInputElement} */ (e.target);
    const todo = todos.get(box.dataset.todo?.toLowerCase() ?? "");
    if (!todo) return;
    const finished = ["done", "cancelled"].includes(todo.fields.status);
    const failed = await writeField(todo, "status", finished ? "open" : "done");
    if (failed) box.checked = finished; // the same HTML won't be re-applied, so put it back
    setError(failed);
    viewVersion.value += 1;
  }

  return html`
    <section class="entity-body">
      <div class="section-head">
        <h2>${detail.type === "glossary-term" ? "Definition" : "Body"}</h2>
        ${!readOnly && !editing && unconverted > 0 &&
        html`<button type="button" onClick=${() => void openCapture({ id, title: detail.title })}>
          <${Icon} name="plus" /> Create ${unconverted} To-do${unconverted === 1 ? "" : "s"}</button>`}
        ${!readOnly &&
        html`<button type="button" aria-pressed=${editing} onClick=${() => {
          if (editing) closeBody(id);
          setEditing(!editing);
        }}><${Icon} name="pencil" /> ${editing ? "Done" : "Edit"}</button>`}
      </div>
      ${error && html`<p class="error-text" role="alert">${error}</p>`}
      ${editing ? html`<${BodyEditor} id=${id} />` : html`<div class="markdown" onChange=${tick}
        dangerouslySetInnerHTML=${{ __html: renderMarkdown(detail.body, resolveMention, (todoId) => todoRow(todos.get(todoId.toLowerCase()))) }}></div>`}
    </section>
  `;
}

/**
 * What a converted task item shows for its To-do: real status, title, Owner and due.
 * @param {Summary | undefined} todo
 */
function todoRow(todo) {
  if (!todo) return null;
  const { status, owner, due } = todo.fields;
  const finished = status === "done" || status === "cancelled";
  const meta = [];
  if (status === "cancelled") meta.push({ class: "status status-cancelled", text: "cancelled" });
  if (owner && !sameId(owner, meId())) meta.push({ class: "party", text: `→ ${resolveMention(owner)?.title ?? owner}` });
  if (due) meta.push({ class: "due", text: `due ${due}` });
  return { finished, title: todo.title, meta };
}

/** @param {Broken["status"]} status */
function brokenLabel(status) {
  return { missing: "nothing has that Id", ambiguous: "ambiguous", wrong_type: "wrong type" }[status];
}

/** Leave ✎ Edit: save what's pending, then let the document go. @param {string} id */
function closeBody(id) {
  const doc = openDoc.value;
  if (doc instanceof BodyDoc && doc.id === id) {
    void doc.flush().then(() => doc.dispose());
    openDoc.value = null;
  }
}

/**
 * One hash-checked field write. A conflict reloads the page's data and says so.
 * @param {Detail} detail
 * @param {Record<string, any>} set
 * @param {string[]} unset
 */
async function patch(detail, set, unset) {
  await request("PATCH", `/api/entities/${encodeURIComponent(detail.id)}`, {
    json: { set, unset },
    ifMatch: detail.hash,
  });
}

/** @param {{detail: Detail, readOnly: boolean, onSaved: () => Promise<void>}} props */
export function Title({ detail, readOnly, onSaved }) {
  const current = typeof detail.fields.title === "string" ? detail.fields.title : "";
  const [draft, setDraft] = useState(current || detail.title);
  const [error, setError] = useState(/** @type {string | null} */ (null));
  useEffect(() => setDraft(current || detail.title), [current, detail.title]);

  async function commit() {
    const next = draft.trim();
    if (next === (current || detail.title) || (!next && detail.type !== "note")) {
      setDraft(current || detail.title);
      return;
    }
    try {
      if (next) await patch(detail, { title: next }, []);
      else await patch(detail, {}, ["title"]);
      setError(null);
    } catch (e) {
      setError(describe(e));
    }
    await onSaved();
  }

  return html`
    <h1 class="entity-title">
      <input aria-label="Title" value=${draft} disabled=${readOnly}
        onInput=${(/** @type {Event} */ e) => setDraft(/** @type {HTMLInputElement} */ (e.currentTarget).value)}
        onBlur=${commit}
        onKeyDown=${(/** @type {KeyboardEvent} */ e) => e.key === "Enter" && /** @type {HTMLInputElement} */ (e.currentTarget).blur()} />
      ${error && html`<span class="field-error">${error}</span>`}
    </h1>
  `;
}

/** @param {{detail: Detail, readOnly: boolean, onSaved: () => Promise<void>}} props */
export function Properties({ detail, readOnly, onSaved }) {
  const candidates = useCandidates();
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const [notice, setNotice] = useState(/** @type {string | null} */ (null));
  const specs = FIELDS[detail.type] ?? [];
  const broken = new Set(detail.broken.map((b) => b.id));

  /** @param {string} name @param {any} value */
  async function save(name, value) {
    try {
      await patch(detail, value == null ? {} : { [name]: value }, value == null ? [name] : []);
      setError(null);
      setNotice(null);
    } catch (e) {
      if (e instanceof ApiError && e.code === "conflict") {
        setNotice("This changed on disk, so the card was reloaded. Make the change again.");
      } else {
        setError(describe(e));
      }
    }
    await onSaved();
  }

  return html`
    <section class="properties" aria-label="Properties">
      ${notice && html`<div class="banner info" role="status">${notice}</div>`}
      <dl>
        ${specs.map(
          (spec) => html`
            <dt><label for="field-${spec.name}">${spec.label}</label></dt>
            <dd>
              <${FieldInput}
                spec=${spec}
                value=${detail.fields[spec.name]}
                onChange=${(/** @type {any} */ v) => void save(spec.name, v)}
                candidates=${candidates}
                names=${detail.names}
                broken=${broken}
                disabled=${readOnly}
                placeholder=${spec.name === "requester" ? "—" : undefined}
              />
            </dd>
          `,
        )}
        <dt>Created</dt>
        <dd>${detail.fields.created ?? html`<span class="muted">—</span>`}</dd>
      </dl>
      ${error && html`<p class="error-text" role="alert">${error}</p>`}
    </section>
  `;
}

/**
 * ✎ Edit: the body as a raw textarea with auto-save (§5.7). Tab indents; Enter continues lists.
 * @param {{id: string}} props
 */
function BodyEditor({ id }) {
  const [error, setError] = useState(/** @type {string | null} */ (null));
  useEffect(() => {
    let cancelled = false;
    BodyDoc.open(id).then(
      (doc) => {
        if (cancelled) return doc.dispose();
        openDoc.value?.dispose();
        openDoc.value = doc;
      },
      (/** @type {unknown} */ e) => !cancelled && setError(describe(e)),
    );
    return () => {
      cancelled = true;
    };
  }, [id]);

  const doc = openDoc.value;
  if (error) return html`<p class="error-text" role="alert">${error}</p>`;
  if (!(doc instanceof BodyDoc) || doc.id !== id) return html`<p class="hint">Opening…</p>`;
  return html`
    <div class="body-editor">
      <${RawText} doc=${doc} label="Body text" onKeyDown=${listHelpers} />
    </div>
  `;
}

const LIST_ITEM = /^(\s*)([-*+]|\d+[.)])(\s+\[[ xX]\])?\s+/;

/**
 * Tab indents, Shift-Tab outdents, Enter continues a list (and ends it on an empty item).
 * Edits go through `execCommand` so the browser's undo keeps working, and `input` fires.
 * @param {KeyboardEvent} e
 */
function listHelpers(e) {
  const area = /** @type {HTMLTextAreaElement} */ (e.currentTarget);
  const { selectionStart: start, selectionEnd: end, value } = area;
  const lineStart = value.lastIndexOf("\n", start - 1) + 1;
  if (e.key === "Tab" && !e.ctrlKey && !e.altKey && !e.metaKey) {
    e.preventDefault();
    if (e.shiftKey) {
      const strip = value.slice(lineStart, lineStart + 2).match(/^ {1,2}/)?.[0].length ?? 0;
      if (!strip) return;
      area.setSelectionRange(lineStart, lineStart + strip);
      document.execCommand("delete");
      area.setSelectionRange(Math.max(lineStart, start - strip), Math.max(lineStart, end - strip));
    } else {
      document.execCommand("insertText", false, "  ");
    }
    return;
  }
  if (e.key !== "Enter" || e.shiftKey || start !== end) return;
  const line = value.slice(lineStart, start);
  const match = LIST_ITEM.exec(line);
  if (!match) return;
  e.preventDefault();
  if (match[0].length === line.length) {
    // An empty item ends the list.
    area.setSelectionRange(lineStart, start);
    document.execCommand("delete");
    return;
  }
  const number = /^\d+/.exec(match[2]);
  const marker = number ? `${Number(number[0]) + 1}${match[2].slice(number[0].length)}` : match[2];
  document.execCommand("insertText", false, `\n${match[1]}${marker}${match[3] ? " [ ]" : ""} `);
}

/** @param {{detail: Detail}} props */
function Related({ detail }) {
  const childLabel = detail.type === "theme" ? "Projects" : detail.type === "project" ? "Deliverables" : null;
  return html`
    <section class="related">
      ${childLabel &&
      html`<${LinkList} title=${childLabel} items=${detail.children}>
        ${detail.type === "project" &&
        html`<button type="button" onClick=${() => openNew("deliverable", { project: detail.id })}>
          <${Icon} name="plus" /> Deliverable
        </button>`}
        ${detail.type === "theme" &&
        html`<button type="button" onClick=${() => openNew("project", { theme: detail.id })}>
          <${Icon} name="plus" /> Project
        </button>`}
      <//>`}
      ${["theme", "project", "deliverable"].includes(detail.type) &&
      html`<${LinkList} title="To-dos" items=${detail.todos} />
        <${LinkList} title="Notes" items=${detail.notes} />`}
      <${LinkList} title="Mentioned in" items=${detail.mentioned_in} />
    </section>
  `;
}

/** @param {{title: string, items: Summary[], children?: any}} props */
export function LinkList({ title, items, children }) {
  return html`
    <div class="link-list">
      <div class="section-head"><h2>${title}</h2>${children}</div>
      ${items.length
        ? html`<ul>
            ${items.map(
              (item) => html`<li>
                <a href=${entityHref(item.id, item.type)}>${item.title}</a>
                ${item.fields.status && html`<span class="status status-${item.fields.status}">${item.fields.status}</span>`}
                ${item.fields.due && html`<span class="muted">due ${item.fields.due}</span>`}
              </li>`,
            )}
          </ul>`
        : html`<p class="muted">None yet</p>`}
    </div>
  `;
}
