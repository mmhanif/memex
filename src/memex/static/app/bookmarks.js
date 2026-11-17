// @ts-check
// `#/bookmarks` (SPEC §10.1): `bookmarks.md` rendered, with a Label filter and Add.
// Bookmark URLs are only ever opened by the browser in a new tab; Memex never fetches them.

import { useEffect, useState } from "preact/hooks";
import { ApiError, describe, request } from "./api.js";
import { fileHref, navigate } from "./router.js";
import { html, tree, useView } from "./state.js";

/**
 * @typedef {{line: number, title: string, url: string, note: string, labels: string[]}} Bookmark
 * @typedef {{line: number, text: string, bookmark: Bookmark | null}} Line
 * @typedef {{lines: Line[], labels: string[]}} BookmarksView
 */

const FILE = "bookmarks.md";

/** Labels compare ignoring case and accents, as the server's filter does. @param {string} s */
function fold(s) {
  return s.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase();
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
    <section class="bookmarks-page">
      <header class="page-head">
        <h1>Bookmarks</h1>
        <a href=${fileHref(FILE)} class="muted">Edit ${FILE}</a>
      </header>
      ${!readOnly && html`<${AddForm} onAdded=${reload} />`}
      ${view &&
      view.labels.length > 0 &&
      html`<div class="label-filter" role="group" aria-label="Label filter">
        <button type="button" class="chip" aria-pressed=${!label} onClick=${() => filterBy("")}>All</button>
        ${view.labels.map(
          (l) => html`<button type="button" class="chip" key=${l}
            aria-pressed=${fold(l) === fold(label)} onClick=${() => filterBy(l)}>#${l}</button>`,
        )}
      </div>`}
      ${error && html`<p class="error-text" role="alert">${describe(error)}</p>`}
      ${view && !shown.length && html`<p class="muted">${label ? `No Bookmarks are labelled #${label}.` : "No Bookmarks yet."}</p>`}
      <ul class="bookmarks">
        ${shown.map((n) => html`<${LineRow} key=${n.line} line=${n} onLabel=${filterBy} />`)}
      </ul>
    </section>
  `;
}

/** @param {{line: Line, onLabel: (label: string) => void}} props */
function LineRow({ line, onLabel }) {
  const b = line.bookmark;
  const id = `bookmark-line-${line.line}`;
  if (!b) {
    const heading = /^(#{1,6})\s+(.*)$/.exec(line.text);
    if (heading) return html`<li id=${id} class="bookmark-heading">${heading[2]}</li>`;
    return html`<li id=${id} class="bookmark-text">${line.text}</li>`;
  }
  const safe = /^https?:\/\//i.test(b.url);
  return html`
    <li id=${id} class="bookmark">
      ${safe
        ? html`<a href=${b.url} target="_blank" rel="noopener noreferrer">${b.title || b.url}</a>`
        : html`<span>${b.title || b.url}</span>`}
      ${b.title && html`<span class="bookmark-url muted">${b.url}</span>`}
      ${b.note && html`<span class="bookmark-note">${b.note}</span>`}
      ${b.labels.map(
        (l) => html`<button type="button" class="chip label" key=${l} onClick=${() => onLabel(l)}>#${l}</button>`,
      )}
    </li>
  `;
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
    <form class="bookmark-add" onSubmit=${submit} aria-label="Add a Bookmark">
      <label>URL <input type="url" required placeholder="https://…" ...${field("url")} /></label>
      <label>Title <input type="text" ...${field("title")} /></label>
      <label>Note <input type="text" ...${field("note")} /></label>
      <label>Labels <input type="text" placeholder="ref eng" ...${field("labels")} /></label>
      <button type="submit" class="primary" disabled=${busy}>Add</button>
      ${Object.entries(fieldErrors).map(
        ([name, message]) => html`<p class="error-text" role="alert" key=${name}>${name}: ${message}</p>`,
      )}
      ${problem && html`<p class="error-text" role="alert">${problem}</p>`}
    </form>
  `;
}
