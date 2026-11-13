// @ts-check
// Client state (SPEC §11.1). The server is the only source of truth; the client holds
// exactly three things: the tree, the open document, and the current view's data.

import { signal } from "@preact/signals";
import { h } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import htm from "htm";
import { describe, request } from "./api.js";

export const html = htm.bind(h);

/**
 * @typedef {{kind: string, message: string, line: number | null}} FileWarning
 * @typedef {{path: string, id: string, type: string | null, title: string, hash: string, warnings: FileWarning[]}} TreeFile
 * @typedef {{read_only: boolean, config_error: string | null, me_set: boolean, me: string | null}} WorkspaceStatus
 * @typedef {{folders: string[], files: TreeFile[], workspace: WorkspaceStatus}} Tree
 */

/** 1. The tree: reloaded on every `changed` event. */
export const tree = signal(/** @type {Tree | null} */ (null));
export const treeError = signal(/** @type {string | null} */ (null));

/** 2. The open document (§5.7). One tab edits one document at a time. */
export const openDoc = signal(/** @type {import("./doc.js").OpenDoc | null} */ (null));

/** 3. The current view's data is refetched when this ticks (route change or `changed`). */
export const viewVersion = signal(0);

export async function reloadTree() {
  try {
    tree.value = await request("GET", "/api/tree");
    treeError.value = null;
  } catch (error) {
    treeError.value = describe(error);
  }
}

/**
 * A Mention's target from the tree: one file with that Id (ignoring case), else null.
 * @type {import("./markdown.js").MentionResolver}
 */
export function resolveMention(id) {
  const key = id.toLowerCase();
  const found = tree.value?.files.filter((f) => f.id.toLowerCase() === key) ?? [];
  return found.length === 1 ? { title: found[0].title } : null;
}

/** Me's Id, or null while Me isn't set. */
export function meId() {
  return tree.value?.workspace.me ?? null;
}

/**
 * A view's data from `url`, refetched when the URL changes and on every `changed` event.
 * Keeps showing the last data while a refetch is in flight.
 * @template T
 * @param {string} url
 * @returns {{data: T | null, error: import("./api.js").ApiError | Error | null, reload: () => Promise<void>}}
 */
export function useView(url) {
  const [data, setData] = useState(/** @type {T | null} */ (null));
  const [error, setError] = useState(/** @type {any} */ (null));
  const latest = useRef(0); // only the newest request's answer is kept
  const version = viewVersion.value;

  async function reload() {
    const n = ++latest.current;
    try {
      const next = await request("GET", url);
      if (n !== latest.current) return;
      setData(next);
      setError(null);
    } catch (e) {
      if (n === latest.current) setError(e);
    }
  }

  useEffect(() => {
    void reload();
    return () => {
      latest.current += 1;
    };
  }, [url, version]);
  return { data, error, reload };
}
