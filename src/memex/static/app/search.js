// @ts-check
// Search (SPEC §9.7, §9.8): the `#/search?q=…` page, and the pieces the Ctrl-K palette
// shares with it (rows, snippets, opening a hit). Query parsing is server-only (§9.1):
// chips are drawn from the parsed filters the server returns, and editing a chip edits
// the query text, so typed tokens and chips are one filter state.

import { useEffect, useState } from "preact/hooks";
import { describe, request } from "./api.js";
import { typeLabel } from "./fields.js";
import { Icon } from "./icons.js";
import { entityHref, fileHref, navigate } from "./router.js";
import { html, viewVersion } from "./state.js";

/**
 * @typedef {{text: string, highlights: [number, number][]}} Snippet
 * @typedef {{line: number, title: string, url: string, note: string, labels: string[]}} BookmarkInfo
 * @typedef {{kind: "file" | "bookmark", id: string, type: string, title: string, path: string,
 *   status?: string | null, finished?: boolean, tier: number, context?: string,
 *   bookmark?: BookmarkInfo, snippets: Snippet[]}} SearchHit
 * @typedef {{kind: string, values: string[], token: string}} ParsedFilter
 * @typedef {{token: string, message: string, candidates: string[]}} TokenError
 * @typedef {{query: {text: string, filters: ParsedFilter[], errors: TokenError[]},
 *   total: number, counts: Record<string, number>, hits: SearchHit[]}} SearchResponse
 */

export const PAGE_SIZE = 50;
const BODY_TIER = 6;

/** @type {Record<string, string>} */
const TYPE_ICONS = {
  theme: "briefcase",
  project: "briefcase",
  deliverable: "briefcase",
  person: "users",
  todo: "square-check",
  "glossary-term": "book-a",
  note: "file-text",
  bookmark: "bookmark",
};

/** @param {string} type */
export function typeIcon(type) {
  return TYPE_ICONS[type] ?? "file-text";
}

/** @param {string} type */
export function typeName(type) {
  return type === "bookmark" ? "Bookmark" : typeLabel(type);
}

/**
 * @param {string} q
 * @param {{limit?: number, offset?: number, hideCompleted?: boolean}} [options]
 * @returns {Promise<SearchResponse>}
 */
export function fetchSearch(q, options = {}) {
  const params = new URLSearchParams({ q, limit: String(options.limit ?? PAGE_SIZE) });
  if (options.offset) params.set("offset", String(options.offset));
  if (options.hideCompleted) params.set("hide_completed", "true");
  return request("GET", `/api/search?${params}`);
}

/** @param {SearchHit} hit */
export function isTextHit(hit) {
  return hit.kind === "bookmark" || hit.tier === BODY_TIER;
}

/** @param {string} q */
export function searchHref(q) {
  return `#/search?${new URLSearchParams({ q })}`;
}

/** @param {SearchHit} hit */
export function hitHref(hit) {
  return hit.type === "note" ? fileHref(hit.path) : entityHref(hit.id, hit.type);
}

/**
 * Open a hit (§9.8). Bookmarks open their URL in a new tab and are never fetched; with
 * `toLine` they jump to their line on the Bookmarks page instead. A body hit scrolls to
 * its first match and highlights it briefly.
 * @param {SearchHit} hit
 * @param {{newTab?: boolean, toLine?: boolean}} [how]
 */
export function openHit(hit, how = {}) {
  if (hit.bookmark) {
    if (how.toLine) navigate(`#/bookmarks?line=${hit.bookmark.line}`);
    else if (/^https?:\/\//i.test(hit.bookmark.url)) {
      window.open(hit.bookmark.url, "_blank", "noopener,noreferrer");
    }
    return;
  }
  const href = hitHref(hit);
  if (how.newTab) {
    window.open(`${window.location.pathname}${href}`, "_blank", "noopener");
    return;
  }
  const first = hit.snippets[0];
  if (hit.tier === BODY_TIER && first?.highlights.length) {
    const [start, end] = first.highlights[0];
    flashText(first.text.slice(start, end));
  }
  navigate(href);
}

const FLASH_MS = 2500;
const FLASH_WAIT_MS = 3000;

/**
 * Scroll the view to the first place `text` shows and highlight it briefly, once the
 * view has rendered. Uses the CSS Custom Highlight API, so the page's DOM is untouched.
 * @param {string} text
 */
function flashText(text) {
  const wanted = text.toLowerCase();
  const started = Date.now();
  const timer = setInterval(() => {
    const range = findText(wanted);
    if (!range && Date.now() - started < FLASH_WAIT_MS) return;
    clearInterval(timer);
    if (!range || !("highlights" in CSS)) return;
    range.startContainer.parentElement?.scrollIntoView({ block: "center" });
    CSS.highlights.set("search-hit", new Highlight(range));
    setTimeout(() => CSS.highlights.delete("search-hit"), FLASH_MS);
  }, 100);
}

/** @param {string} wanted lowercased */
function findText(wanted) {
  const root = document.querySelector(".view .markdown, .view textarea, .view");
  if (!root) return null;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const at = (node.textContent ?? "").toLowerCase().indexOf(wanted);
    if (at >= 0) {
      const range = document.createRange();
      range.setStart(node, at);
      range.setEnd(node, at + wanted.length);
      return range;
    }
  }
  return null;
}

/** @param {{snippet: Snippet}} props */
export function SnippetText({ snippet }) {
  /** @type {any[]} */
  const parts = [];
  let at = 0;
  for (const [start, end] of snippet.highlights) {
    if (start < at) continue;
    parts.push(snippet.text.slice(at, start), html`<mark>${snippet.text.slice(start, end)}</mark>`);
    at = end;
  }
  parts.push(snippet.text.slice(at));
  return html`<span class="snippet">${parts}</span>`;
}

/** The muted line under a hit's title. @param {SearchHit} hit */
export function hitContext(hit) {
  if (hit.bookmark) return hit.bookmark.url;
  return hit.context ?? "";
}

/**
 * Drop one whitespace-separated token from a query.
 * @param {string} q
 * @param {string} token
 */
export function withoutToken(q, token) {
  const words = q.split(/\s+/).filter(Boolean);
  const at = words.indexOf(token);
  if (at >= 0) words.splice(at, 1);
  return words.join(" ");
}

/**
 * Add a token to a query, unless it is there already.
 * @param {string} q
 * @param {string} token
 */
export function withToken(q, token) {
  const words = q.split(/\s+/).filter(Boolean);
  return words.includes(token) ? words.join(" ") : [...words, token].join(" ");
}

const TYPE_CHOICES = ["theme", "project", "deliverable", "person", "todo", "glossary-term", "note", "bookmark"];
const STATUS_CHOICES = ["not-started", "active", "on-hold", "blocked", "done", "cancelled", "open", "archived"];
const DUE_CHOICES = ["overdue", "today", "this-week", "none"];

/**
 * `#/search?q=…&hide=1`: query box, chips, per-type counts, and the ranked list.
 * @param {{query: URLSearchParams}} props
 */
export function SearchPage({ query }) {
  const q = query.get("q") ?? "";
  const hideCompleted = query.get("hide") === "1";
  const [text, setText] = useState(q);
  const [data, setData] = useState(/** @type {SearchResponse | null} */ (null));
  const [hits, setHits] = useState(/** @type {SearchHit[]} */ ([]));
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const version = viewVersion.value;

  useEffect(() => setText(q), [q]);
  useEffect(() => {
    let live = true;
    fetchSearch(q, { hideCompleted, limit: Math.max(PAGE_SIZE, hits.length) })
      .then((next) => {
        if (!live) return;
        setData(next);
        setHits(next.hits);
        setError(null);
      })
      .catch((e) => live && setError(describe(e)));
    return () => {
      live = false;
    };
  }, [q, hideCompleted, version]);

  /** @param {string} nextQ @param {boolean} [nextHide] */
  function go(nextQ, nextHide = hideCompleted) {
    const params = new URLSearchParams({ q: nextQ });
    if (nextHide) params.set("hide", "1");
    setHits([]);
    navigate(`#/search?${params}`);
  }

  async function more() {
    try {
      const next = await fetchSearch(q, { hideCompleted, offset: hits.length });
      setHits([...hits, ...next.hits]);
    } catch (e) {
      setError(describe(e));
    }
  }

  const filters = data?.query.filters ?? [];
  const has = (/** @type {string} */ kind) => filters.some((f) => f.kind === kind);
  /** @param {string} prefix @param {string} value */
  const add = (prefix, value) => value && go(withToken(q, `${prefix}${value}`));

  return html`
    <section class="page search-page">
      <form class="search-box" onSubmit=${(/** @type {Event} */ e) => {
        e.preventDefault();
        go(text.trim());
      }}>
        <label class="search">
          <${Icon} name="search" />
          <input type="search" aria-label="Search query" value=${text}
            onInput=${(/** @type {Event} */ e) => setText(/** @type {HTMLInputElement} */ (e.currentTarget).value)} />
        </label>
        <button type="submit">Search</button>
      </form>
      <div class="search-chips">
        ${filters.map(
          (f) => html`<span class="chip filter-chip">${f.token}
            <button type="button" class="icon-button" aria-label=${`Remove ${f.token}`}
              onClick=${() => go(withoutToken(q, f.token))}><${Icon} name="x" /></button>
          </span>`,
        )}
        <${AddChip} label="Type" choices=${TYPE_CHOICES} names=${typeName} onPick=${(/** @type {string} */ v) => add("type:", v)} />
        <${AddChip} label="Status" choices=${STATUS_CHOICES} onPick=${(/** @type {string} */ v) => add("status:", v)} />
        <${AddText} label="Person" prefix="@" onAdd=${(/** @type {string} */ v) => add("@", v)} />
        <${AddText} label="Label" prefix="label:" onAdd=${(/** @type {string} */ v) => add("label:", v)} />
        <${AddChip} label="Due" choices=${DUE_CHOICES} onPick=${(/** @type {string} */ v) => add("due:", v)} />
        <label class="check" title=${has("status") ? "A status filter overrides this" : ""}>
          <input type="checkbox" checked=${hideCompleted} disabled=${has("status")}
            onChange=${() => go(q, !hideCompleted)} />
          Hide completed
        </label>
      </div>
      ${data?.query.errors.map((er) => html`<p class="error-text" role="alert">${er.token}: ${er.message}</p>`)}
      ${error && html`<p class="error-text" role="alert">${error}</p>`}
      ${data && data.total > 0 &&
      html`<div class="type-counts" aria-label="Results by type">
        ${Object.entries(data.counts).map(
          ([type, n]) => html`<button type="button" class="chip"
            aria-pressed=${q.split(/\s+/).includes(`type:${type}`)}
            onClick=${() => {
              const token = `type:${type}`;
              go(q.split(/\s+/).includes(token) ? withoutToken(q, token) : withToken(q, token));
            }}>${typeName(type)} <span class="muted">${n}</span></button>`,
        )}
      </div>`}
      ${data && !q.trim() && html`<p class="hint">Type words to find, or filters like type:project @alice due:this-week.</p>`}
      ${data && q.trim() && data.total === 0 && !data.query.errors.length && html`<p class="hint">Nothing matches.</p>`}
      <ul class="search-results">
        ${hits.map((hit) => html`<${ResultRow} key=${`${hit.path}:${hit.bookmark?.line ?? 0}`} hit=${hit} />`)}
      </ul>
      ${data && hits.length < data.total &&
      html`<button type="button" onClick=${() => void more()}>Show more</button>`}
    </section>
  `;
}

/** @param {{hit: SearchHit}} props */
function ResultRow({ hit }) {
  const finished = hit.finished || hit.status === "archived";
  const href = hit.bookmark ? hit.bookmark.url : hitHref(hit);
  const external = Boolean(hit.bookmark);
  return html`
    <li class="result ${finished ? "finished" : ""}">
      <div class="result-head">
        <${Icon} name=${typeIcon(hit.type)} />
        <a href=${href} target=${external ? "_blank" : undefined} rel=${external ? "noopener noreferrer" : undefined}
          onClick=${(/** @type {MouseEvent} */ e) => {
            if (e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0) return;
            e.preventDefault();
            openHit(hit);
          }}>${hit.title}</a>
        <span class="type-badge">${typeName(hit.type)}</span>
        ${hit.status && html`<span class="status status-${hit.status}">${hit.status}</span>`}
      </div>
      ${hitContext(hit) && html`<div class="muted result-context">${hitContext(hit)}</div>`}
      ${hit.snippets.slice(0, 2).map((s) => html`<div class="result-snippet"><${SnippetText} snippet=${s} /></div>`)}
    </li>
  `;
}

/**
 * A chip that adds a filter value picked from a list.
 * @param {{label: string, choices: string[], names?: (v: string) => string, onPick: (v: string) => void}} props
 */
function AddChip({ label, choices, names, onPick }) {
  return html`
    <select class="add-chip" aria-label=${`Add ${label} filter`}
      onChange=${(/** @type {Event} */ e) => {
        const select = /** @type {HTMLSelectElement} */ (e.currentTarget);
        onPick(select.value);
        select.value = "";
      }}>
      <option value="">${label}…</option>
      ${choices.map((c) => html`<option value=${c}>${names ? names(c) : c}</option>`)}
    </select>
  `;
}

/**
 * A chip that adds a typed filter value: a Person (`@…`) or a Label.
 * @param {{label: string, prefix: string, onAdd: (v: string) => void}} props
 */
function AddText({ label, prefix, onAdd }) {
  const [value, setValue] = useState("");
  return html`
    <form class="add-chip" onSubmit=${(/** @type {Event} */ e) => {
      e.preventDefault();
      onAdd(value.trim().replace(/\s+/g, "-"));
      setValue("");
    }}>
      <input aria-label=${`Add ${label} filter`} placeholder=${`${prefix}${label.toLowerCase()}`} size="10"
        value=${value} onInput=${(/** @type {Event} */ e) => setValue(/** @type {HTMLInputElement} */ (e.currentTarget).value)} />
    </form>
  `;
}
