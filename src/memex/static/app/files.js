// @ts-check
// The Files page (SPEC §11.8), per "Files — raw editor" in Paper: the raw tree, and the raw
// whole-file editor (frontmatter included) with a line gutter and a live preview. The
// escape hatch for any file.

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "preact/hooks";
import { ApiError, describe, fileUrl, request } from "./api.js";
import { OpenDoc } from "./doc.js";
import { typeLabel } from "./fields.js";
import { fetchTemplates, openNew } from "./newform.js";
import { renderMarkdown, splitFrontmatter } from "./markdown.js";
import { outlineHtml, toggleBlock } from "./outline.js";
import { entityHref, fileHref, isUnder, navigate } from "./router.js";
import { Icon } from "./icons.js";
import { openLifecycle } from "./lifecycle.js";
import { html, openDoc, reloadTree, resolveMention, tree } from "./state.js";

/**
 * @typedef {import("./state.js").TreeFile} TreeFile
 * @typedef {import("./state.js").FileWarning} FileWarning
 * @typedef {{name: string, path: string, folders: Folder[], files: TreeFile[], others: string[], count: number}} Folder
 * @typedef {{kind: "file" | "folder", path: string}} Selection
 * @typedef {"new-file" | "new-folder" | "move"} Action
 */

/** The raw editor's line height in px: the gutter and the error line follow it. */
const LINE_PX = 22;

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
      <aside class="files-tree" aria-label="Files">
        <${TreeHead} selection=${selection} onSelect=${setSelection} />
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

/**
 * The tree pane's head: the Workspace, New file and New folder here, and with a folder
 * selected, its Rename / move and Delete.
 * @param {{selection: Selection | null, onSelect: (s: Selection | null) => void}} props
 */
function TreeHead({ selection, onSelect }) {
  const [action, setAction] = useState(/** @type {Action | null} */ (null));
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const folder = selection ? (selection.kind === "folder" ? selection.path : parentOf(selection.path)) : "";
  const folderSelected = selection?.kind === "folder" ? selection : null;
  const readOnly = tree.value?.workspace.read_only ?? false;

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
      } else if (action === "move" && folderSelected) {
        await movePath(folderSelected, name);
        onSelect({ kind: "folder", path: name });
      }
      setAction(null);
      setError(null);
    } catch (e) {
      setError(describe(e));
    }
  }

  async function remove() {
    if (!folderSelected) return;
    const failed = await removePath(folderSelected);
    if (!failed) onSelect(null);
    setError(failed);
  }

  return html`
    <div class="files-actions">
      <div class="tree-head">
        <span class="tree-root" title=${tree.value?.workspace.path}>${tree.value?.workspace.path ?? "Workspace"}</span>
        <div class="tree-tools">
          ${folderSelected &&
          html`<button type="button" class="tree-tool" aria-label="Rename or move folder" title="Rename or move ${folderSelected.path}"
              disabled=${readOnly} onClick=${() => setAction("move")}><${Icon} name="pencil" /></button>
            <button type="button" class="tree-tool" aria-label="Delete folder" title="Delete ${folderSelected.path} to the trash"
              disabled=${readOnly} onClick=${remove}><${Icon} name="trash-2" /></button>`}
          <button type="button" class="tree-tool" aria-label="New file" title="New file in ${folder || "the Workspace"}"
            disabled=${readOnly}
            onClick=${() => {
              // Inside a type folder a new file is an Entity of that type: use its form.
              const type = TYPE_FOLDERS[folder];
              if (type) openNew(type);
              else setAction("new-file");
            }}><${Icon} name="file-plus" /></button>
          <button type="button" class="tree-tool" aria-label="New folder" title="New folder in ${folder || "the Workspace"}"
            disabled=${readOnly} onClick=${() => setAction("new-folder")}><${Icon} name="folder-plus" /></button>
        </div>
      </div>
      ${action === "new-file" && html`<${NewNoteForm} folder=${folder} onDone=${() => setAction(null)} />`}
      ${action &&
      action !== "new-file" &&
      html`<${PathForm}
        key=${action}
        label=${action === "move" ? "New path" : `New folder in ${folder || "the Workspace"}`}
        initial=${action === "move" && folderSelected ? folderSelected.path : ""}
        onSubmit=${submit}
        onCancel=${() => setAction(null)}
      />`}
      ${error && html`<p class="error-text" role="alert">${error}</p>`}
    </div>
  `;
}

/**
 * Rename or move a file or folder; when it holds the open file, the editor follows (our
 * own move: the app never follows an outside rename).
 * @param {Selection} selection
 * @param {string} to
 */
async function movePath(selection, to) {
  const doc = openDoc.value;
  const holdsOpen = doc && isUnder(doc.path, selection.path);
  if (doc && holdsOpen) await doc.flush();
  await request("POST", "/api/move", { json: { from: selection.path, to } });
  await reloadTree();
  if (doc && holdsOpen) {
    doc.dispose();
    openDoc.value = null;
    navigate(fileHref(to + doc.path.slice(selection.path.length)));
  }
}

/**
 * Delete to the trash (§8.4), after a confirm. Something referring to a file opens the
 * guided delete; a folder is refused while anything inside is referred to from outside.
 * @param {Selection} selection
 * @returns {Promise<string | null>} why it failed, if it did
 */
async function removePath(selection) {
  const what = selection.kind === "folder" ? `the folder ${selection.path} and everything in it` : selection.path;
  if (!window.confirm(`Move ${what} to the trash?`)) return null;
  try {
    await request("DELETE", fileUrl(selection.path));
    if (openDoc.value && isUnder(openDoc.value.path, selection.path)) {
      openDoc.value.dispose();
      openDoc.value = null;
      navigate("#/files");
    }
    await reloadTree();
    return null;
  } catch (e) {
    const file = tree.value?.files.find((f) => f.path === selection.path);
    if (!(e instanceof ApiError && e.code === "has_references")) return describe(e);
    if (file) {
      openLifecycle("delete", { ...file, type: file.type ?? "note" }, "#/files");
      return null;
    }
    const referrers = e.body.impact?.referrers ?? [];
    return `${e.message}: ${referrers.join(", ")}. Remove those references first.`;
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
 * The Workspace tree: folders with how many files they hold, shut until opened or until
 * they hold the open file; the open file highlighted, with a dot when it has warnings.
 * Non-Markdown files are listed greyed and can't be opened (§2).
 * @param {{openPath: string | null, selection: Selection | null, onSelect: (s: Selection) => void}} props
 */
function TreeView({ openPath, selection, onSelect }) {
  const [opened, setOpened] = useState(/** @type {Set<string>} */ (new Set()));
  const [shut, setShut] = useState(/** @type {Set<string>} */ (new Set()));
  const data = tree.value;
  if (!data) return html`<p class="hint">Loading…</p>`;
  const root = buildTree(data.folders, data.files, data.other_files ?? []);

  /** @param {string} path */
  function expanded(path) {
    return !shut.has(path) && (opened.has(path) || (openPath !== null && isUnder(openPath, path)));
  }

  /** @param {string} path */
  function toggle(path) {
    const open = !expanded(path);
    const nextOpened = new Set(opened);
    const nextShut = new Set(shut);
    if (open) {
      nextOpened.add(path);
      nextShut.delete(path);
    } else {
      nextOpened.delete(path);
      nextShut.add(path);
    }
    setOpened(nextOpened);
    setShut(nextShut);
  }

  /** @param {Folder} folder @param {number} depth @returns {any} */
  function renderFolder(folder, depth) {
    return html`
      <ul role="group" class=${depth > 0 ? "tree-children" : undefined}>
        ${folder.folders.map((child) => {
          const isOpen = expanded(child.path);
          const selected = selection?.kind === "folder" && selection.path === child.path;
          return html`
            <li role="treeitem" aria-expanded=${isOpen} aria-selected=${selected}>
              <button
                type="button"
                class="tree-folder ${selected ? "selected" : ""}"
                aria-expanded=${isOpen}
                onClick=${() => {
                  onSelect({ kind: "folder", path: child.path });
                  toggle(child.path);
                }}
              >
                <${Icon} name=${isOpen ? "chevron-down" : "chevron-right"} />
                <${Icon} name="folder" />
                <span class="name">${child.name}</span>
                <span class="count">${child.count}</span>
              </button>
              ${isOpen && renderFolder(child, depth + 1)}
            </li>
          `;
        })}
        ${folder.files.map((file) => {
          const active = file.path === openPath;
          return html`
            <li role="treeitem" aria-selected=${active}>
              <a href=${fileHref(file.path)} class="tree-file ${active ? "selected" : ""} ${depth === 0 ? "top" : ""}"
                title=${file.title}>
                <${Icon} name="file-text" />
                <span class="name">${baseName(file.path)}</span>
                ${file.warnings.length > 0 &&
                html`<span class="warning-dot" role="img" aria-label="Has warnings" title=${file.warnings[0].message}></span>`}
              </a>
            </li>
          `;
        })}
        ${folder.others.map(
          (path) => html`
            <li role="treeitem" aria-disabled="true">
              <span class="tree-file other ${depth === 0 ? "top" : ""}" title="Not Markdown: listed, but not opened here">
                <${Icon} name="file" />
                <span class="name">${baseName(path)}</span>
                <span class="read-only">read-only</span>
              </span>
            </li>
          `,
        )}
      </ul>
    `;
  }

  return html`<nav class="tree" role="tree" aria-label="Workspace files">${renderFolder(root, 0)}</nav>`;
}

/**
 * @param {string[]} folders
 * @param {TreeFile[]} files
 * @param {string[]} others
 * @returns {Folder}
 */
function buildTree(folders, files, others) {
  /** @type {Map<string, Folder>} */
  const byPath = new Map();
  /** @type {Folder} */
  const root = { name: "", path: "", folders: [], files: [], others: [], count: 0 };
  byPath.set("", root);
  /** @param {string} path @returns {Folder} */
  function folderFor(path) {
    const found = byPath.get(path);
    if (found) return found;
    /** @type {Folder} */
    const folder = { name: baseName(path), path, folders: [], files: [], others: [], count: 0 };
    byPath.set(path, folder);
    folderFor(parentOf(path)).folders.push(folder);
    return folder;
  }
  /** Every folder up from `path` holds one more file. @param {string} path */
  function counted(path) {
    for (let p = parentOf(path); p; p = parentOf(p)) folderFor(p).count += 1;
  }
  for (const path of folders) folderFor(path);
  for (const file of files) {
    folderFor(parentOf(file.path)).files.push(file);
    counted(file.path);
  }
  for (const path of others) {
    folderFor(parentOf(path)).others.push(path);
    counted(path);
  }
  for (const folder of byPath.values()) {
    folder.folders.sort((a, b) => a.name.localeCompare(b.name));
    folder.files.sort((a, b) => a.path.localeCompare(b.path));
    folder.others.sort((a, b) => a.localeCompare(b));
  }
  return root;
}

/** @param {{path: string}} props */
function Editor({ path }) {
  const [loadError, setLoadError] = useState(/** @type {string | null} */ (null));
  const area = useRef(/** @type {HTMLTextAreaElement | null} */ (null));
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
  const errorLine = warnings.find((w) => w.line)?.line ?? null;

  /** Put the cursor at the start of a line, and bring it into view. @param {number} line */
  function gotoLine(line) {
    const el = area.current;
    if (!el) return;
    const start = el.value
      .split("\n")
      .slice(0, line - 1)
      .reduce((n, text) => n + text.length + 1, 0);
    el.focus();
    el.setSelectionRange(start, start);
    el.scrollTop = Math.max(0, (line - 1) * LINE_PX - el.clientHeight / 3);
  }

  return html`
    <div class="editor">
      <${FileHeader} path=${path} file=${file} />
      ${warnings.map((w) => html`<${WarningBar} warning=${w} onGoto=${gotoLine} />`)}
      <div class="split">
        <${CodeEditor} doc=${doc} area=${area} errorLine=${errorLine} />
        <${Preview} text=${doc.text.value} path=${path} file=${file} />
      </div>
    </div>
  `;
}

/**
 * The file's path and Id, with Rename / move, Delete and Open page ↗. A file outside the
 * tree (a Template, the config) gets just its path.
 * @param {{path: string, file: TreeFile | undefined}} props
 */
function FileHeader({ path, file }) {
  const [moving, setMoving] = useState(false);
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const readOnly = tree.value?.workspace.read_only ?? false;
  const dir = parentOf(path);

  /** @param {string} value */
  async function move(value) {
    const to = value.trim().replace(/^\/+/, "");
    if (!to || to === path) return setMoving(false);
    try {
      await movePath({ kind: "file", path }, to);
    } catch (e) {
      setError(describe(e));
    }
  }

  async function remove() {
    setError(await removePath({ kind: "file", path }));
  }

  return html`
    <header class="file-header">
      <div class="file-id">
        <h1 class="editor-path">${dir && html`<span class="dir">${dir}/</span>`}<span class="name">${baseName(path)}</span></h1>
        ${file && html`<p class="file-meta">${typeLabel(file.type ?? "note")} · Id <code>${file.id}</code></p>`}
      </div>
      ${file &&
      html`<div class="file-tools">
        <button type="button" class="tool" disabled=${readOnly} onClick=${() => setMoving(true)}>Rename / move</button>
        <button type="button" class="tool" disabled=${readOnly} onClick=${remove}>Delete</button>
        <a class="open-page" href=${entityHref(file.id)}>Open page<${Icon} name="arrow-up-right" /></a>
      </div>`}
    </header>
    ${moving && html`<${PathForm} label="New path" initial=${path} onSubmit=${move} onCancel=${() => setMoving(false)} />`}
    ${error && html`<p class="error-text file-error" role="alert">${error}</p>`}
  `;
}

const PARSE_PREFIX = /^Frontmatter doesn't parse:\s*/;

/**
 * A file's warning as a bar across the editor: rust when the frontmatter won't parse (its
 * fields are ignored), amber otherwise; with a line, a Go to line N.
 * @param {{warning: FileWarning, onGoto: (line: number) => void}} props
 */
function WarningBar({ warning, onGoto }) {
  const parse = warning.kind === "parse";
  const line = warning.line;
  return html`
    <div class="validation-bar ${parse ? "" : "warn"}" role="status">
      <${Icon} name="triangle-alert" />
      <p>
        ${parse
          ? html`<strong>Frontmatter won't parse</strong> — ${line ? `line ${line}: ` : ""}${warning.message
                .replace(PARSE_PREFIX, "")
                .replace(/[.!?]$/, "")}. The file still opens, saves and is searchable as text; its fields are ignored
              until this is fixed.`
          : html`${warning.message}${line ? ` (line ${line})` : ""}`}
      </p>
      ${line && html`<button type="button" class="goto-line" onClick=${() => onGoto(line)}>Go to line ${line}</button>`}
    </div>
  `;
}

/**
 * The raw text with a line-number gutter; the line a warning names is marked in both.
 * Lines don't wrap, so the gutter's numbers stay beside their lines.
 * @param {{doc: OpenDoc, area: import("preact").RefObject<HTMLTextAreaElement | null>, errorLine: number | null}} props
 */
function CodeEditor({ doc, area, errorLine }) {
  const box = useRef(/** @type {HTMLDivElement | null} */ (null));
  const gutter = useRef(/** @type {HTMLDivElement | null} */ (null));
  const count = doc.text.value.split("\n").length;

  function sync() {
    const top = area.current?.scrollTop ?? 0;
    if (gutter.current) gutter.current.scrollTop = top;
    box.current?.style.setProperty("--scroll", `${top}px`);
  }

  return html`
    <div class="code" ref=${box} style=${errorLine ? `--error-line: ${errorLine - 1}` : undefined}>
      <div class="gutter" ref=${gutter} aria-hidden="true">
        ${Array.from({ length: count }, (_, i) => html`<div class=${i + 1 === errorLine ? "error" : undefined}>${i + 1}</div>`)}
      </div>
      ${errorLine && errorLine <= count && html`<div class="line-mark" aria-hidden="true"></div>`}
      <${RawText} doc=${doc} area=${area} wrap="off" onScroll=${sync} />
    </div>
  `;
}

/**
 * The raw textarea: uncontrolled, so a reload from disk can keep the cursor and scroll.
 * Its value is only ever set here (no `defaultValue`: re-rendering one resets the cursor).
 * @param {{doc: OpenDoc, label?: string, onKeyDown?: (e: KeyboardEvent) => void,
 *   area?: import("preact").RefObject<HTMLTextAreaElement | null>, wrap?: "off" | "soft", onScroll?: () => void}} props
 */
export function RawText({ doc, label = "File text", onKeyDown, area: given, wrap, onScroll }) {
  const own = useRef(/** @type {HTMLTextAreaElement | null} */ (null));
  const area = given ?? own;
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
      wrap=${wrap}
      readOnly=${tree.value?.workspace.read_only ?? false}
      onInput=${(/** @type {InputEvent} */ e) => doc.edit(/** @type {HTMLTextAreaElement} */ (e.currentTarget).value)}
      onBlur=${() => void doc.flush()}
      onKeyDown=${onKeyDown}
      onScroll=${onScroll}
    ></textarea>
  `;
}

/**
 * The live preview, styled like the Entity page: the title, the frontmatter, then the body
 * as outline blocks. While the frontmatter won't parse, the title is the filename.
 * @param {{text: string, path: string, file: TreeFile | undefined}} props
 */
function Preview({ text, path, file }) {
  const { frontmatter, body } = splitFrontmatter(text);
  const broken = file?.warnings.some((w) => w.kind === "parse") ?? false;
  const workspace = tree.value;
  const rendered = useMemo(() => outlineHtml(renderMarkdown(body, resolveMention)), [body, workspace]);
  return html`
    <article class="preview" aria-label="Preview">
      <div class="preview-head">
        <span class="eyebrow">Preview</span>
        <span class="preview-note">updates as you type</span>
      </div>
      <h2 class="preview-title">${file?.title ?? baseName(path).replace(/\.md$/, "")}</h2>
      ${broken
        ? html`<p class="properties-unavailable">
            Properties unavailable — showing the filename as the title until the frontmatter parses
          </p>`
        : frontmatter !== null && frontmatter.trim() && html`<pre class="frontmatter">${frontmatter}</pre>`}
      <div class="markdown outline" onClick=${toggleBlock} dangerouslySetInnerHTML=${{ __html: rendered }}></div>
    </article>
  `;
}

/** @param {string} path */
function parentOf(path) {
  const i = path.lastIndexOf("/");
  return i < 0 ? "" : path.slice(0, i);
}

/** @param {string} path */
function baseName(path) {
  return path.slice(path.lastIndexOf("/") + 1);
}

/** @param {string} folder @param {string} name */
function join(folder, name) {
  return folder ? `${folder}/${name}` : name;
}
