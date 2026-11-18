// @ts-check
// The shell (SPEC §11.2): sidebar, top bar, banners, and the routed view.

import { signal } from "@preact/signals";
import { useEffect, useRef, useState } from "preact/hooks";
import { BannerStrip } from "./banners.js";
import { BookmarkLink, BookmarksPage } from "./bookmarks.js";
import { Dashboard } from "./dashboard.js";
import { EntityPage } from "./entity.js";
import { TYPES } from "./fields.js";
import { FilesPage } from "./files.js";
import { GlossaryPage } from "./glossary.js";
import { Icon } from "./icons.js";
import { CaptureDialog } from "./capture.js";
import { LifecycleDialog } from "./lifecycle.js";
import { fetchTemplates, NewDialog, openNew } from "./newform.js";
import { openPalette, Palette } from "./palette.js";
import { PeoplePage, PersonPage } from "./people.js";
import { PortfolioPage } from "./portfolio.js";
import { recents } from "./recent.js";
import { BrokenPage } from "./repair.js";
import { TrashPage } from "./trash.js";
import { route } from "./router.js";
import { SearchPage, typeIcon } from "./search.js";
import { SettingsPage } from "./settings.js";
import { html, openDoc, tree, useView } from "./state.js";
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

/** Whether the sidebar's New… menu is open; `N` opens it from anywhere but a text field. */
const newMenuOpen = signal(false);

/** @typedef {import("./newform.js").TemplateInfo} TemplateInfo */

export function App() {
  const current = route.value;
  useEffect(() => {
    document.addEventListener("keydown", onShortcut);
    return () => document.removeEventListener("keydown", onShortcut);
  }, []);
  return html`
    <div class="shell">
      <${Sidebar} active=${NAV_FOR[current.name] ?? current.name} />
      <div class="main">
        <${TopBar} />
        <${BannerStrip} />
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
  const openTodos = tree.value?.workspace.open_todos || null; // hidden at 0 and without Me
  return html`
    <nav class="sidebar" aria-label="Sections">
      <${WorkspaceHeader} />
      <div class="side-scroll">
        <ul class="side-nav">
          ${NAV.map(
            (item) => html`<li key=${item.route}>
              <${NavRow} item=${item} active=${active} count=${item.route === "todos" ? openTodos : null} />
            </li>`,
          )}
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
    <section class="side-section ${id}">
      <h2 id=${id}>${title}</h2>
      ${empty ? html`<p class="muted side-empty">${empty}</p>` : html`<ul aria-labelledby=${id}>${children}</ul>`}
    </section>
  `;
}

function WorkspaceHeader() {
  const path = tree.value?.workspace.path ?? "";
  return html`
    <div class="side-workspace" title=${path}>
      <span class="side-mark" aria-hidden="true">m</span>
      <span class="side-workspace-name">
        <strong>memex</strong>
        <span class="side-workspace-path">${path}</span>
      </span>
    </div>
  `;
}

/**
 * A section's row; `count` is the To-dos badge (Me's open To-dos), hidden when null.
 * @param {{item: {route: string, label: string, icon: string}, active: string, count?: number | null}} props
 */
function NavRow({ item, active, count = null }) {
  const current = item.route === active;
  return html`
    <a href="#/${item.route}" class="side-row ${current ? "active" : ""}" aria-current=${current ? "page" : undefined}>
      <${Icon} name=${item.icon} /><span class="side-label">${item.label}</span>
      ${count !== null && html`<span class="side-count" aria-label="${count} open">${count}</span>`}
    </a>
  `;
}

function TopBar() {
  void route.value; // subscribe: re-render on navigation, so Back/Forward know where they can go
  const history = /** @type {any} */ (window).navigation;
  const doc = openDoc.value;
  return html`
    <header class="topbar">
      <div class="history">
        <button type="button" class="icon-button" aria-label="Back" title="Back"
          disabled=${history ? !history.canGoBack : false} onClick=${() => window.history.back()}>
          <${Icon} name="chevron-left" />
        </button>
        <button type="button" class="icon-button" aria-label="Forward" title="Forward"
          disabled=${history ? !history.canGoForward : false} onClick=${() => window.history.forward()}>
          <${Icon} name="chevron-right" />
        </button>
      </div>
      <label class="search">
        <${Icon} name="search" />
        <input type="search" aria-label="Search" placeholder="Search notes, people, projects…" value=""
          onFocus=${(/** @type {FocusEvent} */ e) => {
            /** @type {HTMLInputElement} */ (e.currentTarget).blur();
            openPalette();
          }} />
        <kbd aria-hidden="true">Ctrl K</kbd>
      </label>
      <span class="topbar-spacer"></span>
      ${doc && html`<${SaveStatus} doc=${doc} />`}
    </header>
  `;
}

const SAVE_LABELS = { clean: "Saved", dirty: "Unsaved", saving: "Saving…", conflict: "Not saved", deleted: "Not saved" };

/** @param {{doc: import("./doc.js").OpenDoc}} props */
function SaveStatus({ doc }) {
  const state = doc.state.value;
  return html`<span class="save-status ${state}" data-state=${state} role="status">${SAVE_LABELS[state]}</span>`;
}

/**
 * `N` opens the New… menu, unless the user is typing or a dialog is open; Escape closes it.
 * @param {KeyboardEvent} e
 */
function onShortcut(e) {
  if (e.key === "Escape" && newMenuOpen.value) {
    newMenuOpen.value = false;
    return;
  }
  if (e.key !== "n" && e.key !== "N") return;
  if (e.ctrlKey || e.metaKey || e.altKey || e.defaultPrevented) return;
  const target = /** @type {HTMLElement | null} */ (e.target);
  if (target?.closest("input, textarea, select, [contenteditable]:not([contenteditable=false])")) return;
  if (document.querySelector("[role=dialog]")) return;
  e.preventDefault();
  newMenuOpen.value = true;
}

/** What each type's row says on the right of the New… menu. */
/** @type {Record<string, {text: string, mono?: boolean}>} */
const NEW_HINTS = {
  note: { text: "notes/", mono: true },
  deliverable: { text: "needs a Project" },
  person: { text: "Team Member" },
  todo: { text: "owner, requester" },
};
/** Rows after which the menu draws a rule. */
const NEW_GROUP_ENDS = new Set(["note", "deliverable"]);

/**
 * The New… menu (§11.7): a row per type, its other Templates as sub-rows. Each row
 * opens + New… with that Template.
 */
function NewMenu() {
  const open = newMenuOpen.value;
  const box = useRef(/** @type {HTMLDivElement | null} */ (null));
  const [variants, setVariants] = useState(/** @type {Record<string, TemplateInfo[]>} */ ({}));
  useEffect(() => {
    if (!open) return;
    box.current?.querySelector(/** @type {"button"} */ ("[role=menuitem]"))?.focus();
    let cancelled = false;
    Promise.all(TYPES.map((t) => fetchTemplates(t.key).catch(() => null))).then((lists) => {
      if (cancelled) return;
      /** @type {Record<string, TemplateInfo[]>} */
      const found = {};
      TYPES.forEach((t, i) => {
        const list = lists[i];
        found[t.key] = (list?.usable ?? []).filter((v) => v.key !== list?.fallback.key && v.source !== "blank");
      });
      setVariants(found);
    });
    /** @param {MouseEvent} e */
    const away = (e) => box.current?.contains(/** @type {Node} */ (e.target)) || (newMenuOpen.value = false);
    document.addEventListener("mousedown", away);
    return () => {
      cancelled = true;
      document.removeEventListener("mousedown", away);
    };
  }, [open]);

  /** @param {string} type @param {string} [template] */
  const create = (type, template) => {
    newMenuOpen.value = false;
    openNew(type, undefined, template);
  };

  /** @param {KeyboardEvent} e */
  function onKeyDown(e) {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const items = /** @type {HTMLElement[]} */ ([...(box.current?.querySelectorAll("[role=menuitem]") ?? [])]);
    const at = items.indexOf(/** @type {HTMLElement} */ (document.activeElement));
    items[(at + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length]?.focus();
  }

  return html`
    <div class="new-menu side-new" ref=${box}>
      <button type="button" class="new-button" aria-expanded=${open} aria-keyshortcuts="N"
        onClick=${() => (newMenuOpen.value = !open)}>
        <${Icon} name="plus" /><span class="side-label">New…</span><kbd aria-hidden="true">N</kbd>
      </button>
      ${open &&
      html`
        <div class="menu new-types" role="menu" aria-label="Create" onKeyDown=${onKeyDown}>
          <div class="new-types-head" aria-hidden="true"><span>Create</span><span>uses the ★ Template</span></div>
          ${TYPES.map((t) => {
            const hint = NEW_HINTS[t.key];
            return html`
              <button type="button" role="menuitem" aria-label=${t.label} class="new-type" onClick=${() => create(t.key)}>
                <${Icon} name=${typeIcon(t.key)} /><span class="new-type-label">${t.label}</span>
                ${hint && html` <span class="new-hint ${hint.mono ? "mono" : ""}">${hint.text}</span>`}
              </button>
              ${(variants[t.key] ?? []).map(
                (v) => html`
                  <button type="button" role="menuitem" aria-label="${t.label}: ${v.display_name}" class="new-variant"
                    onClick=${() => create(t.key, v.name)}>
                    <span class="new-type-label"><span class="faint">${t.label}: </span>${v.display_name}</span>
                    ${typeof v.fields.date === "string" && html` <span class="new-hint mono">${v.fields.date}-…</span>`}
                  </button>
                `,
              )}
              ${NEW_GROUP_ENDS.has(t.key) && html`<hr />`}
            `;
          })}
        </div>
      `}
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
