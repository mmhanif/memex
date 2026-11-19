// @ts-check
// To-dos (SPEC §6.2, §6.3): the quick-add box, and the To-dos page with its three-way
// switch and outline of groups, per "To-dos — Mine" in Paper. Ticking a row edits the
// To-do file (§6.1).

import { useEffect, useRef, useState } from "preact/hooks";
import { describe, request } from "./api.js";
import { daysBetween, shortDate } from "./dates.js";
import { isFinished, writeField } from "./fields.js";
import { Icon } from "./icons.js";
import { entityHref, personHref } from "./router.js";
import { html, meId, reloadTree, sameId, useView, viewVersion } from "./state.js";

/**
 * @typedef {import("./fields.js").Summary} Summary
 * @typedef {{label: string, person: string | null, todos: Summary[]}} TodoGroup
 * @typedef {"mine" | "waiting-on-them" | "waiting-on-me"} TodoViewName
 * @typedef {{groups: TodoGroup[], names: Record<string, string>,
 *   counts: Record<TodoViewName, number>, week_ends: string}} TodoList
 * @typedef {{token: string | null, message: string, candidates: string[]}} TokenError
 * @typedef {{title: string, owner: string | null, requester: string | null, due: string | null,
 *   errors: TokenError[], names: Record<string, string>}} Parsed
 */

/** The quick-add syntax, as the boxes hint it (§6.3). */
const SYNTAX = "@owner from @requester due:YYYY-MM-DD";

/** @type {{key: TodoViewName, label: string}[]} */
const VIEWS = [
  { key: "mine", label: "Mine" },
  { key: "waiting-on-them", label: "Waiting on them" },
  { key: "waiting-on-me", label: "Waiting on me" },
];

/** Mine's groups (§6.2), each with what it says when empty. */
const BY_DUE = [
  { label: "Overdue", empty: "Nothing overdue." },
  { label: "This week", empty: "Nothing due this week." },
  { label: "Later", empty: "Nothing due later." },
  { label: "No date", empty: "Nothing without a due date." },
];

/**
 * Whether an unfinished item due on `due` is late, by this machine's date (§4.2).
 * @param {string} due
 */
export function isOverdue(due) {
  return due < today();
}

/** Today on this machine, `YYYY-MM-DD`. */
export function today() {
  const d = new Date();
  const pad = (/** @type {number} */ n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/**
 * Tick or untick a To-do: a one-field write to its file (§6.1). Resolves to the write's
 * error message, or null.
 * @param {Summary} todo
 */
export async function toggleTodo(todo) {
  const { status } = todo.fields;
  const error = await writeField(todo, "status", isFinished(status) ? "open" : "done");
  viewVersion.value += 1;
  return error;
}

/**
 * The quick-add box (§6.3): a live server-side parse as you type, Enter creates. `boxed`
 * draws it as the dashed box with a + and the syntax hint under it; `page` as the To-dos
 * page's box, with an Enter key and the preview attached, saying which list it goes to.
 * @param {{label: string, defaults?: {owner?: string, requester?: string}, placeholder?: string,
 *   boxed?: boolean, page?: boolean}} props
 */
export function QuickAdd({ label, defaults = {}, placeholder, boxed = false, page = false }) {
  const [text, setText] = useState("");
  const [parsed, setParsed] = useState(/** @type {Parsed | null} */ (null));
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const [busy, setBusy] = useState(false);
  const latest = useRef(0);

  useEffect(() => {
    const n = ++latest.current;
    if (!text.trim()) {
      setParsed(null);
      return;
    }
    const timer = setTimeout(async () => {
      try {
        const next = await request("POST", "/api/parse/quick-add", { json: { text, defaults } });
        if (n === latest.current) setParsed(next);
      } catch (e) {
        if (n === latest.current) setError(describe(e));
      }
    }, 150);
    return () => clearTimeout(timer);
  }, [text]);

  /** @param {Event} e */
  async function submit(e) {
    e.preventDefault();
    if (!text.trim() || busy) return;
    setBusy(true);
    try {
      await request("POST", "/api/todos/quick-add", { json: { text, defaults } });
      setText("");
      setParsed(null);
      setError(null);
      viewVersion.value += 1;
      void reloadTree();
    } catch (err) {
      setError(describe(err));
    } finally {
      setBusy(false);
    }
  }

  const input = html`<input aria-label=${label} value=${text} disabled=${busy}
    placeholder=${placeholder ?? `New To-do: Title ${SYNTAX}`}
    onInput=${(/** @type {Event} */ e) => {
      setText(/** @type {HTMLInputElement} */ (e.currentTarget).value);
      setError(null);
    }} />`;
  const preview = parsed && html`<${Preview} parsed=${parsed} destination=${page} />`;
  return html`
    <form class="quick-add ${boxed ? "boxed" : ""} ${page ? "page-box" : ""}" onSubmit=${submit}>
      ${page
        ? html`<div class="quick-add-frame">
            <label class="quick-add-box"><${Icon} name="plus" />${input}<kbd aria-hidden="true">Enter</kbd></label>
            ${preview}
          </div>`
        : boxed
          ? html`<label class="quick-add-box"><${Icon} name="plus" />${input}</label>
            <p class="quick-add-hint"><code>${SYNTAX}</code></p>${preview}`
          : html`${input}${preview}`}
      ${error && html`<p class="error-text" role="alert">${error}</p>`}
    </form>
  `;
}

/**
 * The live parse: its errors, or each field ("owner Ben Carter", "from Me") and, on the
 * To-dos page, the list the To-do goes to.
 * @param {{parsed: Parsed, destination: boolean}} props
 */
function Preview({ parsed, destination }) {
  const me = meId();
  const name = (/** @type {string | null} */ id) =>
    !id ? "—" : sameId(id, me) ? "Me" : (parsed.names[id] ?? id);
  if (parsed.errors.length) {
    return html`<div class="quick-add-preview" aria-live="polite">
      ${parsed.errors.map((er) => html`<span class="field-error">${er.token ? `${er.token}: ` : ""}${er.message}</span>`)}
    </div>`;
  }
  return html`
    <div class="quick-add-preview" aria-live="polite">
      <span><span class="key">title</span> ${parsed.title}</span>
      <span><span class="key">owner</span> ${name(parsed.owner)}</span>
      <span><span class="key">from</span> ${name(parsed.requester)}</span>
      ${parsed.due && html`<span><span class="key">due</span> ${shortDate(parsed.due)}</span>`}
      <span class="goes-to">${destination ? `→ goes to ${goesTo(parsed, me, name)}` : "Enter to add"}</span>
    </div>
  `;
}

/**
 * Which of Me's lists a new To-do lands in (§6.2), or whose Person Views when neither
 * party is Me.
 * @param {Parsed} parsed
 * @param {string | null} me
 * @param {(id: string | null) => string} name
 */
function goesTo({ owner, requester }, me, name) {
  const mine = sameId(owner, me);
  const asked = sameId(requester, me);
  if (mine) return asked ? "Mine" : "Mine and Waiting on me";
  if (asked) return "Waiting on them";
  return `${name(owner)}'s and ${name(requester)}'s Person Views`;
}

/** A link to a Person, written as a Mention. @param {{id: string, names: Record<string, string>}} props */
export function PersonRef({ id, names }) {
  return html`<a href=${personHref(id)} title=${names[id]}>@${id}</a>`;
}

/**
 * One To-do as an outline row: bullet, tick box, title, the parties that aren't Me (minus
 * the one its group names), and its due date with any lateness.
 * @param {{todo: Summary, names: Record<string, string>, hide?: "owner" | "requester", now: string}} props
 */
function TodoBlock({ todo, names, hide, now }) {
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const me = meId();
  const { owner, requester, status, due } = todo.fields;
  const finished = isFinished(status);
  const late = typeof due === "string" && !finished ? daysBetween(due, now) : 0;
  return html`
    <div class="block-row todo-block ${finished ? "finished" : ""}">
      <span class="bullet"></span>
      <span class="check-slot">
        <input type="checkbox" class="checkbox" checked=${finished} aria-label="Done: ${todo.title}"
          onChange=${async () => setError(await toggleTodo(todo))} />
      </span>
      <span class="block-text">
        <a class="todo-title" href=${entityHref(todo.id)}>${todo.title}</a>
        ${status === "cancelled" && html` <span class="muted">· cancelled</span>`}
        ${hide !== "owner" && owner && !sameId(owner, me) &&
        html` <span class="muted">→</span> <${PersonRef} id=${owner} names=${names} />`}
        ${hide !== "requester" && requester && !sameId(requester, me) &&
        html` <span class="muted">from</span> <${PersonRef} id=${requester} names=${names} />`}
        ${typeof due === "string" &&
        html` <span class="due ${late > 0 ? "late" : ""}">due ${shortDate(due)}${
          late > 0 ? ` · ${late} day${late === 1 ? "" : "s"} late` : ""
        }</span>`}
        ${todo.warnings.length > 0 &&
        html` <span class="broken" title=${todo.warnings.map((w) => w.message).join("; ")}>!</span>`}
        ${error && html` <span class="field-error">${error}</span>`}
      </span>
    </div>
  `;
}

/**
 * A group as a heading block (a Person's links to their Person View), its To-dos hanging
 * off the guide.
 * @param {{label: string, person?: string | null, note?: string, empty?: string, children?: any}} props
 */
function GroupBlock({ label, person, note, empty, children }) {
  return html`
    <section class="block block-heading todo-group" aria-label=${label}>
      <div class="block-row">
        <span class="bullet"></span>
        <h2 class="block-text">${person ? html`<a href=${personHref(person)}>${label}</a>` : label}</h2>
        ${note && html`<span class="group-note">${note}</span>`}
      </div>
      <div class="block-children">
        ${children}
        ${empty && html`<p class="block-empty">${empty}</p>`}
      </div>
    </section>
  `;
}

/**
 * The page's outline: Mine always shows its four groups once anything is open, so "This
 * week" can say it's clear; the Waiting views show a group per Person.
 * @param {{list: TodoList, view: TodoViewName, now: string}} props
 */
function Groups({ list, view, now }) {
  const hide = view === "waiting-on-them" ? "owner" : view === "waiting-on-me" ? "requester" : undefined;
  const rows = (/** @type {TodoGroup} */ g, /** @type {typeof hide} */ h) =>
    g.todos.map((t) => html`<${TodoBlock} key=${t.id} todo=${t} names=${list.names} hide=${h} now=${now} />`);
  const completed = list.groups.find((g) => g.label === "Completed");
  const open = list.groups.filter((g) => g !== completed);
  return html`
    <div class="todo-groups">
      ${!open.length
        ? html`<p class="block-empty todos-empty">${view === "mine" ? "No open To-dos." : "Nobody here."}</p>`
        : view === "mine"
          ? BY_DUE.map(({ label, empty }) => {
              const g = open.find((x) => x.label === label);
              return html`<${GroupBlock} key=${label} label=${label} empty=${g ? undefined : empty}
                note=${label === "This week" ? `through ${shortDate(list.week_ends)}` : undefined}>
                ${g && rows(g, hide)}
              <//>`;
            })
          : open.map((g) => html`<${GroupBlock} key=${g.label} label=${g.label} person=${g.person}>${rows(g, hide)}<//>`)}
      ${completed && html`<${GroupBlock} label="Completed">${rows(completed, undefined)}<//>`}
    </div>
  `;
}

/**
 * "5 open · 1 overdue": the shown view in one line.
 * @param {TodoList} list
 * @param {TodoViewName} view
 * @param {string} now
 */
function summaryLine(list, view, now) {
  const open = list.counts[view];
  const overdue = list.groups
    .filter((g) => g.label !== "Completed")
    .flatMap((g) => g.todos)
    .filter((t) => typeof t.fields.due === "string" && t.fields.due < now).length;
  return open ? `${open} open${overdue ? ` · ${overdue} overdue` : ""}` : "Nothing open";
}

/** `#/todos/<view>`: the three-way switch, Show completed and quick-add (§6.2, §11.3). */
/** @param {{view: string}} props */
export function TodosPage({ view }) {
  const [showDone, setShowDone] = useState(false);
  const known = VIEWS.find((v) => v.key === view)?.key ?? "mine";
  const { data, error } = useView(
    /** @type {string} */ (`/api/views/todos?view=${known}&include_done=${showDone}`),
  );
  const list = /** @type {TodoList | null} */ (data);
  const now = today();
  return html`
    <section class="page todos-page">
      <header class="todos-head">
        <p class="eyebrow">${list ? summaryLine(list, known, now) : "\u00a0"}</p>
        <h1 class="title">To-dos</h1>
      </header>
      <div class="todos-controls">
        <nav class="segmented" aria-label="To-do views">
          ${VIEWS.map(
            (v) => html`<a href="#/todos/${v.key}" class=${v.key === known ? "active" : ""}
              aria-current=${v.key === known ? "page" : undefined}>${v.label} <span class="count">${list?.counts[v.key] ?? ""}</span></a>`,
          )}
        </nav>
        <label class="toggle"><input type="checkbox" role="switch" checked=${showDone}
          onChange=${(/** @type {Event} */ e) => setShowDone(/** @type {HTMLInputElement} */ (e.currentTarget).checked)} />
          Show completed</label>
      </div>
      <${QuickAdd} page label="Quick-add To-do" />
      ${error
        ? html`<p class="error-text" role="alert">${describe(error)}</p>`
        : list
          ? html`<${Groups} list=${list} view=${known} now=${now} />`
          : html`<p class="hint">Loading…</p>`}
    </section>
  `;
}
