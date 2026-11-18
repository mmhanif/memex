// @ts-check
// The banner strip (SPEC §11.2): one strip under the top bar, full width of Main.
// Workspace-wide banners (Me not set, config error, read-only) stay until the cause is
// fixed; file banners belong to the open document and pause its auto-save (§5.7).

import { useEffect, useState } from "preact/hooks";
import { describe } from "./api.js";
import { BodyDoc } from "./doc.js";
import { Icon } from "./icons.js";
import { openNew } from "./newform.js";
import { fileHref, navigate } from "./router.js";
import { html, openDoc, tree, treeError } from "./state.js";

const CONFIG = ".memex/config.yaml";

export function BannerStrip() {
  const doc = openDoc.value;
  return html`
    <div class="banner-strip">
      <${WorkspaceBanners} />
      ${doc && html`<${DocBanners} key=${doc.path} doc=${doc} />`}
    </div>
  `;
}

function WorkspaceBanners() {
  const status = tree.value?.workspace;
  return html`
    <div role="status">
      ${treeError.value &&
      html`<${Banner} tone="rust" icon="triangle-alert"><strong>Memex isn't answering.</strong> ${treeError.value}<//>`}
      ${status?.read_only &&
      html`<${Banner} tone="neutral" icon="lock">
        <strong>Read-only.</strong> This Workspace is format ${status.format} and Memex ${status.version} understands
        format ${status.supported_format}. You can read and search; nothing can be saved. Quit Memex, then run
        ${" "}<code>pipx upgrade memex</code>.
      <//>`}
      ${status?.config_error &&
      html`<${Banner}
        tone="rust"
        icon="triangle-alert"
        actions=${html`<a class="button" href=${fileHref(CONFIG)}>Open config.yaml</a>`}
      >
        <strong>Workspace config won't parse</strong>${lineSuffix(status.config_error_line)}:
        ${" "}${status.config_error.replace(/[.!?]$/, "")}.
        Running on defaults, so Me is unset; Settings is read-only until it's fixed.
      <//>`}
      ${status && !status.me_set && !status.config_error && html`<${MeBanner} written=${status.me_ref} />`}
    </div>
  `;
}

/** @param {{written: string | null}} props */
function MeBanner({ written }) {
  const actions = html`
    <a class="button solid" href="#/settings">Pick a Person</a>
    <button type="button" onClick=${() => openNew("person")}>Create Person</button>
  `;
  return html`
    <${Banner} tone="amber" icon="user" actions=${actions}>
      <strong>Me isn't set: pick or create.</strong>
      ${" "}${written ? html`<code>me: ${written}</code> matches no Person.` : "The Workspace config names no one."}
      ${" "}Waiting-on views and quick-add defaults are paused until it does.
    <//>
  `;
}

/**
 * The open document's banners: Updated from disk, conflict, deleted, and a failed save.
 * @param {{doc: import("./doc.js").OpenDoc}} props
 */
function DocBanners({ doc }) {
  const [rows, setRows] = useState(/** @type {import("./doc.js").DiffRow[] | null} */ (null));
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const state = doc.state.value;
  const problem = doc.problem.value;
  useEffect(() => {
    if (state !== "conflict") setRows(null);
  }, [state]);

  const title = tree.value?.files.find((f) => f.path === doc.path)?.title ?? doc.path;

  async function compare() {
    try {
      setRows(await doc.compare());
    } catch (e) {
      setError(describe(e));
    }
  }

  function close() {
    doc.dispose();
    openDoc.value = null;
    navigate(doc instanceof BodyDoc ? "#/home" : "#/files");
  }

  return html`
    ${doc.notice.value && html`<div role="status"><${Banner} tone="info">${doc.notice.value}<//></div>`}
    ${state === "conflict" &&
    html`<${Banner}
      tone="rust conflict"
      icon="git-merge"
      alert
      actions=${html`
        <button type="button" onClick=${() => doc.reload()}>Reload</button>
        <button type="button" onClick=${() => void doc.keepMine()}>Keep mine</button>
        <button type="button" class="solid" onClick=${compare}>Compare</button>
      `}
    >
      <strong>${title} changed on disk</strong> while you had unsaved edits. Your edits are still here; nothing has
      been saved.
    <//>`}
    ${state === "deleted" &&
    html`<${Banner}
      tone="rust conflict"
      icon="file-x"
      alert
      actions=${html`
        ${doc.canRecreate &&
        html`<button type="button" class="solid" onClick=${() => void doc.recreate()}>Recreate</button>`}
        <button type="button" onClick=${close}>Close</button>
      `}
    >
      <strong><code>${doc.path}</code> was deleted or moved outside Memex.</strong> The editor kept its text. Memex
      doesn't follow renames.
    <//>`}
    ${problem &&
    html`<${Banner}
      tone=${problem.locked ? "amber" : "rust"}
      icon=${problem.locked ? "lock" : "triangle-alert"}
      alert
      actions=${html`<button type="button" class="solid" onClick=${() => void doc.retry()}>Retry</button>`}
    >
      <strong>Couldn't save ${title}:</strong> ${problem.reason}
    <//>`}
    ${error && html`<p class="error-text">${error}</p>`}
    ${rows && state === "conflict" && html`<${DiffView} rows=${rows} onClose=${() => setRows(null)} />`}
  `;
}

/**
 * One banner: a tone, an icon, the message, and its actions on the right.
 * @param {{tone: string, icon?: string, alert?: boolean, actions?: any, children?: any}} props
 */
function Banner({ tone, icon, alert = false, actions, children }) {
  return html`
    <div class="banner ${tone}" role=${alert ? "alert" : undefined}>
      ${icon && html`<${Icon} name=${icon} />`}
      <p class="banner-text">${children}</p>
      ${actions && html`<div class="banner-actions">${actions}</div>`}
    </div>
  `;
}

/**
 * " (line 7)" after a message, when the line is known.
 * @param {number | null} line
 */
export function lineSuffix(line) {
  return line ? ` (line ${line})` : "";
}

/** @param {{rows: import("./doc.js").DiffRow[], onClose: () => void}} props */
function DiffView({ rows, onClose }) {
  return html`
    <div class="diff">
      <div class="diff-head">
        <span>On disk</span><span>Mine</span>
        <button type="button" title="Close" aria-label="Close" onClick=${onClose}><${Icon} name="x" /></button>
      </div>
      <table>
        <tbody>
          ${rows.map(
            (row) => html`
              <tr class="diff-${row.kind}">
                <td class="disk">${row.disk ?? ""}</td>
                <td class="mine">${row.mine ?? ""}</td>
              </tr>
            `,
          )}
        </tbody>
      </table>
    </div>
  `;
}
