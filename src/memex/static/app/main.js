// @ts-check
// Entry point: mount the shell, load the tree, and follow changes on disk (SPEC §5.6, §5.7).

import { render } from "preact";
import { connectEvents } from "./events.js";
import { isUnder } from "./router.js";
import { App } from "./shell.js";
import { html, openDoc, reloadTree, viewVersion } from "./state.js";

/** Coarse invalidation: reload the tree and the view, and recheck the open file. */
function resync() {
  void reloadTree();
  viewVersion.value += 1;
  void openDoc.value?.recheck();
}

connectEvents({
  onChanged(changes) {
    void reloadTree();
    viewVersion.value += 1;
    const doc = openDoc.value;
    if (!doc) return;
    for (const change of changes) {
      if (change.path === doc.path) doc.onRemoteChange(change.hash);
      // A folder holding the open file moved or went.
      else if (isUnder(doc.path, change.path)) void doc.recheck();
    }
  },
  onReconnect: resync,
});

window.addEventListener("focus", resync);

// Save immediately when the tab is hidden or closed (§5.7).
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") void openDoc.value?.flush(true);
});
window.addEventListener("pagehide", () => void openDoc.value?.flush(true));

// "Leave site?" while there are unsaved edits, a save in flight, or a banner showing.
window.addEventListener("beforeunload", (event) => {
  if (openDoc.value?.guarded) event.preventDefault();
});

if (!window.location.hash) window.location.replace("#/home");
void reloadTree();
const root = document.getElementById("app");
if (root) render(html`<${App} />`, root);
