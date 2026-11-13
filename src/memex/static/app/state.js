// @ts-check
// Client state (SPEC §11.1). The server is the only source of truth; the client holds
// exactly three things: the tree, the open document, and the current view's data.

import { signal } from "@preact/signals";
import { h } from "preact";
import htm from "htm";
import { describe, request } from "./api.js";

export const html = htm.bind(h);

/**
 * @typedef {{kind: string, message: string, line: number | null}} FileWarning
 * @typedef {{path: string, id: string, type: string | null, title: string, hash: string, warnings: FileWarning[]}} TreeFile
 * @typedef {{read_only: boolean, config_error: string | null, me_set: boolean}} WorkspaceStatus
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
