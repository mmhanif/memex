// @ts-check
// The Ctrl-K palette (SPEC §9.6). Server search supplies Entities, Notes and text hits;
// views and commands are a static list matched here in the browser and merged in.
// `>` limits it to commands; `+` turns it into To-do quick-add.

import { signal } from "@preact/signals";
import { useEffect, useRef, useState } from "preact/hooks";
import { describe, request } from "./api.js";
import { TYPES } from "./fields.js";
import { Icon } from "./icons.js";
import { fetchTemplates, openNew } from "./newform.js";
import { recents } from "./recent.js";
import { navigate } from "./router.js";
import {
  fetchSearch,
  hitContext,
  isTextHit,
  MatchedText,
  openHit,
  openInNewTab,
  searchHref,
  SnippetText,
  typeIcon,
  typeName,
} from "./search.js";
import { html, reloadTree, tree, viewVersion } from "./state.js";

/**
 * @typedef {import("./search.js").SearchHit} SearchHit
 * @typedef {{label: string, icon: string, context?: string, run: (how: {newTab?: boolean}) => void,
 *   href?: string}} Command
 * @typedef {{key: string, section: string, icon: string, title: string, context?: string,
 *   snippet?: import("./search.js").Snippet, finished?: boolean, kind?: "text" | "see-all",
 *   run: (how: {newTab?: boolean, toLine?: boolean, stay?: boolean}) => void | Promise<void>}} Row
 */

const DEBOUNCE_MS = 100;
const GO_TO_MAX = 8;
const COMMANDS_MAX = 4;
const IN_TEXT_MAX = 5;
const SEARCH_LIMIT = 200; // the API's maximum

/** Whether the palette is open, and the text it opened with. */
export const palette = signal(/** @type {{initial: string} | null} */ (null));

export function openPalette(initial = "") {
  palette.value = { initial };
}

document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === "k") {
    e.preventDefault();
    openPalette();
  }
});

// Views and commands: static, matched in the browser.

/** @type {[string, string, string][]} label, route, icon */
const VIEWS = [
  ["Home", "#/home", "house"],
  ["Portfolio: board", "#/portfolio/board", "briefcase"],
  ["Portfolio: outline", "#/portfolio/outline", "briefcase"],
  ["People", "#/people", "users"],
  ["To-dos: Mine", "#/todos/mine", "square-check"],
  ["To-dos: Waiting on them", "#/todos/waiting-on-them", "square-check"],
  ["To-dos: Waiting on me", "#/todos/waiting-on-me", "square-check"],
  ["Glossary", "#/glossary", "book-a"],
  ["Bookmarks", "#/bookmarks", "bookmark"],
  ["Files", "#/files", "folder"],
  ["Search", "#/search", "search"],
  ["Settings", "#/settings", "settings"],
  ["Broken references", "#/broken", "circle-alert"],
  ["Trash", "#/trash", "trash-2"],
];

/** @type {Command[]} */
const VIEW_COMMANDS = VIEWS.map(([label, href, icon]) => ({
  label,
  icon,
  href,
  run: (how) => go(href, how.newTab),
}));

/**
 * @param {string} href
 * @param {boolean} [newTab]
 */
function go(href, newTab) {
  if (newTab) openInNewTab(href);
  else navigate(href);
}

/** @type {Command} */
const QUIT = {
  label: "Quit Memex",
  icon: "x",
  run: () => {
    void request("POST", "/api/quit").then(() => {
      document.body.textContent = "Memex has quit. You can close this tab.";
    });
  },
};

/** "New <Type>" for each type; "New <Type>: <Template>" for each other Template (§7.4). */
async function newCommands() {
  /** @type {Command[]} */
  const commands = TYPES.map((t) => ({ label: `New ${t.label}`, icon: "plus", run: () => openNew(t.key) }));
  const lists = await Promise.all(TYPES.map((t) => fetchTemplates(t.key).catch(() => null)));
  TYPES.forEach((t, i) => {
    const list = lists[i];
    for (const tpl of list?.usable ?? []) {
      if (tpl.key === list?.fallback.key) continue;
      commands.push({
        label: `New ${t.label}: ${tpl.display_name}`,
        icon: "plus",
        run: () => openNew(t.key, undefined, tpl.name),
      });
    }
  });
  return commands;
}

/** @param {string} text */
function fold(text) {
  return text.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

/**
 * How well `query` matches `label`: lower is better, null is no match. Every word must
 * match: as a prefix of a word, else as a fuzzy subsequence.
 * @param {string} query
 * @param {string} label
 */
export function commandScore(query, label) {
  const l = fold(label);
  const q = fold(query).trim();
  if (!q) return 0;
  if (l === q) return 0;
  if (l.startsWith(q)) return 1;
  let worst = 2;
  for (const word of q.split(/\s+/)) {
    if (l.split(/[^a-z0-9]+/).some((w) => w.startsWith(word))) continue;
    if (!isSubsequence(word, l)) return null;
    worst = 3;
  }
  return worst;
}

/** @param {string} q @param {string} text */
function isSubsequence(q, text) {
  let at = 0;
  for (const c of q) {
    at = text.indexOf(c, at) + 1;
    if (at === 0) return false;
  }
  return true;
}

/**
 * @param {Command[]} commands
 * @param {string} q
 */
function matchCommands(commands, q) {
  return commands
    .map((c) => ({ c, score: commandScore(q, c.label) }))
    .filter((x) => x.score !== null)
    .sort((a, b) => /** @type {number} */ (a.score) - /** @type {number} */ (b.score))
    .map((x) => x.c);
}

/** @param {Command} c @param {string} section */
function commandRow(c, section) {
  return /** @type {Row} */ ({ key: `${section}:${c.label}`, section, icon: c.icon, title: c.label, run: c.run });
}

/**
 * A server hit as a palette row. Go to rows say the type and context ("Deliverable · Data
 * Migration"); In text rows say where the text is (a Note's folder, else the type) and
 * show the snippet under the title.
 * @param {SearchHit} hit @param {string} section
 */
function hitRow(hit, section) {
  const text = section === "In text";
  const context = hitContext(hit);
  const where = hit.bookmark ? context : hit.type === "note" ? (context ? `${context}/` : "") : typeName(hit.type);
  return /** @type {Row} */ ({
    key: `hit:${hit.path}:${hit.bookmark?.line ?? 0}`,
    section,
    icon: typeIcon(hit.type),
    title: hit.title,
    context: text ? where : [typeName(hit.type), context].filter(Boolean).join(" · "),
    snippet: text ? hit.snippets[0] : undefined,
    finished: hit.finished,
    kind: text ? "text" : undefined,
    run: (how) => openHit(hit, how),
  });
}

export function Palette() {
  const open = palette.value;
  if (!open) return null;
  return html`<${PaletteBox} initial=${open.initial} />`;
}

/** @param {{initial: string}} props */
function PaletteBox({ initial }) {
  const [text, setText] = useState(initial);
  const [hits, setHits] = useState(/** @type {SearchHit[] | null} */ (null));
  const [errors, setErrors] = useState(/** @type {string[]} */ ([]));
  const [preview, setPreview] = useState(/** @type {any} */ (null));
  const [commands, setCommands] = useState(/** @type {Command[]} */ ([]));
  const [selected, setSelected] = useState(0);
  const [problem, setProblem] = useState(/** @type {string | null} */ (null));
  const input = useRef(/** @type {HTMLInputElement | null} */ (null));
  const latest = useRef(0);

  useEffect(() => {
    input.current?.focus();
    void newCommands().then(setCommands);
  }, []);

  const mode = text.startsWith(">") ? "commands" : text.startsWith("+") ? "quick-add" : "search";
  const q = mode === "search" ? text.trim() : text.slice(1).trim();
  const version = viewVersion.value; // a change on disk refreshes the results

  useEffect(() => {
    const n = ++latest.current;
    if (mode === "commands" || !q) {
      setHits(null);
      setErrors([]);
      setPreview(null);
      return;
    }
    const timer = setTimeout(async () => {
      try {
        if (mode === "quick-add") {
          const next = await request("POST", "/api/parse/quick-add", { json: { text: q } });
          if (n === latest.current) setPreview(next);
        } else {
          // Wide enough that body hits still reach "In text" behind many name hits.
          const next = await fetchSearch(q, { limit: SEARCH_LIMIT });
          if (n !== latest.current) return;
          setHits(next.hits);
          setErrors(next.query.errors.map((e) => `${e.token}: ${e.message}`));
        }
        setProblem(null);
      } catch (e) {
        if (n === latest.current) setProblem(describe(e));
      }
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [text, version]);
  useEffect(() => setSelected(0), [text]);

  const close = () => {
    palette.value = null;
  };

  /** @param {boolean} stay */
  async function addTodo(stay) {
    try {
      await request("POST", "/api/todos/quick-add", { json: { text: q } });
      viewVersion.value += 1;
      void reloadTree();
      if (stay) setText("+");
      else close();
    } catch (e) {
      setProblem(describe(e));
    }
  }

  const allCommands = [...commands, ...VIEW_COMMANDS, QUIT];
  /** @type {Row[]} */
  let rows = [];
  if (mode === "quick-add") {
    if (preview && !preview.errors.length) {
      const name = (/** @type {string | null} */ id) => (id ? (preview.names[id] ?? id) : "—");
      rows = [{
        key: "quick-add",
        section: "New To-do",
        icon: "square-check",
        title: preview.title,
        context: `${name(preview.owner)} ← ${name(preview.requester)}${preview.due ? ` · due ${preview.due}` : ""}`,
        run: (how) => addTodo(Boolean(how.stay)),
      }];
    }
  } else if (mode === "commands") {
    rows = matchCommands(allCommands, q).map((c) => commandRow(c, "Commands"));
  } else if (!q) {
    rows = [
      ...recents.value.map((r) => /** @type {Row} */ ({
        key: `recent:${r.href}`,
        section: "Recent",
        icon: r.icon,
        title: r.title,
        run: (how) => go(r.href, how.newTab),
      })),
      ...allCommands.slice(0, COMMANDS_MAX).map((c) => commandRow(c, "Commands")),
    ];
  } else {
    const found = hits ?? [];
    const views = matchCommands(VIEW_COMMANDS, q).slice(0, 3).map((c) => commandRow(c, "Go to"));
    const goTo = [...found.filter((h) => !isTextHit(h)).map((h) => hitRow(h, "Go to")), ...views]
      .slice(0, GO_TO_MAX);
    rows = [
      ...goTo,
      // Every named view is a command too (§9.6); skip ones Go to already shows.
      ...matchCommands(allCommands, q)
        .filter((c) => !c.href || !goTo.some((r) => r.key === `Go to:${c.label}`))
        .slice(0, COMMANDS_MAX)
        .map((c) => commandRow(c, "Commands")),
      ...found.filter(isTextHit).slice(0, IN_TEXT_MAX).map((h) => hitRow(h, "In text")),
      {
        key: "see-all",
        section: "",
        kind: "see-all",
        icon: "arrow-right",
        title: `See all results for '${q}'`,
        run: (how) => go(searchHref(q), how.newTab),
      },
    ];
  }

  const at = Math.min(selected, Math.max(rows.length - 1, 0));

  /** @param {Row} row @param {{newTab?: boolean, toLine?: boolean, stay?: boolean}} how */
  function choose(row, how) {
    if (!how.stay) close();
    void row.run(how);
  }

  /** @param {KeyboardEvent} e */
  function onKeyDown(e) {
    if (e.key === "Escape") {
      e.preventDefault();
      close();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelected((at + 1) % Math.max(rows.length, 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelected((at - 1 + rows.length) % Math.max(rows.length, 1));
    } else if (e.key === "Enter" && rows[at]) {
      e.preventDefault();
      const stay = mode === "quick-add" && e.shiftKey;
      choose(rows[at], { newTab: e.ctrlKey || e.metaKey, toLine: e.altKey, stay });
    }
  }

  let lastSection = "";
  return html`
    <div class="dialog-backdrop palette-backdrop" onClick=${(/** @type {Event} */ e) => e.target === e.currentTarget && close()}>
      <div class="palette" role="dialog" aria-label="Command palette" onKeyDown=${onKeyDown}>
        <div class="palette-input">
          <${Icon} name="search" />
          <input ref=${input} aria-label="Search or run a command" role="combobox"
            aria-expanded="true" aria-controls="palette-rows" aria-activedescendant=${rows[at] ? `palette-row-${at}` : undefined}
            placeholder="Search, > for commands, + to add a To-do" value=${text}
            onInput=${(/** @type {Event} */ e) => setText(/** @type {HTMLInputElement} */ (e.currentTarget).value)} />
          <kbd>Esc</kbd>
        </div>
        ${problem && html`<p class="error-text" role="alert">${problem}</p>`}
        ${errors.map((m) => html`<p class="error-text" role="alert">${m}</p>`)}
        ${mode === "quick-add" && preview?.errors.map(
          (/** @type {{token: string | null, message: string}} */ er) =>
            html`<p class="field-error">${er.token ? `${er.token}: ` : ""}${er.message}</p>`,
        )}
        <ul id="palette-rows" class="palette-rows" role="listbox" aria-label="Results">
          ${rows.map((row, i) => {
            const heading = row.section && row.section !== lastSection ? row.section : null;
            lastSection = row.section;
            const title = mode === "search" && row.kind !== "see-all"
              ? html`<${MatchedText} text=${row.title} q=${q} />`
              : row.title;
            return html`
              ${heading && html`<li class="palette-section" role="presentation">${heading}</li>`}
              <li id=${`palette-row-${i}`} role="option" aria-selected=${i === at}
                class="palette-row ${row.kind ?? ""} ${i === at ? "selected" : ""} ${row.finished ? "finished" : ""}"
                onMouseMove=${() => i !== at && setSelected(i)}
                onClick=${(/** @type {MouseEvent} */ e) => choose(row, { newTab: e.ctrlKey || e.metaKey })}>
                <span class="palette-icon"><${Icon} name=${row.icon} /></span>
                ${row.kind === "text"
                  ? html`<span class="palette-text">
                      <span class="palette-title">${title}${row.context && html` <span class="palette-where">· ${row.context}</span>`}</span>
                      ${row.snippet && html`<span class="palette-snippet"><${SnippetText} snippet=${row.snippet} /></span>`}
                    </span>`
                  : html`<span class="palette-title">${title}</span>
                      <span class="palette-context">${row.context ?? ""}</span>`}
                ${i === at && html`<span class="palette-enter" aria-hidden="true">↵</span>`}
              </li>
            `;
          })}
        </ul>
        <div class="palette-keys" aria-hidden="true">
          <span><b>↑↓</b> move</span>
          <span><b>↵</b> open</span>
          <span><b>Ctrl ↵</b> new tab</span>
          <span class="grow"></span>
          <span><b class="mono">${">"}</b> commands</span>
          <span><b class="mono">+</b> add To-do</span>
        </div>
      </div>
    </div>
  `;
}
