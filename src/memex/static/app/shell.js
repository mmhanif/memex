// @ts-check
// The shell (SPEC §11.2): icon rail, top bar, banners, and the routed view.

import { useState } from "preact/hooks";
import { describe, request } from "./api.js";
import { FilesPage } from "./files.js";
import { Icon } from "./icons.js";
import { fileHref, navigate, route } from "./router.js";
import { html, openDoc, reloadTree, tree, treeError } from "./state.js";

const RAIL = [
  { route: "home", label: "Home", icon: "house" },
  { route: "portfolio", label: "Portfolio", icon: "briefcase" },
  { route: "people", label: "People", icon: "users" },
  { route: "todos", label: "To-dos", icon: "square-check" },
  { route: "glossary", label: "Glossary", icon: "book-a" },
  { route: "bookmarks", label: "Bookmarks", icon: "bookmark" },
  { route: "files", label: "Files", icon: "folder" },
];

export function App() {
  const current = route.value;
  return html`
    <div class="shell">
      <${Rail} active=${current.name === "file" ? "files" : current.name} />
      <div class="main">
        <${TopBar} />
        <${Banners} />
        <main class="view">
          <${View} />
        </main>
      </div>
    </div>
  `;
}

/** @param {{active: string}} props */
function Rail({ active }) {
  return html`
    <nav class="rail" aria-label="Sections">
      ${RAIL.map(
        (item) => html`
          <a
            href="#/${item.route}"
            class=${item.route === active ? "active" : ""}
            title=${item.label}
            aria-label=${item.label}
            aria-current=${item.route === active ? "page" : undefined}
          >
            <${Icon} name=${item.icon} />
          </a>
        `,
      )}
      <a
        href="#/settings"
        class="rail-bottom ${active === "settings" ? "active" : ""}"
        title="Settings"
        aria-label="Settings"
      >
        <${Icon} name="settings" />
      </a>
    </nav>
  `;
}

function TopBar() {
  return html`
    <header class="topbar">
      <label class="search">
        <${Icon} name="search" />
        <input type="search" placeholder="Search (arrives with Ctrl-K)" disabled />
      </label>
      <${NewMenu} />
    </header>
  `;
}

function NewMenu() {
  const [open, setOpen] = useState(false);
  const [error, setError] = useState(/** @type {string | null} */ (null));

  async function newNote() {
    setOpen(false);
    const taken = new Set(tree.value?.files.map((f) => f.path) ?? []);
    let path = "notes/untitled.md";
    for (let n = 2; taken.has(path); n++) path = `notes/untitled-${n}.md`;
    try {
      await request("POST", "/api/files", { json: { path, content: "# Untitled\n" } });
      await reloadTree();
      navigate(fileHref(path));
      setError(null);
    } catch (e) {
      setError(describe(e));
    }
  }

  return html`
    <div class="new-menu">
      <button type="button" class="primary" aria-expanded=${open} onClick=${() => setOpen(!open)}>
        <${Icon} name="plus" /> New…
      </button>
      ${open &&
      html`
        <ul class="menu" role="menu">
          <li><button type="button" role="menuitem" onClick=${newNote}>Note</button></li>
          <li class="menu-note">Themes, Projects and the other types arrive with Entities.</li>
        </ul>
      `}
      ${error && html`<span class="error-text">${error}</span>`}
    </div>
  `;
}

function Banners() {
  const status = tree.value?.workspace;
  const doc = openDoc.value;
  return html`
    <div class="banners" role="status">
      ${treeError.value && html`<div class="banner warn">${treeError.value}</div>`}
      ${status?.read_only &&
      html`<div class="banner warn">
        This Workspace was written by a newer Memex, so it is read-only. Upgrade Memex to edit it.
      </div>`}
      ${status?.config_error &&
      html`<div class="banner warn">
        The Workspace config (.memex/config.yaml) doesn't parse: ${status.config_error}. Memex is
        using defaults until it is fixed.
      </div>`}
      ${status &&
      !status.me_set &&
      html`<div class="banner warn">Me isn't set: pick or create your Person in Settings.</div>`}
      ${doc?.problem.value &&
      html`<div class="banner warn" role="alert">
        <span>${doc.problem.value}</span>
        <button type="button" onClick=${() => void doc.save()}>Try again</button>
      </div>`}
    </div>
  `;
}

function View() {
  const current = route.value;
  if (current.name === "files") return html`<${FilesPage} path=${null} />`;
  if (current.name === "file") return html`<${FilesPage} path=${current.path ?? null} />`;
  return html`<${Placeholder} name=${current.name} />`;
}

/** @param {{name: string}} props */
function Placeholder({ name }) {
  const label = RAIL.find((r) => r.route === name)?.label ?? name;
  return html`
    <section class="placeholder">
      <h1>${label}</h1>
      <p>This view arrives in a later build step. Meanwhile, every file is on the <a href="#/files">Files</a> page.</p>
    </section>
  `;
}
