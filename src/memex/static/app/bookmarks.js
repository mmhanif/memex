// @ts-check
// `#/bookmarks` (SPEC §10.1), per "Bookmarks" in Paper: `bookmarks.md` rendered as outline
// blocks (its headings as heading blocks, prose kept as text), Label chips with counts, and
// the Add form in a well. Bookmark URLs are only ever opened by the browser in a new tab;
// Memex never fetches them.

import { useEffect, useState } from "preact/hooks";
import { ApiError, describe, request } from "./api.js";
import { Icon } from "./icons.js";
import { fileHref, navigate } from "./router.js";
import { html, tree, useView } from "./state.js";

/**
 * @typedef {{line: number, title: string, url: string, note: string, labels: string[]}} Bookmark
 * @typedef {{line: number, text: string, bookmark: Bookmark | null}} Line
 * @typedef {{lines: Line[], labels: {name: string, count: number}[], total: number}} BookmarksView
 * @typedef {{heading: Line | null, lines: Line[]}} Section
 */

const FILE = "bookmarks.md";
const HEADING = /^#{1,6}\s+(.*)$/;

/** Labels compare ignoring case and accents, as the server's filter does. @param {string} s */
function fold(s) {
  return s.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase();
}

/**
 * The shown lines split at each heading; lines before the first heading have none.
 * @param {Line[]} lines
 * @returns {Section[]}
 */
function sections(lines) {
  /** @type {Section[]} */
  const out = [{ heading: null, lines: [] }];
  for (const n of lines) {
    if (!n.bookmark && HEADING.test(n.text)) out.push({ heading: n, lines: [] });
    else out[out.length - 1].lines.push(n);
  }
  return out.filter((s) => s.heading || s.lines.length);
}

/** @param {{query: URLSearchParams}} props */
export function BookmarksPage({ query }) {
  const label = query.get("label") ?? "";
  const line = Number(query.get("line") ?? 0);
  const url = label ? `/api/bookmarks?label=${encodeURIComponent(label)}` : "/api/bookmarks";
  const { data, error, reload } = useView(url);
  const view = /** @type {BookmarksView | null} */ (data);
  const readOnly = tree.value?.workspace.read_only ?? false;

  // Alt-Enter on a search hit lands here with `?line=` (§9.8): bring that line into view.
  useEffect(() => {
    if (!line || !view) return;
    const row = document.getElementById(`bookmark-line-${line}`);
    row?.scrollIntoView({ block: "center" });
    row?.classList.add("flash");
  }, [line, view]);

  /** @param {string} next */
  function filterBy(next) {
    navigate(next ? `#/bookmarks?label=${encodeURIComponent(next)}` : "#/bookmarks");
  }

  const shown = view?.lines.filter((n) => n.bookmark || n.text.trim()) ?? [];
  return html`
    <section class="page bookmarks-page">
      <header class="bookmarks-head">
        <p class="eyebrow">${view ? `${view.total} Bookmark${view.total === 1 ? "" : "s"} · ` : ""}<a
          href=${fileHref(FILE)} class="file-link" title=${`Edit ${FILE}`}>${FILE}</a></p>
        <h1 class="title">Bookmarks</h1>
      </header>
      ${!readOnly && html`<${AddForm} onAdded=${reload} />`}
      ${view &&
      view.labels.length > 0 &&
      html`<div class="label-filter" role="group" aria-label="Label filter">
        <button type="button" class="label-chip all" aria-pressed=${!label} onClick=${() => filterBy("")}><span>All</span><span class="count">${view.total}</span></button>
        ${view.labels.map(
          (l) => html`<button type="button" class="label-chip" key=${l.name}
            aria-pressed=${fold(l.name) === fold(label)} onClick=${() => filterBy(l.name)}><span class="label-name">#${l.name}</span><span class="count">${l.count}</span></button>`,
        )}
      </div>`}
      ${error && html`<p class="error-text" role="alert">${describe(error)}</p>`}
      ${view && !shown.length && html`<p class="block-empty">${label ? `No Bookmarks are labelled #${label}.` : "No Bookmarks yet."}</p>`}
      <div class="bookmarks">
        ${sections(shown).map((s) =>
          s.heading
            ? html`<section key=${s.heading.line} class="block block-heading bookmark-section" id=${`bookmark-line-${s.heading.line}`}>
                <div class="block-row"><span class="bullet"></span><h2 class="block-text">${HEADING.exec(s.heading.text)?.[1]}</h2></div>
                ${s.lines.length > 0 &&
                html`<div class="block-children">
                  ${s.lines.map((n) => html`<${LineBlock} key=${n.line} line=${n} onLabel=${filterBy} />`)}
                </div>`}
              </section>`
            : s.lines.map((n) => html`<${LineBlock} key=${n.line} line=${n} onLabel=${filterBy} />`),
        )}
      </div>
    </section>
  `;
}

/**
 * A Bookmark as a block: its title (a bare URL in mono), ↗, the domain, then the note and
 * Labels. Any other line is plain text in the block's place, without a bullet.
 * @param {{line: Line, onLabel: (label: string) => void}} props
 */
function LineBlock({ line, onLabel }) {
  const b = line.bookmark;
  const id = `bookmark-line-${line.line}`;
  if (!b) {
    return html`<div id=${id} class="block bookmark-text">
      <div class="block-row"><span class="bullet-slot"></span><p class="block-text">${line.text}</p></div>
    </div>`;
  }
  return html`
    <div id=${id} class="block bookmark">
      <div class="block-row">
        <span class="bullet"></span>
        <div class="block-text">
          <div class="bookmark-line">
            <${BookmarkLink} bookmark=${b} class=${b.title ? "bookmark-title" : "bookmark-title mono"} />
            ${/^https?:\/\//i.test(b.url) && html`<${Icon} name="arrow-up-right" />`}
            ${b.title && html`<span class="bookmark-domain">${domain(b.url)}</span>`}
          </div>
          ${(b.note || b.labels.length > 0) &&
          html`<p class="bookmark-note">
            ${b.note}
            ${b.labels.map(
              (l) => html` <button type="button" class="label-link" key=${l} onClick=${() => onLabel(l)}>#${l}</button>`,
            )}
          </p>`}
        </div>
      </div>
    </div>
  `;
}

/** The host a URL points at, or the URL itself when it doesn't parse. @param {string} url */
function domain(url) {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

/**
 * A Bookmark's title (else its URL), opened by the browser in a new tab. Only http(s) URLs
 * become links.
 * @param {{bookmark: Bookmark, class?: string}} props
 */
export function BookmarkLink({ bookmark: b, class: cls }) {
  const label = b.title || b.url;
  if (!/^https?:\/\//i.test(b.url)) return html`<span class=${cls}>${label}</span>`;
  return html`<a href=${b.url} class=${cls} target="_blank" rel="noopener noreferrer">${label}</a>`;
}

/** @param {{onAdded: () => Promise<void>}} props */
function AddForm({ onAdded }) {
  const empty = { url: "", title: "", note: "", labels: "" };
  const [form, setForm] = useState(empty);
  const [problem, setProblem] = useState(/** @type {string | null} */ (null));
  const [fieldErrors, setFieldErrors] = useState(/** @type {Record<string, string>} */ ({}));
  const [busy, setBusy] = useState(false);

  /** @param {keyof typeof empty} name */
  function field(name) {
    return {
      value: form[name],
      onInput: (/** @type {InputEvent} */ e) =>
        setForm({ ...form, [name]: /** @type {HTMLInputElement} */ (e.currentTarget).value }),
      "aria-invalid": fieldErrors[name] ? "true" : undefined,
    };
  }

  /** @param {SubmitEvent} e */
  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    try {
      await request("POST", "/api/bookmarks", {
        json: {
          url: form.url,
          title: form.title,
          note: form.note,
          labels: form.labels.split(/[\s,]+/).filter(Boolean),
        },
      });
      setForm(empty);
      setProblem(null);
      setFieldErrors({});
      await onAdded();
    } catch (err) {
      const errors = err instanceof ApiError ? (err.body.field_errors ?? []) : [];
      setFieldErrors(Object.fromEntries(errors.map((f) => [f.field, f.message])));
      setProblem(errors.length ? null : describe(err));
    } finally {
      setBusy(false);
    }
  }

  return html`
    <form class="well bookmark-add" onSubmit=${submit} aria-label="Add a Bookmark">
      <div class="bookmark-add-head">
        <span class="eyebrow">Add Bookmark</span>
        <span class="add-hint">appends one line to ${FILE}</span>
      </div>
      <div class="bookmark-add-row">
        <input type="url" class="url" required aria-label="URL" placeholder="https://…" ...${field("url")} />
        <input type="text" class="title-field" aria-label="Title" placeholder="Title" ...${field("title")} />
      </div>
      <div class="bookmark-add-row">
        <input type="text" class="note" aria-label="Note" placeholder="Note (optional)" ...${field("note")} />
        <input type="text" class="labels" aria-label="Labels" placeholder="#labels" ...${field("labels")} />
        <button type="submit" class="solid" disabled=${busy}>Add</button>
      </div>
      ${Object.entries(fieldErrors).map(
        ([name, message]) => html`<p class="error-text" role="alert" key=${name}>${name}: ${message}</p>`,
      )}
      ${problem && html`<p class="error-text" role="alert">${problem}</p>`}
    </form>
  `;
}
