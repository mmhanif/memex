// @ts-check
// Hash routes (SPEC §11.3). Leaving the editor saves first (§5.7), and asks before
// abandoning a conflict or a deleted file's text.

import { signal } from "@preact/signals";
import { openDoc } from "./state.js";

/** @typedef {{name: string, path?: string, id?: string}} Route */

/** @param {string} hash */
export function parseRoute(hash) {
  const raw = hash.replace(/^#\/?/, "");
  const [name, ...rest] = raw.split("/");
  if (name === "f" && rest.length) {
    return { name: "file", path: rest.map(decodeURIComponent).join("/") };
  }
  if (name === "e" && rest.length) return { name: "entity", id: decodeURIComponent(rest.join("/")) };
  return { name: name || "home" };
}

/**
 * True when `path` is `ancestor` or inside it.
 * @param {string} path
 * @param {string} ancestor
 */
export function isUnder(path, ancestor) {
  return path === ancestor || path.startsWith(`${ancestor}/`);
}

/** @param {string} path */
export function fileHref(path) {
  return `#/f/${path.split("/").map(encodeURIComponent).join("/")}`;
}

/** @param {string} id */
export function entityHref(id) {
  return `#/e/${encodeURIComponent(id)}`;
}

export const route = signal(/** @type {Route} */ (parseRoute(window.location.hash)));

let current = window.location.hash;

async function onHashChange() {
  const next = window.location.hash;
  if (next === current) return;
  const doc = openDoc.value;
  const target = parseRoute(next);
  const leavingDoc = doc && !doc.ownsRoute(target);
  if (doc && leavingDoc) {
    await doc.flush();
    if (
      doc.state.value !== "clean" &&
      !window.confirm("This file's edits haven't been saved. Leave anyway and lose them?")
    ) {
      window.history.replaceState(null, "", current);
      return;
    }
  }
  current = next;
  route.value = target;
}

window.addEventListener("hashchange", () => void onHashChange());

/** @param {string} hash */
export function navigate(hash) {
  window.location.hash = hash;
}
