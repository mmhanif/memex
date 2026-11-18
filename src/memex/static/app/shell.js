// @ts-check
// The shell (SPEC §11.2): sidebar, top bar, banners, and the routed view.

import { useState } from "preact/hooks";
import { BookmarkLink, BookmarksPage } from "./bookmarks.js";
import { Dashboard } from "./dashboard.js";
import { EntityPage } from "./entity.js";
import { TYPES } from "./fields.js";
import { FilesPage } from "./files.js";
import { GlossaryPage } from "./glossary.js";
import { Icon } from "./icons.js";
import { CaptureDialog } from "./capture.js";
import { LifecycleDialog } from "./lifecycle.js";
import { NewDialog, openNew } from "./newform.js";
import { openPalette, Palette } from "./palette.js";
import { PeoplePage, PersonPage } from "./people.js";
import { PortfolioPage } from "./portfolio.js";
import { recents } from "./recent.js";
import { BrokenPage } from "./repair.js";
import { TrashPage } from "./trash.js";
import { route } from "./router.js";
import { SearchPage } from "./search.js";
import { SettingsPage } from "./settings.js";
import { html, openDoc, tree, treeError, useView } from "./state.js";
import { TodosPage } from "./todos.js";

const NAV = [
  { route: "home", label: "Home", icon: "house" },
  { route: "portfolio", label: "Portfolio", icon: "briefcase" },
  { route: "people", label: "People", icon: "users" },
  { route: "todos", label: "To-dos", icon: "square-check" },
  { route: "glossary", label: "Glossary", icon: "book-a" },
  { route: "bookmarks", label: "Bookmarks", icon: "bookmark" },
  { route: "files", label: "Files", icon: "folder" },
];
const SETTINGS = { route: "settings", label: "Settings", icon: "settings" };
const BOOKMARKED_MAX = 10;

/** Routes that light up another route's sidebar row. */
/** @type {Record<string, string>} */
const NAV_FOR = { file: "files", person: "people" };

export function App() {
  const current = route.value;
  return html`
    <div class="shell">
      <${Sidebar} active=${NAV_FOR[current.name] ?? current.name} />
      <div class="main">
        <${TopBar} />
        <${Banners} />
        <main class="view">
          <${View} />
        </main>
      </div>
      <${NewDialog} />
      <${LifecycleDialog} />
      <${CaptureDialog} />
      <${Palette} />
    </div>
  `;
}

/** @param {{active: string}} props */
function Sidebar({ active }) {
  return html`
    <nav class="sidebar" aria-label="Sections">
      <div class="side-scroll">
        <ul class="side-nav">
          ${NAV.map((item) => html`<li key=${item.route}><${NavRow} item=${item} active=${active} /></li>`)}
        </ul>
        <${Bookmarked} />
        <${Recent} />
      </div>
      <div class="side-bottom">
        <${NewMenu} />
        <${NavRow} item=${SETTINGS} active=${active} />
      </div>
    </nav>
  `;
}

function Bookmarked() {
  const { data, error } = useView("/api/bookmarks");
  const view = /** @type {import("./bookmarks.js").BookmarksView | null} */ (data);
  const all = view?.lines.flatMap((n) => (n.bookmark ? [n.bookmark] : [])) ?? [];
  const empty = error && !view ? "Bookmarks couldn't be loaded" : view && !all.length ? "No Bookmarks yet" : null;
  return html`
    <${SideSection} title="Bookmarked" empty=${empty}>
      ${all.slice(0, BOOKMARKED_MAX).map(
        (b) => html`<li key=${b.line}><${BookmarkLink} bookmark=${b} class="side-row" /></li>`,
      )}
      ${all.length > BOOKMARKED_MAX &&
      html`<li><a href="#/bookmarks" class="side-row side-more">All Bookmarks →</a></li>`}
    <//>
  `;
}

function Recent() {
  const list = recents.value;
  return html`
    <${SideSection} title="Recent" empty=${list.length ? null : "Nothing opened yet"}>
      ${list.map(
        (r) => html`<li key=${r.href}>
          <a href=${r.href} class="side-row"><${Icon} name=${r.icon} /><span>${r.title}</span></a>
        </li>`,
      )}
    <//>
  `;
}

/**
 * A titled list in the sidebar; `empty` replaces the list when set.
 * @param {{title: string, empty: string | null, children?: any}} props
 */
function SideSection({ title, empty, children }) {
  const id = `side-${title.toLowerCase()}`;
  return html`
    <section class="side-section">
      <h2 id=${id}>${title}</h2>
      ${empty ? html`<p class="muted side-empty">${empty}</p>` : html`<ul aria-labelledby=${id}>${children}</ul>`}
    </section>
  `;
}

/** @param {{item: {route: string, label: string, icon: string}, active: string}} props */
function NavRow({ item, active }) {
  const current = item.route === active;
  return html`
    <a href="#/${item.route}" class="side-row ${current ? "active" : ""}" aria-current=${current ? "page" : undefined}>
      <${Icon} name=${item.icon} /><span>${item.label}</span>
    </a>
  `;
}

function TopBar() {
  return html`
    <header class="topbar">
      <label class="search">
        <${Icon} name="search" />
        <input type="search" aria-label="Search" placeholder="Search (Ctrl-K)" value=""
          onFocus=${(/** @type {FocusEvent} */ e) => {
            /** @type {HTMLInputElement} */ (e.currentTarget).blur();
            openPalette();
          }} />
      </label>
    </header>
  `;
}

function NewMenu() {
  const [open, setOpen] = useState(false);
  return html`
    <div class="new-menu side-new">
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
  if (current.name === "portfolio") return html`<${PortfolioPage} view=${current.view ?? "board"} query=${current.query} />`;
  if (current.name === "broken") return html`<${BrokenPage} />`;
  if (current.name === "trash") return html`<${TrashPage} />`;
  if (current.name === "glossary") return html`<${GlossaryPage} />`;
  if (current.name === "bookmarks") return html`<${BookmarksPage} query=${current.query ?? new URLSearchParams()} />`;
  if (current.name === "search") return html`<${SearchPage} query=${current.query ?? new URLSearchParams()} />`;
  if (current.name === "person" && current.id) return html`<${PersonPage} key=${current.id} id=${current.id} />`;
  if (current.name === "entity" && current.id) return html`<${EntityPage} key=${current.id} id=${current.id} />`;
  return html`<${Placeholder} name=${current.name} />`;
}

/** @param {{name: string}} props */
function Placeholder({ name }) {
  const label = NAV.find((r) => r.route === name)?.label ?? name;
  return html`
    <section class="placeholder">
      <h1>${label}</h1>
      <p>This view arrives in a later build step. Meanwhile, every file is on the <a href="#/files">Files</a> page.</p>
    </section>
  `;
}
