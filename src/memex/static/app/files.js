// @ts-check
// The Files page (SPEC §11.8): the raw tree, and the raw whole-file editor (frontmatter
// included) with a live preview. The escape hatch for any file.

import { useEffect, useLayoutEffect, useRef, useState } from "preact/hooks";
import { ApiError, describe, fileUrl, request } from "./api.js";
import { OpenDoc } from "./doc.js";
import { fetchTemplates, openNew } from "./newform.js";
import { renderMarkdown, splitFrontmatter } from "./markdown.js";
import { entityHref, fileHref, isUnder, navigate } from "./router.js";
import { Icon } from "./icons.js";
import { openLifecycle } from "./lifecycle.js";
import { html, openDoc, reloadTree, resolveMention, tree } from "./state.js";

/**
 * @typedef {import("./state.js").TreeFile} TreeFile
 * @typedef {{name: string, path: string, folders: Folder[], files: TreeFile[]}} Folder
 * @typedef {{kind: "file" | "folder", path: string}} Selection
 * @typedef {"new-file" | "new-folder" | "move"} Action
 */

/** @param {{path: string | null}} props */
export function FilesPage({ path }) {
  const [selection, setSelection] = useState(
    /** @type {Selection | null} */ (path ? { kind: "file", path } : null),
  );
  useEffect(() => {
    if (path) setSelection({ kind: "file", path });
  }, [path]);

  return html`
    <div class="files-page">
      <aside class="files-tree">
        <${Actions} selection=${selection} onSelect=${setSelection} />
        <${TreeView} openPath=${path} selection=${selection} onSelect=${setSelection} />
      </aside>
      <section class="files-editor">
        ${path
          ? html`<${Editor} key=${path} path=${path} />`
          : html`<p class="hint">Pick a file to open it, or make a new one.</p>`}
      </section>
    </div>
  `;
}

/** @param {{selection: Selection | null, onSelect: (s: Selection | null) => void}} props */
function Actions({ selection, onSelect }) {
  const [action, setAction] = useState(/** @type {Action | null} */ (null));
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const folder = selection ? (selection.kind === "folder" ? selection.path : parentOf(selection.path)) : "";

  /** @param {string} value */
  async function submit(value) {
    const name = value.trim().replace(/^\/+|\/+$/g, "");
    if (!name) return;
    try {
      if (action === "new-folder") {
        const path = join(folder, name);
        await request("POST", "/api/folders", { json: { path } });
        await reloadTree();
        onSelect({ kind: "folder", path });
      } else if (action === "move" && selection) {
        await moveSelection(selection, name, onSelect);
      }
      setAction(null);
      setError(null);
    } catch (e) {
      setError(describe(e));
    }
  }

  async function remove() {
    if (!selection) return;
    const what = selection.kind === "folder" ? `the folder ${selection.path} and everything in it` : selection.path;
    if (!window.confirm(`Move ${what} to the trash?`)) return;
    try {
      await request("DELETE", fileUrl(selection.path));
      if (openDoc.value && isUnder(openDoc.value.path, selection.path)) {
        openDoc.value.dispose();
        openDoc.value = null;
        navigate("#/files");
      }
      onSelect(null);
      setError(null);
      await reloadTree();
    } catch (e) {
      const file = tree.value?.files.find((f) => f.path === selection.path);
      if (e instanceof ApiError && e.code === "has_references" && file) {
        // Something refers to this file: the guided delete with its impact preview (§8.4).
        setError(null);
        openLifecycle("delete", { ...file, type: file.type ?? "note" }, "#/files");
      } else if (e instanceof ApiError && e.code === "has_references") {
        const referrers = e.body.impact?.referrers ?? [];
        setError(`${e.message}: ${referrers.join(", ")}. Remove those references first.`);
      } else {
        setError(describe(e));
      }
    }
  }

  const initial = action === "move" && selection ? selection.path : "";
  return html`
    <div class="files-actions">
      <div class="toolbar">
        <button
          type="button"
          title="New file here"
          onClick=${() => {
            // Inside a type folder a new file is an Entity of that type: use its form.
            const type = TYPE_FOLDERS[folder];
            if (type) openNew(type);
            else setAction("new-file");
          }}
        >
          <${Icon} name="file-plus" /> File
        </button>
        <button type="button" title="New folder here" onClick=${() => setAction("new-folder")}>
          <${Icon} name="folder-plus" /> Folder
        </button>
        <button type="button" title="Rename or move" disabled=${!selection} onClick=${() => setAction("move")}>
          <${Icon} name="pencil" /> Move
        </button>
        <button type="button" title="Delete to trash" disabled=${!selection} onClick=${remove}>
          <${Icon} name="trash-2" /> Delete
        </button>
      </div>
      ${action === "new-file" &&
      html`<${NewNoteForm} folder=${folder} onDone=${() => setAction(null)} />`}
      ${action &&
      action !== "new-file" &&
      html`<${PathForm}
        key=${action}
        label=${action === "move" ? "New path" : `New folder in ${folder || "the Workspace"}`}
        initial=${initial}
        onSubmit=${submit}
        onCancel=${() => setAction(null)}
      />`}
      ${error && html`<p class="error-text" role="alert">${error}</p>`}
    </div>
  `;
}

/**
 * @param {Selection} selection
 * @param {string} to
 * @param {(s: Selection | null) => void} onSelect
 */
async function moveSelection(selection, to, onSelect) {
  const doc = openDoc.value;
  if (doc && isUnder(doc.path, selection.path)) await doc.flush();
  await request("POST", "/api/move", { json: { from: selection.path, to } });
  await reloadTree();
  onSelect({ kind: selection.kind, path: to });
  if (doc && isUnder(doc.path, selection.path)) {
    // Our own move: follow it (the app never follows an outside rename).
    doc.dispose();
    openDoc.value = null;
    navigate(fileHref(to + doc.path.slice(selection.path.length)));
  }
}

/** @type {Record<string, string>} */
const TYPE_FOLDERS = {
  themes: "theme",
  projects: "project",
  deliverables: "deliverable",
  people: "person",
  todos: "todo",
  glossary: "glossary-term",
};

/**
 * New file here (§7.4, §11.8): a Note in the browsed folder, from a Template.
 * @param {{folder: string, onDone: () => void}} props
 */
function NewNoteForm({ folder, onDone }) {
  const [templates, setTemplates] = useState(/** @type {import("./newform.js").TemplateInfo[]} */ ([]));
  const [template, setTemplate] = useState("");
  const [title, setTitle] = useState("");
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const input = useRef(/** @type {HTMLInputElement | null} */ (null));
  useEffect(() => {
    input.current?.focus();
    fetchTemplates("note").then(
      ({ usable, fallback }) => {
        setTemplates(usable);
        setTemplate(fallback.name);
      },
      (e) => setError(describe(e)),
    );
  }, []);

  /** @param {Event} e */
  async function submit(e) {
    e.preventDefault();
    try {
      const created = await request("POST", "/api/entities", {
        json: { type: "note", fields: { title: title.trim() }, template, folder },
      });
      await reloadTree();
      onDone();
      navigate(fileHref(created.path));
    } catch (err) {
      setError(describe(err));
    }
  }

  return html`
    <form class="path-form" onSubmit=${submit}
      onKeyDown=${(/** @type {KeyboardEvent} */ e) => e.key === "Escape" && onDone()}>
      <label>
        New Note in ${folder || "the Workspace"}
        <input ref=${input} aria-label="Note title" placeholder="Title" value=${title}
          onInput=${(/** @type {Event} */ e) => setTitle(/** @type {HTMLInputElement} */ (e.currentTarget).value)} />
      </label>
      <label>
        Template
        <select value=${template}
          onChange=${(/** @type {Event} */ e) => setTemplate(/** @type {HTMLSelectElement} */ (e.currentTarget).value)}>
          ${templates.map((t) => html`<option value=${t.name}>${t.display_name}</option>`)}
        </select>
      </label>
      <button type="submit" class="primary" disabled=${!template}>Create</button>
      <button type="button" onClick=${onDone}>Cancel</button>
      ${error && html`<p class="error-text" role="alert">${error}</p>`}
    </form>
  `;
}

/** @param {{label: string, initial: string, onSubmit: (v: string) => void, onCancel: () => void}} props */
function PathForm({ label, initial, onSubmit, onCancel }) {
  const input = useRef(/** @type {HTMLInputElement | null} */ (null));
  useEffect(() => input.current?.focus(), []);
  return html`
    <form
      class="path-form"
      onSubmit=${(/** @type {Event} */ e) => {
        e.preventDefault();
        onSubmit(input.current?.value ?? "");
      }}
    >
      <label>
        ${label}
        <input ref=${input} value=${initial} onKeyDown=${(/** @type {KeyboardEvent} */ e) => e.key === "Escape" && onCancel()} />
      </label>
      <button type="submit" class="primary">OK</button>
      <button type="button" onClick=${onCancel}>Cancel</button>
    </form>
  `;
}

/**
 * @param {{openPath: string | null, selection: Selection | null, onSelect: (s: Selection) => void}} props
 */
function TreeView({ openPath, selection, onSelect }) {
  const [collapsed, setCollapsed] = useState(/** @type {Set<string>} */ (new Set()));
  const data = tree.value;
  if (!data) return html`<p class="hint">Loading…</p>`;
  const root = buildTree(data.folders, data.files);

  /** @param {string} path */
  function toggle(path) {
    const next = new Set(collapsed);
    if (next.has(path)) next.delete(path);
    else next.add(path);
    setCollapsed(next);
  }

  /** @param {Folder} folder @returns {any} */
  function renderFolder(folder) {
    return html`
      <ul role="group">
        ${folder.folders.map((child) => {
          const isCollapsed = collapsed.has(child.path) && !(openPath && isUnder(openPath, child.path));
          const selected = selection?.kind === "folder" && selection.path === child.path;
          return html`
            <li role="treeitem" aria-expanded=${!isCollapsed} aria-selected=${selected}>
              <button
                type="button"
                class="tree-folder ${selected ? "selected" : ""}"
                onClick=${() => {
                  onSelect({ kind: "folder", path: child.path });
                  toggle(child.path);
                }}
              >
                <${Icon} name=${isCollapsed ? "chevron-right" : "chevron-down"} />
                <${Icon} name="folder" />
                ${child.name}
              </button>
              ${!isCollapsed && renderFolder(child)}
            </li>
          `;
        })}
        ${folder.files.map(
          (file) => html`
            <li role="treeitem" aria-selected=${file.path === openPath}>
              <a
                href=${fileHref(file.path)}
                class="tree-file ${file.path === openPath ? "selected" : ""}"
                title=${file.title}
              >
                <${Icon} name=${file.warnings.length ? "circle-alert" : "file-text"} />
                ${file.path.split("/").pop()}
              </a>
            </li>
          `,
        )}
      </ul>
    `;
  }

  return html`<nav class="tree" role="tree" aria-label="Workspace files">${renderFolder(root)}</nav>`;
}

/**
 * @param {string[]} folders
 * @param {TreeFile[]} files
 * @returns {Folder}
 */
function buildTree(folders, files) {
  /** @type {Map<string, Folder>} */
  const byPath = new Map();
  const root = { name: "", path: "", folders: [], files: [] };
  byPath.set("", root);
  /** @param {string} path @returns {Folder} */
  function folderFor(path) {
    const found = byPath.get(path);
    if (found) return found;
    const folder = { name: path.split("/").pop() ?? path, path, folders: [], files: [] };
    byPath.set(path, folder);
    folderFor(parentOf(path)).folders.push(folder);
    return folder;
  }
  for (const path of folders) folderFor(path);
  for (const file of files) folderFor(parentOf(file.path)).files.push(file);
  for (const folder of byPath.values()) {
    folder.folders.sort((a, b) => a.name.localeCompare(b.name));
    folder.files.sort((a, b) => a.path.localeCompare(b.path));
  }
  return root;
}

/** @param {{path: string}} props */
function Editor({ path }) {
  const [loadError, setLoadError] = useState(/** @type {string | null} */ (null));
  useEffect(() => {
    let cancelled = false;
    OpenDoc.open(path).then(
      (doc) => {
        if (cancelled) return doc.dispose();
        openDoc.value?.dispose();
        openDoc.value = doc;
      },
      (/** @type {unknown} */ e) => !cancelled && setLoadError(describe(e)),
    );
    return () => {
      cancelled = true;
      const doc = openDoc.value;
      if (doc && doc.path === path) {
        void doc.flush();
        openDoc.value = null;
      }
    };
  }, [path]);

  const doc = openDoc.value;
  if (loadError) return html`<p class="error-text" role="alert">${loadError}</p>`;
  if (!doc || doc.path !== path) return html`<p class="hint">Opening ${path}…</p>`;
  const file = tree.value?.files.find((f) => f.path === path);
  const warnings = file?.warnings ?? [];
  return html`
    <div class="editor">
      <header class="editor-head">
        <h1 class="editor-path">${path}</h1>
        ${file && html`<a class="button" href=${entityHref(file.id)}>Open page</a>`}
        <${SaveStatus} doc=${doc} />
      </header>
      ${warnings.map(
        (w) => html`<div class="banner warn">${w.message}${w.line ? ` (line ${w.line})` : ""}</div>`,
      )}
      <${DocBanners} doc=${doc} />
      <div class="split">
        <${RawText} doc=${doc} />
        <${Preview} text=${doc.text.value} />
      </div>
    </div>
  `;
}

/** @param {{doc: OpenDoc}} props */
export function SaveStatus({ doc }) {
  const labels = { clean: "Saved", dirty: "Unsaved", saving: "Saving…", conflict: "Not saved", deleted: "Not saved" };
  return html`<span class="save-status ${doc.state.value}" data-state=${doc.state.value}>${labels[doc.state.value]}</span>`;
}

/** @param {{doc: OpenDoc, closeTo?: string}} props */
export function DocBanners({ doc, closeTo = "#/files" }) {
  const [rows, setRows] = useState(/** @type {import("./doc.js").DiffRow[] | null} */ (null));
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const state = doc.state.value;
  useEffect(() => {
    if (state !== "conflict") setRows(null);
  }, [state]);

  async function compare() {
    try {
      setRows(await doc.compare());
    } catch (e) {
      setError(describe(e));
    }
  }

  return html`
    ${doc.notice.value && html`<div class="banner info" role="status">${doc.notice.value}</div>`}
    ${state === "conflict" &&
    html`<div class="banner conflict" role="alert">
      <span>This file changed on disk while you were editing it.</span>
      <button type="button" onClick=${() => doc.reload()}>Reload</button>
      <button type="button" onClick=${() => void doc.keepMine()}>Keep mine</button>
      <button type="button" onClick=${compare}>Compare</button>
    </div>`}
    ${state === "deleted" &&
    html`<div class="banner conflict" role="alert">
      <span>This file was deleted or moved outside Memex. Your text is still here.</span>
      ${doc.canRecreate && html`<button type="button" onClick=${() => void doc.recreate()}>Recreate</button>`}
      <button
        type="button"
        onClick=${() => {
          doc.dispose();
          openDoc.value = null;
          navigate(closeTo);
        }}
      >
        Close
      </button>
    </div>`}
    ${error && html`<p class="error-text">${error}</p>`}
    ${rows && state === "conflict" && html`<${DiffView} rows=${rows} onClose=${() => setRows(null)} />`}
  `;
}

/** @param {{rows: import("./doc.js").DiffRow[], onClose: () => void}} props */
function DiffView({ rows, onClose }) {
  return html`
    <div class="diff">
      <div class="diff-head">
        <span>On disk</span><span>Mine</span>
        <button type="button" title="Close" aria-label="Close" onClick=${onClose}><${Icon} name="x" /></button>
      </div>
      <table>
        <tbody>
          ${rows.map(
            (row) => html`
              <tr class="diff-${row.kind}">
                <td class="disk">${row.disk ?? ""}</td>
                <td class="mine">${row.mine ?? ""}</td>
              </tr>
            `,
          )}
        </tbody>
      </table>
    </div>
  `;
}

/**
 * The raw textarea: uncontrolled, so a reload from disk can keep the cursor and scroll.
 * Its value is only ever set here (no `defaultValue`: re-rendering one resets the cursor).
 * @param {{doc: OpenDoc, label?: string, onKeyDown?: (e: KeyboardEvent) => void}} props
 */
export function RawText({ doc, label = "File text", onKeyDown }) {
  const area = useRef(/** @type {HTMLTextAreaElement | null} */ (null));
  const revision = doc.revision.value;
  useLayoutEffect(() => {
    const el = area.current;
    if (!el || el.value === doc.text.value) return;
    const { selectionStart, selectionEnd, scrollTop } = el;
    el.value = doc.text.value;
    el.setSelectionRange(Math.min(selectionStart, el.value.length), Math.min(selectionEnd, el.value.length));
    el.scrollTop = scrollTop;
  }, [revision]);
  return html`
    <textarea
      ref=${area}
      class="raw"
      aria-label=${label}
      spellcheck=${false}
      readOnly=${tree.value?.workspace.read_only ?? false}
      onInput=${(/** @type {InputEvent} */ e) => doc.edit(/** @type {HTMLTextAreaElement} */ (e.currentTarget).value)}
      onBlur=${() => void doc.flush()}
      onKeyDown=${onKeyDown}
    ></textarea>
  `;
}

/** @param {{text: string}} props */
function Preview({ text }) {
  const { frontmatter, body } = splitFrontmatter(text);
  return html`
    <article class="preview" aria-label="Preview">
      ${frontmatter !== null && html`<pre class="frontmatter">${frontmatter}</pre>`}
      <div class="markdown" dangerouslySetInnerHTML=${{ __html: renderMarkdown(body, resolveMention) }}></div>
    </article>
  `;
}

/** @param {string} path */
function parentOf(path) {
  const i = path.lastIndexOf("/");
  return i < 0 ? "" : path.slice(0, i);
}

/** @param {string} folder @param {string} name */
function join(folder, name) {
  return folder ? `${folder}/${name}` : name;
}
