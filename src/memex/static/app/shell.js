// @ts-check
// The shell (SPEC §11.2): icon rail, top bar, banners, and the routed view.

import { useState } from "preact/hooks";
import { Dashboard } from "./dashboard.js";
import { EntityPage } from "./entity.js";
import { TYPES } from "./fields.js";
import { FilesPage } from "./files.js";
import { Icon } from "./icons.js";
import { NewDialog, openNew } from "./newform.js";
import { PeoplePage, PersonPage } from "./people.js";
import { PortfolioPage } from "./portfolio.js";
import { route } from "./router.js";
import { SettingsPage } from "./settings.js";
import { html, openDoc, tree, treeError } from "./state.js";
import { TodosPage } from "./todos.js";

const RAIL = [
  { route: "home", label: "Home", icon: "house" },
  { route: "portfolio", label: "Portfolio", icon: "briefcase" },
  { route: "people", label: "People", icon: "users" },
  { route: "todos", label: "To-dos", icon: "square-check" },
  { route: "glossary", label: "Glossary", icon: "book-a" },
  { route: "bookmarks", label: "Bookmarks", icon: "bookmark" },
  { route: "files", label: "Files", icon: "folder" },
];

/** Routes that light up another route's rail icon. */
/** @type {Record<string, string>} */
const RAIL_FOR = { file: "files", person: "people" };

export function App() {
  const current = route.value;
  return html`
    <div class="shell">
      <${Rail} active=${RAIL_FOR[current.name] ?? current.name} />
      <div class="main">
        <${TopBar} />
        <${Banners} />
        <main class="view">
          <${View} />
        </main>
      </div>
      <${NewDialog} />
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
  return html`
    <div class="new-menu">
      <button type="button" class="primary" aria-expanded=${open} onClick=${() => setOpen(!open)}>
        <${Icon} name="plus" /> New…
      </button>
      ${open &&
      html`
        <ul class="menu" role="menu" onKeyDown=${(/** @type {KeyboardEvent} */ e) => e.key === "Escape" && setOpen(false)}>
          ${TYPES.map(
            (t) => html`<li>
              <button type="button" role="menuitem" onClick=${() => {
                setOpen(false);
                openNew(t.key);
              }}>${t.label}</button>
            </li>`,
          )}
        </ul>
      `}
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
  if (current.name === "settings") return html`<${SettingsPage} />`;
  if (current.name === "home") return html`<${Dashboard} />`;
  if (current.name === "todos") return html`<${TodosPage} view=${current.view ?? "mine"} />`;
  if (current.name === "people") return html`<${PeoplePage} />`;
  if (current.name === "portfolio") return html`<${PortfolioPage} view=${current.view ?? "board"} />`;
  if (current.name === "person" && current.id) return html`<${PersonPage} key=${current.id} id=${current.id} />`;
  if (current.name === "entity" && current.id) return html`<${EntityPage} key=${current.id} id=${current.id} />`;
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
