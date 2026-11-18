// @ts-check
// To-dos (SPEC §6.2, §6.3): rows, grouped lists, the quick-add box, and the To-dos page
// with its three-way switch. Ticking a row edits the To-do file (§6.1).

import { useEffect, useRef, useState } from "preact/hooks";
import { describe, request } from "./api.js";
import { writeField } from "./fields.js";
import { entityHref, personHref } from "./router.js";
import { html, meId, reloadTree, sameId, useView, viewVersion } from "./state.js";

/**
 * @typedef {import("./fields.js").Summary} Summary
 * @typedef {{label: string, person: string | null, todos: Summary[]}} TodoGroup
 * @typedef {{groups: TodoGroup[], names: Record<string, string>}} TodoList
 * @typedef {{token: string | null, message: string, candidates: string[]}} TokenError
 * @typedef {{title: string, owner: string | null, requester: string | null, due: string | null,
 *   errors: TokenError[], names: Record<string, string>}} Parsed
 */

const VIEWS = [
  { key: "mine", label: "Mine" },
  { key: "waiting-on-them", label: "Waiting on them" },
  { key: "waiting-on-me", label: "Waiting on me" },
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
 * One To-do: a tick box that edits its file, its title, the parties that aren't Me
 * (minus the one a group already names), and its due date.
 * @param {{todo: Summary, names: Record<string, string>, hide?: "owner" | "requester"}} props
 */
export function TodoRow({ todo, names, hide }) {
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const me = meId();
  const { owner, requester, status, due } = todo.fields;
  const finished = status === "done" || status === "cancelled";
  const name = (/** @type {string} */ id) => names[id] ?? id;

  async function toggle() {
    setError(await toggleTodo(todo));
  }

  return html`
    <li class="todo ${finished ? "finished" : ""}">
      <input type="checkbox" checked=${finished} aria-label="Done: ${todo.title}" onChange=${toggle} />
      <a href=${entityHref(todo.id)}>${todo.title}</a>
      ${status === "cancelled" && html`<span class="status status-cancelled">cancelled</span>`}
      ${hide !== "owner" && owner && !sameId(owner, me) &&
      html`<span class="party">→ <a href=${personHref(owner)}>${name(owner)}</a></span>`}
      ${hide !== "requester" && requester && !sameId(requester, me) &&
      html`<span class="party">from <a href=${personHref(requester)}>${name(requester)}</a></span>`}
      ${due && html`<span class="due ${!finished && isOverdue(due) ? "overdue" : ""}">due ${due}</span>`}
      ${todo.warnings.length > 0 && html`<span class="broken" title=${todo.warnings.map((w) => w.message).join("; ")}>!</span>`}
      ${error && html`<span class="field-error">${error}</span>`}
    </li>
  `;
}

/**
 * Tick or untick a To-do: a one-field write to its file (§6.1). Resolves to the write's
 * error message, or null.
 * @param {Summary} todo
 */
export async function toggleTodo(todo) {
  const { status } = todo.fields;
  const error = await writeField(todo, "status", status === "done" || status === "cancelled" ? "open" : "done");
  viewVersion.value += 1;
  return error;
}

/**
 * Groups of To-do rows. A group for a Person links to their Person View.
 * @param {{list: TodoList, hide?: "owner" | "requester", empty?: string, headings?: boolean}} props
 */
export function TodoGroups({ list, hide, empty = "Nothing here", headings = true }) {
  if (!list.groups.length) return html`<p class="muted">${empty}</p>`;
  return html`
    <div class="todo-groups">
      ${list.groups.map(
        (g) => html`
          <section class="todo-group">
            ${headings &&
            html`<h3>${g.person ? html`<a href=${personHref(g.person)}>${g.label}</a>` : g.label}
              <span class="muted">${g.todos.length}</span></h3>`}
            <ul class="todo-list">
              ${g.todos.map(
                (t) => html`<${TodoRow} key=${t.id} todo=${t} names=${list.names}
                  hide=${g.label === "Completed" ? undefined : hide} />`,
              )}
            </ul>
          </section>
        `,
      )}
    </div>
  `;
}

/**
 * The quick-add box (§6.3): a live server-side parse as you type, Enter creates.
 * @param {{label: string, defaults?: {owner?: string, requester?: string}, placeholder?: string}} props
 */
export function QuickAdd({ label, defaults = {}, placeholder }) {
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

  const name = (/** @type {string | null} */ id) => (id ? (parsed?.names[id] ?? id) : "—");
  return html`
    <form class="quick-add" onSubmit=${submit}>
      <input aria-label=${label} value=${text} disabled=${busy}
        placeholder=${placeholder ?? "New To-do: Title @owner from @requester due:YYYY-MM-DD"}
        onInput=${(/** @type {Event} */ e) => {
          setText(/** @type {HTMLInputElement} */ (e.currentTarget).value);
          setError(null);
        }} />
      ${parsed &&
      html`<div class="quick-add-preview" aria-live="polite">
        ${parsed.errors.length
          ? parsed.errors.map(
              (er) => html`<span class="field-error">${er.token ? `${er.token}: ` : ""}${er.message}</span>`,
            )
          : html`<span><strong>${parsed.title}</strong> · ${name(parsed.owner)} ← ${name(parsed.requester)}${
              parsed.due ? ` · due ${parsed.due}` : ""
            }</span><span class="muted">Enter to add</span>`}
      </div>`}
      ${error && html`<p class="error-text" role="alert">${error}</p>`}
    </form>
  `;
}

/** `#/todos/<view>`: the three-way switch, Show completed and quick-add (§6.2, §11.3). */
/** @param {{view: string}} props */
export function TodosPage({ view }) {
  const [showDone, setShowDone] = useState(false);
  const known = VIEWS.some((v) => v.key === view) ? view : "mine";
  const { data, error } = useView(
    /** @type {string} */ (`/api/views/todos?view=${known}&include_done=${showDone}`),
  );
  const list = /** @type {TodoList | null} */ (data);
  const hide = known === "waiting-on-them" ? "owner" : known === "waiting-on-me" ? "requester" : undefined;
  return html`
    <section class="page todos-page">
      <header class="page-head">
        <h1>To-dos</h1>
        <nav class="switch" aria-label="To-do views">
          ${VIEWS.map(
            (v) => html`<a href="#/todos/${v.key}" class=${v.key === known ? "active" : ""}
              aria-current=${v.key === known ? "page" : undefined}>${v.label}</a>`,
          )}
        </nav>
        <label class="check"><input type="checkbox" checked=${showDone}
          onChange=${(/** @type {Event} */ e) => setShowDone(/** @type {HTMLInputElement} */ (e.currentTarget).checked)} />
          Show completed</label>
      </header>
      <${QuickAdd} label="Quick-add To-do" />
      ${error
        ? html`<p class="error-text" role="alert">${describe(error)}</p>`
        : list
          ? html`<${TodoGroups} list=${list} hide=${hide} />`
          : html`<p class="hint">Loading…</p>`}
    </section>
  `;
}
