// @ts-check
// Search (SPEC §9.7, §9.8): the `#/search?q=…` page, and the pieces the Ctrl-K palette
// shares with it (rows, snippets, opening a hit). Query parsing is server-only (§9.1):
// chips are drawn from the parsed filters the server returns, and editing a chip edits
// the query text, so typed tokens and chips are one filter state.

import { useEffect, useState } from "preact/hooks";
import { describe, request } from "./api.js";
import { dayMonth, shortDate } from "./dates.js";
import { typeLabel } from "./fields.js";
import { Icon } from "./icons.js";
import { entityHref, fileHref, navigate } from "./router.js";
import { html, viewVersion } from "./state.js";
import { fold, folding } from "./text.js";

/**
 * @typedef {{text: string, highlights: [number, number][]}} Snippet
 * @typedef {{line: number, title: string, url: string, note: string, labels: string[]}} BookmarkInfo
 * @typedef {{kind: "file" | "bookmark", id: string, type: string, title: string, path: string,
 *   status?: string | null, finished?: boolean, tier: number, context?: string,
 *   lead?: string | null, due?: string | null, completed?: string | null, date?: string | null,
 *   about?: string | null, labels?: string[], bookmark?: BookmarkInfo, snippets: Snippet[]}} SearchHit
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
  project: "columns-3",
  deliverable: "panel-left",
  person: "user",
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
    openInNewTab(href);
    return;
  }
  const first = hit.snippets[0];
  if (hit.tier === BODY_TIER && first?.highlights.length) {
    const [start, end] = first.highlights[0];
    flashText(first.text.slice(start, end));
  }
  navigate(href);
}

/** Open one of the app's own routes in a new browser tab. @param {string} href */
export function openInNewTab(href) {
  window.open(`${window.location.pathname}${href}`, "_blank", "noopener");
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
 * The search page's fuller context line (§9.7): "Data Migration · lead Alice Smith · due 11 Dec",
 * "Alice Smith → Me · due Fri 20 Nov · about Data Migration", "notes/ · Tue 17 Nov · #one-on-one".
 * @param {SearchHit} hit
 */
export function hitLine(hit) {
  if (hit.bookmark) return hit.bookmark.url;
  const context = hit.context ?? "";
  const labels = (hit.labels ?? []).map((l) => `#${l}`);
  /** @type {(string | null | undefined | false)[]} */
  let parts;
  if (hit.type === "todo") {
    const when = hit.finished && hit.completed
      ? `completed ${dayMonth(hit.completed)}`
      : hit.due ? `due ${shortDate(hit.due)}` : !hit.finished && "no due date";
    parts = [context, when, hit.about && `about ${hit.about}`];
  } else if (hit.type === "note") {
    parts = [context && `${context}/`, hit.date && shortDate(hit.date), ...labels];
  } else {
    parts = [context, hit.lead && `lead ${hit.lead}`, hit.due && `due ${dayMonth(hit.due)}`, ...labels];
  }
  return parts.filter(Boolean).join(" · ");
}

/**
 * Where a word of the query starts a word of `text`, as [start, end) spans: the palette
 * bolds them in titles. Filter tokens are skipped. Matching ignores case and accents.
 * @param {string} text
 * @param {string} q
 * @returns {[number, number][]}
 */
export function wordMatches(text, q) {
  const { folded, span } = folding(text);
  const words = q.replace(/"/g, " ").split(/\s+/)
    .filter((w) => w && !w.includes(":") && !/^[@<>]/.test(w) && !/^due[<>]/i.test(w))
    .map(fold);
  /** @type {[number, number][]} */
  const spans = [];
  for (const word of words) {
    for (let at = folded.indexOf(word); at >= 0; at = folded.indexOf(word, at + 1)) {
      if (at === 0 || !/[a-z0-9]/.test(folded[at - 1])) spans.push(span(at, at + word.length));
    }
  }
  spans.sort((a, b) => a[0] - b[0]);
  return spans;
}

/** A title with the query's words marked. @param {{text: string, q: string}} props */
export function MatchedText({ text, q }) {
  return html`<${SnippetText} snippet=${{ text, highlights: wordMatches(text, q) }} />`;
}

/** @param {string} status */
function statusLabel(status) {
  const text = status.replace(/-/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** A hit's status: a dot for work, a box for an open To-do, a pill once finished. @param {{status: string}} props */
function StatusBadge({ status }) {
  if (status === "done") return html`<span class="result-status pill done"><${Icon} name="check" />Done</span>`;
  if (status === "cancelled" || status === "archived") {
    return html`<span class="result-status pill">${statusLabel(status)}</span>`;
  }
  const mark = status === "open" ? html`<span class="box"></span>` : html`<span class="dot dot-${status}"></span>`;
  return html`<span class="result-status ${status === "blocked" ? "blocked" : ""}">${mark}${statusLabel(status)}</span>`;
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
 * Swap one whitespace-separated token of a query for another, in place.
 * @param {string} q
 * @param {string} token
 * @param {string} next
 */
export function replaceToken(q, token, next) {
  return q.split(/\s+/).filter(Boolean).map((w) => (w === token ? next : w)).join(" ");
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
  /** Per-type counts without the `type:` filter, so the tabs stay put while one is picked. */
  const [allCounts, setAllCounts] = useState(/** @type {Record<string, number> | null} */ (null));
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const version = viewVersion.value;

  useEffect(() => setText(q), [q]);
  useEffect(() => {
    let live = true;
    fetchSearch(q, { hideCompleted, limit: Math.max(PAGE_SIZE, hits.length) })
      .then(async (next) => {
        const typeToken = next.query.filters.find((f) => f.kind === "type")?.token;
        const wide = typeToken
          ? (await fetchSearch(withoutToken(q, typeToken), { hideCompleted, limit: 1 })).counts
          : next.counts;
        if (!live) return;
        setData(next);
        setHits(next.hits);
        setAllCounts(wide);
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
  /** The `kind:` token already in the query, whose values a chip adds to (OR, §9.4). */
  const tokenFor = (/** @type {string} */ prefix) =>
    filters.find((f) => f.token.toLowerCase().startsWith(prefix));
  /** @param {string} prefix @param {string} value */
  const add = (prefix, value) => {
    if (!value) return;
    const existing = prefix === "@" ? undefined : tokenFor(prefix);
    if (!existing) go(withToken(q, `${prefix}${value}`));
    else if (!existing.values.includes(value)) {
      go(replaceToken(q, existing.token, `${prefix}${[...existing.values, value].join(",")}`));
    }
  };
  const typeToken = tokenFor("type:");
  /** A type tab toggles that type in the `type:` filter. @param {string} type */
  const toggleType = (type) => {
    if (!typeToken?.values.includes(type)) return add("type:", type);
    const rest = typeToken.values.filter((v) => v !== type);
    go(rest.length ? replaceToken(q, typeToken.token, `type:${rest.join(",")}`) : withoutToken(q, typeToken.token));
  };
  const typeShown = (/** @type {string} */ type) => Boolean(typeToken?.values.includes(type));
  const counts = allCounts ?? data?.counts ?? {};
  const all = Object.values(counts).reduce((a, b) => a + b, 0);
  const asked = q.trim();

  return html`
    <section class="page search-page">
      <header class="search-head">
        <p class="eyebrow">Search</p>
        <h1 class="title">${data && asked
          ? `${data.total} result${data.total === 1 ? "" : "s"} for ‘${asked}’`
          : "Search"}</h1>
      </header>
      <div class="search-controls">
        <form class="search-box" onSubmit=${(/** @type {Event} */ e) => {
          e.preventDefault();
          go(text.trim());
        }}>
          <${Icon} name="search" />
          <input type="search" aria-label="Search query" value=${text}
            onInput=${(/** @type {Event} */ e) => setText(/** @type {HTMLInputElement} */ (e.currentTarget).value)} />
          <span class="search-hint">filter with <code>type:</code> <code>status:</code> <code>@person</code></span>
        </form>
        <div class="search-chips">
          ${filters.map(
            (f) => html`<span class="filter-chip">${f.token}
              <button type="button" aria-label=${`Remove ${f.token}`}
                onClick=${() => go(withoutToken(q, f.token))}><${Icon} name="x" /></button>
            </span>`,
          )}
          <${AddChip} label="Type" choices=${TYPE_CHOICES} names=${typeName} onPick=${(/** @type {string} */ v) => add("type:", v)} />
          <${AddChip} label="Status" choices=${STATUS_CHOICES} onPick=${(/** @type {string} */ v) => add("status:", v)} />
          <${AddText} label="Person" prefix="@" onAdd=${(/** @type {string} */ v) => add("@", v)} />
          <${AddText} label="Label" prefix="label:" onAdd=${(/** @type {string} */ v) => add("label:", v)} />
          <${AddChip} label="Due" choices=${DUE_CHOICES} onPick=${(/** @type {string} */ v) => add("due:", v)} />
          <label class="hide-chip" title=${has("status") ? "A status filter overrides this" : ""}>
            <input type="checkbox" class="checkbox" checked=${hideCompleted} disabled=${has("status")}
              onChange=${() => go(q, !hideCompleted)} />
            Hide completed
          </label>
        </div>
        ${all > 0 &&
        html`<div class="type-tabs" role="group" aria-label="Results by type">
          <button type="button" aria-pressed=${!typeToken}
            onClick=${() => typeToken && go(withoutToken(q, typeToken.token))}>All <span class="count">${all}</span></button>
          ${Object.entries(counts).sort((a, b) => b[1] - a[1]).map(
            ([type, n]) => html`<button type="button" aria-pressed=${typeShown(type)}
              onClick=${() => toggleType(type)}>${typeName(type)} <span class="count">${n}</span></button>`,
          )}
        </div>`}
      </div>
      ${data?.query.errors.map((er) => html`<p class="error-text" role="alert">${er.token}: ${er.message}</p>`)}
      ${error && html`<p class="error-text" role="alert">${error}</p>`}
      ${data && !asked && html`<p class="hint">Type words to find, or filters like type:project @alice due:this-week.</p>`}
      ${data && asked && data.total === 0 && !data.query.errors.length && html`<p class="hint">Nothing matches.</p>`}
      <ul class="search-results">
        ${hits.map((hit) => html`<${ResultRow} key=${`${hit.path}:${hit.bookmark?.line ?? 0}`} hit=${hit} />`)}
      </ul>
      ${data && hits.length < data.total &&
      html`<button type="button" class="show-more" onClick=${() => void more()}>Show more</button>`}
    </section>
  `;
}

/** @param {{hit: SearchHit}} props */
function ResultRow({ hit }) {
  const finished = hit.finished;
  const href = hit.bookmark ? hit.bookmark.url : hitHref(hit);
  const external = Boolean(hit.bookmark);
  const line = hitLine(hit);
  return html`
    <li class="result ${finished ? "finished" : ""}">
      <div class="result-head">
        <a href=${href} target=${external ? "_blank" : undefined} rel=${external ? "noopener noreferrer" : undefined}
          onClick=${(/** @type {MouseEvent} */ e) => {
            if (e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0) return;
            e.preventDefault();
            openHit(hit);
          }}>${hit.title}</a>
        <span class="type-badge">${typeName(hit.type)}</span>
        ${hit.status && html`<${StatusBadge} status=${hit.status} />`}
      </div>
      ${line && html`<div class="result-context">${line}</div>`}
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
    <span class="add-chip">
      <select aria-label=${`Add ${label} filter`}
        onChange=${(/** @type {Event} */ e) => {
          const select = /** @type {HTMLSelectElement} */ (e.currentTarget);
          onPick(select.value);
          select.value = "";
        }}>
        <option value="">${label}</option>
        ${choices.map((c) => html`<option value=${c}>${names ? names(c) : statusLabel(c)}</option>`)}
      </select>
      <${Icon} name="chevron-down" />
    </span>
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
      <input aria-label=${`Add ${label} filter`} placeholder=${label} title=${`${prefix}${label.toLowerCase()}: type and press Enter`}
        size="7" value=${value} onInput=${(/** @type {Event} */ e) => setValue(/** @type {HTMLInputElement} */ (e.currentTarget).value)} />
      <${Icon} name="chevron-down" />
    </form>
  `;
}
