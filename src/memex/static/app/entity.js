// @ts-check
// The Entity page (SPEC §11.5), also used for Notes: an eyebrow and title, a properties
// well edited in place (one hash-checked field write per edit), the body as outline blocks
// in read mode with ✎ Edit, and what links here.

import { useEffect, useMemo, useState } from "preact/hooks";
import { ApiError, describe, request } from "./api.js";
import { CaptureBar, openCapture } from "./capture.js";
import { lineSuffix } from "./banners.js";
import { dayDate, dueLabel, noteDay, shortDate } from "./dates.js";
import { BodyDoc } from "./doc.js";
import { FIELDS, FieldInput, initials, typeLabel, useCandidates, writeField } from "./fields.js";
import { RawText } from "./files.js";
import { Icon } from "./icons.js";
import { Actions, ArchivedBar } from "./lifecycle.js";
import { InlineRepairs } from "./repair.js";
import { renderMarkdown } from "./markdown.js";
import { openNew } from "./newform.js";
import { outlineHtml, toggleBlock } from "./outline.js";
import { entityHref, personHref } from "./router.js";
import { html, meId, openDoc, resolveMention, sameId, tree, viewVersion } from "./state.js";
import { isOverdue, today, toggleTodo } from "./todos.js";

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
 *   mentioned_in: (Summary & {context: string | null})[],
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
  const [editing, setEditing] = useState(false);
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
  useEffect(() => setEditing(false), [id]);

  useEffect(() => {
    // A Person's page is their Person View (§11.3).
    if (detail?.type === "person") window.location.replace(personHref(detail.id));
  }, [detail?.type, detail?.id]);

  if (loadError) return html`<section class="entity"><p class="error-text" role="alert">${loadError}</p></section>`;
  if (!detail || detail.id.toLowerCase() !== id.toLowerCase()) return html`<p class="hint">Loading…</p>`;
  const readOnly = detail.read_only || (tree.value?.workspace.read_only ?? false);
  const unconverted = detail.unconverted_todos ?? 0;

  function toggleEditing() {
    if (editing) closeBody(id);
    setEditing(!editing);
  }

  return html`
    <article class="entity entity-page">
      <header class="entity-head">
        <p class="eyebrow">${eyebrow(detail)}</p>
        <${Title} detail=${detail} readOnly=${readOnly} onSaved=${load} />
        <div class="entity-tools">
          ${!readOnly &&
          html`<button type="button" class="tool" aria-pressed=${editing} onClick=${toggleEditing}>
            <${Icon} name="pencil" /> ${editing ? "Done" : "Edit"}</button>`}
          <${Actions} detail=${detail} readOnly=${readOnly} openFile />
        </div>
      </header>
      <${ArchivedBar} detail=${detail} readOnly=${readOnly} onSaved=${load} />
      <${Warnings} detail=${detail} />
      <${Properties} detail=${detail} readOnly=${readOnly} onSaved=${load} />
      ${!readOnly && !editing && unconverted > 0 &&
      html`<${CaptureBar} count=${unconverted} onOpen=${() => void openCapture({ id, title: detail.title })} />`}
      <${BodySection} detail=${detail} readOnly=${readOnly} editing=${editing} />
      <${Related} detail=${detail} />
    </article>
  `;
}

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;

/**
 * The line over the title: the type, then a Note's date or a work item's parent.
 * @param {Detail} detail
 */
function eyebrow(detail) {
  const { date, theme, project } = detail.fields;
  const parent = detail.type === "project" ? theme : detail.type === "deliverable" ? project : null;
  const extra =
    detail.type === "note" && typeof date === "string" && ISO_DAY.test(date)
      ? dayDate(date)
      : typeof parent === "string"
        ? (detail.names[parent] ?? parent)
        : null;
  return extra ? `${typeLabel(detail.type)} · ${extra}` : typeLabel(detail.type);
}

/**
 * Validation warnings and Broken References, each in a bar; Broken References offer their
 * repairs inline, under the bar (§8.5, §11.5).
 * @param {{detail: Detail}} props
 */
export function Warnings({ detail }) {
  const repairable = detail.broken.filter((b) => b.status !== "wrong_type").map((b) => b.id);
  const count = detail.broken.length;
  return html`
    ${detail.warnings.map(
      (w) => html`<div class="validation-bar warn" role="status">
        <${Icon} name="triangle-alert" /><p>${w.message}${lineSuffix(w.line)}</p>
      </div>`,
    )}
    ${count > 0 &&
    html`<div class="validation-bar" role="status">
      <${Icon} name="triangle-alert" />
      <p><strong>${count} Broken Reference${count === 1 ? "" : "s"}.</strong>${" "}
        ${detail.broken.map(
          (b, i) => html`${i > 0 && "; "}<code>${b.field}</code> points to <code class="broken-id">${b.id}</code>, ${brokenLabel(b.status)}`,
        )}.</p>
    </div>
    <${InlineRepairs} ids=${repairable} />`}
  `;
}

/**
 * The body in read mode, or with ✎ Edit a raw textarea with auto-save. Given `editing`,
 * the page owns the ✎ Edit toggle and the body reads as outline blocks; without it, the
 * section has its own head with the toggle.
 * @param {{detail: Detail, readOnly: boolean, editing?: boolean}} props
 */
export function BodySection({ detail, readOnly, editing: controlled }) {
  const [own, setOwn] = useState(false);
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const headless = controlled !== undefined;
  const editing = controlled ?? own;
  const id = detail.id;
  useEffect(() => () => closeBody(id), [id]);
  const todos = new Map((detail.mentioned_todos ?? []).map((t) => [t.id.toLowerCase(), t]));
  const unconverted = detail.unconverted_todos ?? 0;
  const workspace = tree.value;
  const rendered = useMemo(() => {
    const out = renderMarkdown(detail.body, resolveMention, (todoId) => todoRow(todos.get(todoId.toLowerCase())));
    return headless ? outlineHtml(out) : out;
  }, [detail, workspace, headless]);

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
    <section class="entity-body" aria-label=${detail.type === "glossary-term" ? "Definition" : "Body"}>
      ${!headless &&
      html`<div class="section-head">
        <h2>${detail.type === "glossary-term" ? "Definition" : "Body"}</h2>
        ${!readOnly && !editing && unconverted > 0 &&
        html`<button type="button" onClick=${() => void openCapture({ id, title: detail.title })}>
          <${Icon} name="plus" /> Create ${unconverted} To-do${unconverted === 1 ? "" : "s"}</button>`}
        ${!readOnly &&
        html`<button type="button" aria-pressed=${editing} onClick=${() => {
          if (editing) closeBody(id);
          setOwn(!editing);
        }}><${Icon} name="pencil" /> ${editing ? "Done" : "Edit"}</button>`}
      </div>`}
      ${error && html`<p class="error-text" role="alert">${error}</p>`}
      ${editing
        ? html`<${BodyEditor} id=${id} />`
        : html`<div class="markdown ${headless ? "outline" : ""}" onChange=${tick} onClick=${headless ? toggleBlock : undefined}
            dangerouslySetInnerHTML=${{ __html: rendered }}></div>`}
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
  if (owner && !sameId(owner, meId())) meta.push({ class: "party", text: resolveMention(owner)?.title ?? owner });
  if (typeof due === "string" && ISO_DAY.test(due)) {
    meta.push({ class: !finished && isOverdue(due) ? "due late" : "due", text: `due ${shortDate(due)}` });
  } else if (due) {
    meta.push({ class: "due", text: `due ${due}` });
  }
  return { finished, title: todo.title, meta };
}

/** @param {Broken["status"]} status */
function brokenLabel(status) {
  return {
    missing: "which isn't in the Workspace",
    ambiguous: "which more than one file has as its Id",
    wrong_type: "which is the wrong type here",
  }[status];
}

/** Leave ✎ Edit: save what's pending, then let the document go. @param {string} id */
export function closeBody(id) {
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

/**
 * The properties well. `children` are extra read-only rows, after the fields.
 * @param {{detail: Detail, readOnly: boolean, onSaved: () => Promise<void>, children?: any}} props
 */
export function Properties({ detail, readOnly, onSaved, children }) {
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
    <section class="properties-block" aria-label="Properties">
      <span class="bullet" aria-hidden="true"></span>
      <div class="well properties">
        ${notice && html`<div class="banner info" role="status">${notice}</div>`}
        ${specs.map(
          (spec) => html`
            <div class="prop">
              <label class="prop-key" for="field-${spec.name}" title=${spec.label}>${spec.name}</label>
              <div class="prop-value">
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
              </div>
            </div>
          `,
        )}
        ${children}
        <div class="prop">
          <span class="prop-key">created</span>
          <span class="prop-value">${detail.fields.created ?? html`<span class="muted">—</span>`}</span>
        </div>
        ${error && html`<p class="error-text" role="alert">${error}</p>`}
      </div>
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

/**
 * What links here, each under a section header: children, To-dos and Notes about it, and
 * where it's Mentioned.
 * @param {{detail: Detail}} props
 */
function Related({ detail }) {
  const childType = detail.type === "theme" ? "project" : detail.type === "project" ? "deliverable" : null;
  const work = ["theme", "project", "deliverable"].includes(detail.type);
  return html`
    <div class="related-sections">
      ${childType && html`<${ChildSection} detail=${detail} type=${childType} />`}
      ${work && html`<${TodoSection} detail=${detail} />`}
      ${work && html`<${NoteSection} detail=${detail} />`}
      <${Section} title="Mentioned in" count=${detail.mentioned_in.length}>
        ${detail.mentioned_in.length
          ? detail.mentioned_in.map(
              (m) => html`<div class="ref-card" key=${m.id}>
                <a class="ref-title" href=${entityHref(m.id, m.type)}>${m.title}</a>
                ${m.context &&
                html`<div class="ref-context" dangerouslySetInnerHTML=${{ __html: renderMarkdown(m.context, resolveMention) }}></div>`}
              </div>`,
            )
          : html`<p class="section-empty">Nothing Mentions this yet</p>`}
      <//>
    </div>
  `;
}

/**
 * A titled section whose chevron folds it away.
 * @param {{title: string, count?: string | number, action?: any, children?: any}} props
 */
export function Section({ title, count, action, children }) {
  const [open, setOpen] = useState(true);
  return html`
    <section class="related-section" aria-label=${title}>
      <h2 class="section-header">
        <button type="button" class="fold" aria-expanded=${open} aria-label=${open ? `Hide ${title}` : `Show ${title}`}
          onClick=${() => setOpen(!open)}><${Icon} name=${open ? "chevron-down" : "chevron-right"} /></button>
        <span class="section-title">${title}${count !== undefined && html` <span class="count">${count}</span>`}</span>
        ${action}
      </h2>
      ${open && html`<div class="section-body">${children}</div>`}
    </section>
  `;
}

/** A Person's name, from the Workspace's files. @param {string} id */
function personName(id) {
  return resolveMention(id)?.title ?? id;
}

/**
 * A Theme's Projects or a Project's Deliverables: status, Lead, and due or lateness.
 * @param {{detail: Detail, type: "project" | "deliverable"}} props
 */
function ChildSection({ detail, type }) {
  const now = today();
  const parentField = type === "project" ? "theme" : "project";
  return html`
    <${Section} title=${type === "project" ? "Projects" : "Deliverables"} count=${detail.children.length}>
      ${detail.children.map((c) => {
        const { status, lead, due } = c.fields;
        const late = typeof due === "string" && due < now && !["done", "cancelled"].includes(status);
        return html`<div class="child-row" key=${c.id}>
          <span class="bullet" aria-hidden="true"></span>
          <a class="child-title" href=${entityHref(c.id, c.type)}>${c.title}</a>
          <span class="child-status ${status === "blocked" ? "blocked" : ""}">
            ${status && html`<span class="dot dot-${status}"></span>${statusLabel(status)}`}
          </span>
          <span class="child-lead">
            ${typeof lead === "string" &&
            html`<span class="avatar">${initials(personName(lead))}</span>${personName(lead).split(" ")[0]}`}
          </span>
          <span class="child-due ${late ? "late" : ""}">${typeof due === "string" && dueLabel(due, now)}</span>
        </div>`;
      })}
      <button type="button" class="add-row" onClick=${() => openNew(type, { [parentField]: detail.id })}>
        <${Icon} name="plus" /> ${typeLabel(type)}
      </button>
    <//>
  `;
}

/** @param {string} status */
function statusLabel(status) {
  const text = status.replace(/-/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/**
 * To-dos about this work item, ticked in place; finished ones behind "Show completed".
 * @param {{detail: Detail}} props
 */
function TodoSection({ detail }) {
  const [showDone, setShowDone] = useState(false);
  const finished = (/** @type {Summary} */ t) => ["done", "cancelled"].includes(t.fields.status);
  const open = detail.todos.filter((t) => !finished(t));
  const done = detail.todos.length - open.length;
  const shown = showDone ? detail.todos : open;
  return html`
    <${Section} title="To-dos about this" count="${open.length} open"
      action=${done > 0 &&
      html`<button type="button" class="link-button" aria-pressed=${showDone} onClick=${() => setShowDone(!showDone)}>
        ${showDone ? "Hide" : "Show"} completed (${done})</button>`}>
      ${shown.length === 0 && html`<p class="section-empty">No open To-dos</p>`}
      ${shown.map((t) => html`<${AboutTodo} key=${t.id} todo=${t} />`)}
    <//>
  `;
}

/** @param {{todo: Summary}} props */
function AboutTodo({ todo }) {
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const { status, owner, due } = todo.fields;
  const finished = status === "done" || status === "cancelled";
  const late = typeof due === "string" && !finished && isOverdue(due);
  return html`
    <div class="todo-line ${finished ? "finished" : ""}">
      <input type="checkbox" class="checkbox" checked=${finished} aria-label="Done: ${todo.title}"
        onChange=${async () => setError(await toggleTodo(todo))} />
      <span class="todo-text">
        <a href=${entityHref(todo.id)}>${todo.title}</a>
        ${typeof owner === "string" && !sameId(owner, meId()) &&
        html` <span class="muted">· owner</span> <a href=${personHref(owner)}>${personName(owner)}</a>`}
        ${error && html`<span class="field-error">${error}</span>`}
      </span>
      ${typeof due === "string"
        ? html`<span class="todo-due ${late ? "late" : ""}">${late ? "" : "due "}${dueLabel(due, today())}</span>`
        : html`<span class="todo-due none">no due date</span>`}
    </div>
  `;
}

/**
 * Notes with `about` naming this, newest first, with their day and Labels.
 * @param {{detail: Detail}} props
 */
function NoteSection({ detail }) {
  const now = today();
  const day = (/** @type {Summary} */ n) => {
    const d = n.fields.date ?? n.fields.created;
    return typeof d === "string" && ISO_DAY.test(d) ? d : "";
  };
  const notes = [...detail.notes].sort((a, b) => day(b).localeCompare(day(a)));
  return html`
    <${Section} title="Notes about this" count=${notes.length}
      action=${html`<button type="button" class="link-button" onClick=${() => openNew("note", { about: [detail.id] })}>
        <${Icon} name="plus" /> New Note about this</button>`}>
      ${notes.length === 0 && html`<p class="section-empty">No Notes about this yet</p>`}
      ${notes.map((n) => {
        const labels = Array.isArray(n.fields.labels) ? n.fields.labels : [];
        return html`<div class="note-line" key=${n.id}>
          <span class="note-day">${day(n) && noteDay(day(n), now)}</span>
          <a href=${entityHref(n.id, n.type)}>${n.title}</a>
          ${labels.length > 0 && html`<span class="muted">${labels.map((l) => `#${l}`).join(" ")}</span>`}
        </div>`;
      })}
    <//>
  `;
}
