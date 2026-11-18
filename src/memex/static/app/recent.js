// @ts-check
// Recently opened Entities and files, in this browser only: a convenience (SPEC §9.6).
// The palette's empty state and the sidebar's Recent list (§11.2) show this same list.

import { effect, signal } from "@preact/signals";
import { entityHref, fileHref, route } from "./router.js";
import { typeIcon } from "./search.js";
import { tree } from "./state.js";

/** @typedef {{href: string, title: string, icon: string}} Recent */

const RECENT_MAX = 8;
const RECENT_KEY = "memex.recent";

/** Newest first, at most RECENT_MAX. */
export const recents = signal(readRecents());

/** @returns {Recent[]} */
function readRecents() {
  try {
    const stored = JSON.parse(window.localStorage.getItem(RECENT_KEY) ?? "[]");
    return Array.isArray(stored) ? stored.slice(0, RECENT_MAX) : [];
  } catch {
    return [];
  }
}

/** @param {Recent} recent */
function remember(recent) {
  const current = recents.peek();
  const top = current[0];
  if (top && top.href === recent.href && top.title === recent.title && top.icon === recent.icon) return;
  const next = [recent, ...current.filter((r) => r.href !== recent.href)].slice(0, RECENT_MAX);
  recents.value = next;
  try {
    window.localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    // Storage off or full: recents are only a convenience.
  }
}

effect(() => {
  const r = route.value;
  const files = tree.value?.files ?? [];
  if (r.name === "file" && r.path) {
    const found = files.find((f) => f.path === r.path);
    remember({ href: fileHref(r.path), title: found?.title ?? r.path, icon: typeIcon(found?.type ?? "note") });
  } else if ((r.name === "entity" || r.name === "person") && r.id) {
    const key = r.id.toLowerCase();
    const found = files.find((f) => f.id.toLowerCase() === key && f.type);
    if (!found) return;
    const href = entityHref(r.id, r.name === "person" ? "person" : undefined);
    remember({ href, title: found.title, icon: typeIcon(found.type ?? "note") });
  }
});
