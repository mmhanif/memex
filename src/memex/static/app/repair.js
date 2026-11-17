// @ts-check
// Broken Reference repair (SPEC §8.5): the `#/broken` page, and the same repairs inline on
// an Entity page. Each group offers Replace with…, Remove and Create; Replace and Remove
// show the impact preview first, then apply against its hashes.

import { useState } from "preact/hooks";
import { describe, request } from "./api.js";
import { typeLabel, useCandidates } from "./fields.js";
import { ImpactList } from "./lifecycle.js";
import { entityHref, fileHref } from "./router.js";
import { html, reloadTree, tree, useView, viewVersion } from "./state.js";

/**
 * @typedef {{path: string, id: string | null, title: string, type: string | null, field: string}} Use
 * @typedef {{id: string, status: "missing" | "ambiguous", uses: Use[], create_types: string[],
 *   types: string[]}} Group
 * @typedef {import("./lifecycle.js").Outcome} Outcome
 * @typedef {{action: "replace" | "remove", replacement: string | null, outcome: Outcome}} Pending
 */

const BROKEN_URL = "/api/broken-references";

export function BrokenPage() {
  const { data, error } = useView(BROKEN_URL);
  const groups = /** @type {{groups: Group[]} | null} */ (data)?.groups;
  return html`
    <section class="repair-page">
      <h1>Broken references</h1>
      <p class="hint">References and [[Mentions]] whose Id names no file, or more than one. Nothing is fixed
        automatically: pick a repair for each.</p>
      ${error && html`<p class="error-text" role="alert">${describe(error)}</p>`}
      ${groups && !groups.length && html`<p class="muted">No broken references.</p>`}
      ${groups?.map((g) => html`<${BrokenGroup} key=${g.id} group=${g} />`)}
    </section>
  `;
}

/**
 * The repairs for an Entity page's own Broken References (§11.5): the same groups,
 * filtered to the Ids it names.
 * @param {{ids: string[]}} props
 */
export function InlineRepairs({ ids }) {
  const { data } = useView(BROKEN_URL);
  const wanted = new Set(ids.map((i) => i.toLowerCase()));
  const groups = /** @type {{groups: Group[]} | null} */ (data)?.groups.filter((g) => wanted.has(g.id.toLowerCase()));
  if (!groups?.length) return null;
  return html`<div class="inline-repairs">${groups.map((g) => html`<${BrokenGroup} key=${g.id} group=${g} compact />`)}</div>`;
}

/** @param {Use} use */
function useHref(use) {
  return use.id === null || use.type === null ? "#/settings" : entityHref(use.id, use.type);
}

/** @param {{group: Group, compact?: boolean}} props */
function BrokenGroup({ group, compact = false }) {
  const candidates = useCandidates();
  const [replacement, setReplacement] = useState("");
  const [createType, setCreateType] = useState(group.create_types[0] ?? "");
  const [pending, setPending] = useState(/** @type {Pending | null} */ (null));
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const [busy, setBusy] = useState(false);
  const readOnly = tree.value?.workspace.read_only ?? false;
  const fits = candidates.filter((c) => group.types.includes(c.type) && c.id.toLowerCase() !== group.id.toLowerCase());

  /** @param {Record<string, any>} json */
  async function send(json) {
    setBusy(true);
    try {
      const outcome = /** @type {Outcome} */ (await request("POST", "/api/broken-references/repair", { json: { id: group.id, ...json } }));
      setError(null);
      return outcome;
    } catch (e) {
      setError(describe(e));
      return null;
    } finally {
      setBusy(false);
    }
  }

  /** @param {Outcome | null} outcome */
  async function finish(outcome) {
    if (!outcome) return;
    setPending(null);
    if (outcome.skipped.length) {
      setError(`Skipped: ${outcome.skipped.map((s) => `${s.path} (${s.message})`).join("; ")}`);
    }
    await reloadTree();
    viewVersion.value += 1;
  }

  /** @param {"replace" | "remove"} action */
  async function preview(action) {
    const r = action === "replace" ? replacement : null;
    const outcome = await send({ action, replacement: r });
    if (outcome) setPending({ action, replacement: r, outcome });
  }

  async function confirm() {
    if (!pending) return;
    const { action, replacement: r, outcome } = pending;
    await finish(await send({ action, replacement: r, dry_run: false, hashes: outcome.hashes }));
  }

  const creatable = group.create_types.length > 0;
  const blocked = pending?.action === "remove" ? pending.outcome.impact.blocked : [];
  return html`
    <article class="broken-group ${compact ? "compact" : ""}" aria-label=${`Broken reference ${group.id}`}>
      <h2><code>${group.id}</code> <span class="status status-blocked">${group.status}</span></h2>
      ${!compact &&
      html`<ul>
        ${group.uses.map(
          (u) => html`<li><a href=${useHref(u)}>${u.title}</a> <span class="muted">${u.field === "mention" ? "[[Mention]]" : u.field}</span>
            ${u.id !== null && html` · <a class="muted" href=${fileHref(u.path)}>${u.path}</a>`}</li>`,
        )}
      </ul>`}
      ${!readOnly &&
      !pending &&
      html`<div class="repair-actions">
        <span>
          <select aria-label="Replace with" value=${replacement}
            onChange=${(/** @type {Event} */ e) => setReplacement(/** @type {HTMLSelectElement} */ (e.currentTarget).value)}>
            <option value="">Replace with…</option>
            ${fits.map((c) => html`<option value=${c.id}>${c.title} (${typeLabel(c.type)})</option>`)}
          </select>
          <button type="button" disabled=${busy || !replacement} onClick=${() => preview("replace")}>Replace…</button>
        </span>
        <button type="button" disabled=${busy} onClick=${() => preview("remove")}>Remove…</button>
        <span title=${creatable ? "" : group.status === "ambiguous" ? "A file already has this Id" : "The references disagree about the type"}>
          ${group.create_types.length > 1 &&
          html`<select aria-label="Type to create" value=${createType}
            onChange=${(/** @type {Event} */ e) => setCreateType(/** @type {HTMLSelectElement} */ (e.currentTarget).value)}>
            ${group.create_types.map((t) => html`<option value=${t}>${typeLabel(t)}</option>`)}
          </select>`}
          <button type="button" disabled=${busy || !creatable}
            onClick=${async () => finish(await send({ action: "create", type: createType, dry_run: false }))}>
            Create${group.create_types.length === 1 ? ` ${typeLabel(group.create_types[0])}` : ""}
          </button>
        </span>
      </div>`}
      ${pending &&
      html`<div class="repair-preview">
        <${ImpactList} impact=${pending.outcome.impact} />
        ${blocked.length > 0 &&
        html`<p class="hint">Remove is blocked by required references:
          ${blocked.map((b) => `${b.title} (${b.field})`).join(", ")}. Use Replace with… instead.</p>`}
        <div class="repair-actions">
          <button type="button" onClick=${() => setPending(null)}>Cancel</button>
          <button type="button" class="primary" disabled=${busy || blocked.length > 0} onClick=${confirm}>
            ${pending.action === "replace" ? "Replace" : "Remove"}
          </button>
        </div>
      </div>`}
      ${error && html`<p class="error-text" role="alert">${error}</p>`}
    </article>
  `;
}
