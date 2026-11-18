// @ts-check
// `#/trash` (SPEC §8.4), per "Trash" in Paper: deletes newest first, grouped by trash stamp
// (date and the mono stamp folder). Each row has its type icon, title and original path,
// what the delete did to references, and Restore. When Restore can't succeed (the Id or
// the path is taken) the row says why before anyone clicks.

import { useState } from "preact/hooks";
import { describe, request } from "./api.js";
import { dayTime } from "./dates.js";
import { typeLabel } from "./fields.js";
import { Icon } from "./icons.js";
import { entityHref, fileHref } from "./router.js";
import { typeIcon } from "./search.js";
import { today } from "./todos.js";
import { html, reloadTree, tree, useView } from "./state.js";

/**
 * @typedef {{mode: "plain" | "replace" | "remove", references: number, files: number,
 *   replacement: string | null, replacement_title: string | null}} Deletion
 * @typedef {{id: string, title: string, type: string, path: string}} FileRef
 * @typedef {{reason: "id" | "path", path: string, id: string | null, by: FileRef | null}} Blocked
 * @typedef {{entry: string, path: string, files: string[], deleted: string | null, type: string,
 *   id: string | null, title: string, deletion: Deletion | null, blocked: Blocked | null}} Trashed
 * @typedef {{stamp: string, deleted: string | null, entries: Trashed[]}} Group
 */

const TRASH = ".memex/trash";

/** @param {number} n @param {string} one @param {string} [many] */
const count = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** Entries made in the same second share a stamp (`<stamp>`, `<stamp>-2`, …). @param {Trashed[]} entries */
function byStamp(entries) {
  /** @type {Group[]} */
  const groups = [];
  for (const t of entries) {
    const stamp = t.entry.slice(0, 15);
    const last = groups.at(-1);
    if (last?.stamp === stamp) last.entries.push(t);
    else groups.push({ stamp, deleted: t.deleted, entries: [t] });
  }
  return groups;
}

export function TrashPage() {
  const { data, error, reload } = useView("/api/trash");
  const entries = /** @type {{entries: Trashed[]} | null} */ (data)?.entries;
  const [problem, setProblem] = useState(/** @type {{entry: string, message: string} | null} */ (null));
  const readOnly = tree.value?.workspace.read_only ?? false;
  const files = entries?.reduce((n, t) => n + Math.max(t.files.length, 1), 0) ?? 0;

  /** @param {Trashed} t */
  async function restore(t) {
    try {
      await request("POST", "/api/trash/restore", { json: { entry: t.entry } });
      setProblem(null);
      await reloadTree();
      await reload();
    } catch (e) {
      setProblem({ entry: t.entry, message: `Can't restore ${t.path}: ${describe(e)}` });
    }
  }

  return html`
    <section class="page repair-page trash-page">
      <header class="repair-head">
        <p class="eyebrow">${entries ? `${count(files, "file")} · never emptied automatically` : " "}</p>
        <h1 class="title">Trash</h1>
      </header>
      <p class="lede">Deleted files wait in <code>${TRASH}/</code>. Restore puts a file back at its original path
        when both the path and its Id are still free. References rewritten at delete time stay rewritten.</p>
      ${error && html`<p class="error-text" role="alert">${describe(error)}</p>`}
      ${entries && !entries.length && html`<p class="block-empty">The trash is empty.</p>`}
      ${entries &&
      byStamp(entries).map(
        (g) => html`
          <section key=${g.stamp} class="block trash-group">
            <div class="block-row trash-when">
              <span class="bullet"></span>
              <h2 class="block-text">${g.deleted ? dayTime(g.deleted, today()) : g.stamp}</h2>
              <code class="trash-stamp">${g.entries.map((t) => `${t.entry}/`).join(" · ")}</code>
            </div>
            <div class="block-children">
              ${g.entries.map(
                (t) => html`<${TrashRow} key=${t.entry} item=${t} readOnly=${readOnly}
                  problem=${problem?.entry === t.entry ? problem.message : null} onRestore=${() => restore(t)} />`,
              )}
            </div>
          </section>
        `,
      )}
    </section>
  `;
}

/** @param {Trashed} t */
function icon(t) {
  if (t.type === "folder") return "folder";
  if (t.type === "file") return "file";
  return typeIcon(t.type);
}

/** "Project", "Folder · 3 files", "File". @param {Trashed} t */
function kind(t) {
  if (t.type === "folder") return `Folder · ${count(t.files.length, "file")}`;
  if (t.type === "file") return "File";
  return typeLabel(t.type);
}

/**
 * What the delete did to references.
 * @param {{deletion: Deletion, folder: boolean}} props
 */
function DeletionNote({ deletion: d, folder }) {
  const refs = count(d.references, "reference");
  const were = d.references === 1 ? "was" : "were";
  if (d.mode === "replace" && d.references > 0) {
    const name = d.replacement_title ?? d.replacement;
    return html`${refs} ${were} replaced with ${d.replacement ? html`<a href=${entityHref(d.replacement)}>${name}</a>` : name} (not restored)`;
  }
  if (d.mode === "remove" && d.references > 0) return html`${refs} ${were} removed (not restored)`;
  return folder ? "nothing outside referred to it" : "had no incoming references";
}

/**
 * Why Restore can't succeed now.
 * @param {{blocked: Blocked, raw: string | null}} props
 */
function BlockedNote({ blocked: b, raw }) {
  const open = raw && html`, or <a href=${fileHref(raw)}>open this one raw</a> to copy its text`;
  if (b.reason === "id") {
    const by = b.by
      ? html`<a href=${entityHref(b.by.id, b.by.type)}>${b.by.title}</a> (${b.by.path})`
      : "more than one file";
    return html`<span class="blocked">Can't restore: Id <code>${b.id}</code> is taken by ${by}.</span>${" "}${
      b.by ? "Rename that file's Id" : "Rename those files' Ids"}${open}.`;
  }
  return html`<span class="blocked">Can't restore: <code>${b.path}</code> is taken.</span>${" "}Move or rename that file${open}.`;
}

/**
 * @param {{item: Trashed, readOnly: boolean, problem: string | null, onRestore: () => void}} props
 */
function TrashRow({ item: t, readOnly, problem, onRestore }) {
  const why = `restore-blocked-${t.entry}`;
  const raw = t.type !== "folder" && t.type !== "file" ? `${TRASH}/${t.entry}/${t.path}` : null;
  return html`
    <div class="trash-item" role="group" aria-label=${t.path}>
      <span class="trash-icon"><${Icon} name=${icon(t)} /></span>
      <div class="trash-body">
        <div class="trash-line">
          <span class="trash-title">${t.title}</span>
          <code class="trash-path">${t.path}</code>
        </div>
        <p class="trash-note" id=${why}>
          ${t.blocked
            ? html`<${BlockedNote} blocked=${t.blocked} raw=${raw} />`
            : html`${kind(t)}${t.deletion && html` · <${DeletionNote} deletion=${t.deletion} folder=${t.type === "folder"} />`}`}
        </p>
        ${problem && html`<p class="error-text" role="alert">${problem}</p>`}
      </div>
      ${!readOnly &&
      html`<button type="button" class="restore" disabled=${t.blocked !== null}
        aria-describedby=${t.blocked ? why : undefined} onClick=${onRestore}>Restore</button>`}
    </div>
  `;
}
