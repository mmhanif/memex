// @ts-check
// Broken Reference repair (SPEC §8.5), per "Broken references" in Paper: the `#/broken`
// page, and the same repairs inline on an Entity page. Each group is an outline block: the
// mono Id, a missing/ambiguous badge, what its references imply, and Replace with…, Remove
// and Create (Rename id… when several files claim the Id). Under it, a row per occurrence.
// Replace and Remove show the impact preview first, then apply against its hashes.

import { useState } from "preact/hooks";
import { describe, request } from "./api.js";
import { typeLabel, useCandidates } from "./fields.js";
import { ImpactList } from "./lifecycle.js";
import { entityHref, fileHref } from "./router.js";
import { html, reloadTree, tree, useView, viewVersion } from "./state.js";

/**
 * @typedef {{path: string, id: string | null, title: string, type: string | null, field: string,
 *   snippet: [string, string, string] | null, targets: string[]}} Use
 * @typedef {{id: string, title: string, type: string, path: string}} FileRef
 * @typedef {{id: string, status: "missing" | "ambiguous", uses: Use[], create_types: string[],
 *   types: string[], claimants: FileRef[]}} Group
 * @typedef {import("./lifecycle.js").Outcome} Outcome
 * @typedef {{action: "replace" | "remove", replacement: string | null, outcome: Outcome}} Pending
 */

const BROKEN_URL = "/api/broken-references";
const MENTION = "mention";
const ME = "me";
const ALL_TYPES = 7; // six Entity types and Note: a Mention names any of them

/** @param {number} n @param {string} one @param {string} [many] */
const count = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

export function BrokenPage() {
  const { data, error } = useView(BROKEN_URL);
  const groups = /** @type {{groups: Group[]} | null} */ (data)?.groups;
  const refs = groups?.reduce((n, g) => n + g.uses.length, 0) ?? 0;
  return html`
    <section class="page repair-page broken-page">
      <header class="repair-head">
        <p class="eyebrow">${groups ? `${count(groups.length, "Id")} · ${count(refs, "reference")}` : " "}</p>
        <h1 class="title">Broken references</h1>
      </header>
      <p class="lede">References whose Id matches no Entity, or more than one. Each repair rewrites every
        occurrence in one go; nothing is guessed for you.</p>
      ${error && html`<p class="error-text" role="alert">${describe(error)}</p>`}
      ${groups && !groups.length && html`<p class="block-empty">No Broken References.</p>`}
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

/** @param {string[]} types */
const typeList = (types) => types.map(typeLabel).join(" or ");

/**
 * What a group's references say the Id should be: "implies Person", "any type",
 * "Theme or Person?" when they disagree, "2 files claim it" when ambiguous.
 * @param {Group} group
 */
function groupMeta(group) {
  const refs = count(group.uses.length, "ref");
  if (group.status === "ambiguous") return `${group.claimants.length} files claim it · ${refs}`;
  if (group.types.length >= ALL_TYPES) return `any type · ${refs}`;
  if (group.types.length) return `implies ${typeList(group.types)} · ${refs}`;
  return `${typeList(disagreeing(group))}? · ${refs}`;
}

/** The types the uses ask for when they disagree, in the order they're written. @param {Group} group */
function disagreeing(group) {
  return [...new Set(group.uses.filter((u) => u.field !== MENTION).flatMap((u) => u.targets))];
}

const CREATE_OFF = "Create is off because the references imply different types. Replace or Remove one side first.";

/** @param {{group: Group, compact?: boolean}} props */
function BrokenGroup({ group, compact = false }) {
  const candidates = useCandidates();
  const [createType, setCreateType] = useState(group.create_types[0] ?? "");
  const [pending, setPending] = useState(/** @type {Pending | null} */ (null));
  const [renaming, setRenaming] = useState(false);
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const [busy, setBusy] = useState(false);
  const readOnly = tree.value?.workspace.read_only ?? false;
  const fits = candidates.filter((c) => group.types.includes(c.type) && c.id.toLowerCase() !== group.id.toLowerCase());
  const ambiguous = group.status === "ambiguous";
  const creatable = group.create_types.length > 0;
  const reasonId = `create-off-${group.id}`;

  /** @param {Record<string, any>} json @param {string} [url] */
  async function send(json, url = "/api/broken-references/repair") {
    setBusy(true);
    try {
      const outcome = await request("POST", url, { json: { id: group.id, ...json } });
      setError(null);
      return outcome;
    } catch (e) {
      setError(describe(e));
      return null;
    } finally {
      setBusy(false);
    }
  }

  /** @param {Outcome | {path: string} | null} outcome */
  async function finish(outcome) {
    if (!outcome) return;
    setPending(null);
    setRenaming(false);
    if ("skipped" in outcome && outcome.skipped.length) {
      setError(`Skipped: ${outcome.skipped.map((s) => `${s.path} (${s.message})`).join("; ")}`);
    }
    await reloadTree();
    viewVersion.value += 1;
  }

  /** @param {"replace" | "remove"} action @param {string | null} [replacement] */
  async function preview(action, replacement = null) {
    const outcome = /** @type {Outcome | null} */ (await send({ action, replacement }));
    if (outcome) setPending({ action, replacement, outcome });
  }

  async function confirm() {
    if (!pending) return;
    const { action, replacement: r, outcome } = pending;
    await finish(/** @type {Outcome | null} */ (await send({ action, replacement: r, dry_run: false, hashes: outcome.hashes })));
  }

  const blocked = pending?.action === "remove" ? pending.outcome.impact.blocked : [];
  const showReason = !readOnly && !ambiguous && !creatable;
  return html`
    <article class="block broken-group ${ambiguous ? "ambiguous" : "missing"} ${compact ? "compact" : ""}"
      aria-label=${`Broken reference ${group.id}`}>
      <div class="block-row broken-head">
        <span class="bullet"></span>
        <code class="group-id">${group.id}</code>
        <span class="broken-badge">${group.status}</span>
        <span class="broken-meta">${groupMeta(group)}</span>
        ${!readOnly &&
        !pending &&
        html`<div class="repair-actions">
          <select class="repair-select" aria-label="Replace with" value="" disabled=${busy || !fits.length}
            onChange=${(/** @type {Event} */ e) => {
              const value = /** @type {HTMLSelectElement} */ (e.currentTarget).value;
              if (value) preview("replace", value);
            }}>
            <option value="">Replace with…</option>
            ${fits.map((c) => html`<option value=${c.id}>${c.title} (${typeLabel(c.type)})</option>`)}
          </select>
          <button type="button" disabled=${busy} onClick=${() => preview("remove")}>Remove</button>
          ${ambiguous
            ? html`<button type="button" aria-expanded=${renaming} disabled=${busy} onClick=${() => setRenaming(!renaming)}>Rename id…</button>`
            : creatable
              ? html`${group.create_types.length > 1 &&
                  html`<select class="repair-select" aria-label="Type to create" value=${createType}
                    onChange=${(/** @type {Event} */ e) => setCreateType(/** @type {HTMLSelectElement} */ (e.currentTarget).value)}>
                    ${group.create_types.map((t) => html`<option value=${t}>${typeLabel(t)}</option>`)}
                  </select>`}
                  <button type="button" class="solid" disabled=${busy}
                    onClick=${async () => finish(await send({ action: "create", type: createType, dry_run: false }))}>
                    Create${group.create_types.length === 1 ? ` ${typeLabel(group.create_types[0])}` : ""}
                  </button>`
              : html`<button type="button" class="solid" disabled aria-describedby=${reasonId}>Create…</button>`}
        </div>`}
      </div>
      <div class="block-children broken-uses">
        ${!compact && group.uses.map((u, i) => html`<${UseRow} key=${i} use=${u} group=${group} />`)}
        ${!compact &&
        ambiguous &&
        html`<div class="broken-use claimed">
          <span class="use-bullet"></span>
          <div class="use-body">
            <div class="use-line">
              <span class="use-title muted">Claimed by</span>
              <span class="use-path">
                ${group.claimants.map((c, i) => html`${i > 0 && " · "}<a href=${fileHref(c.path)}>${c.path}</a>`)}
              </span>
            </div>
            <p class="use-note">Ids compare case-insensitively. Rename one file's Id and every reference resolves again.</p>
          </div>
        </div>`}
        ${showReason && html`<p class="repair-note" id=${reasonId}>${CREATE_OFF}</p>`}
        ${renaming && !pending && html`<${RenameClaimant} group=${group} busy=${busy}
          onCancel=${() => setRenaming(false)}
          onRename=${async (/** @type {string} */ path, /** @type {string} */ newId) =>
            finish(await send({ path, new_id: newId }, "/api/broken-references/rename"))} />`}
        ${pending &&
        html`<div class="repair-preview">
          <${ImpactList} impact=${pending.outcome.impact} />
          ${blocked.length > 0 &&
          html`<p class="repair-note">Remove is blocked by required references:
            ${blocked.map((b) => `${b.title} (${b.field})`).join(", ")}. Use Replace with… instead.</p>`}
          <div class="repair-actions">
            <button type="button" onClick=${() => setPending(null)}>Cancel</button>
            <button type="button" class="solid" disabled=${busy || blocked.length > 0} onClick=${confirm}>
              ${pending.action === "replace" ? "Replace" : "Remove"}
            </button>
          </div>
        </div>`}
        ${error && html`<p class="error-text" role="alert">${error}</p>`}
      </div>
    </article>
  `;
}

/**
 * One occurrence: the referring file's title and path, the field (or Mention) as a chip,
 * and for a Mention the words around it.
 * @param {{use: Use, group: Group}} props
 */
function UseRow({ use: u, group }) {
  const mention = u.field === MENTION;
  const config = u.field === ME && u.id === null;
  // When the references disagree, each chip says which type its field wants.
  const wants = group.status === "missing" && !group.types.length && !mention ? ` → ${typeList(u.targets)}` : "";
  return html`
    <div class="broken-use">
      <span class="use-bullet"></span>
      <div class="use-body">
        <div class="use-line">
          <a class="use-title" href=${useHref(u)}>${u.title}</a>
          <a class="use-path" href=${config ? "#/settings" : fileHref(u.path)}>${u.path}</a>
          <span class="field-chip ${mention ? "" : "mono"}">${mention ? "Mention" : u.field}${wants}</span>
        </div>
        ${u.snippet &&
        html`<p class="use-snippet">${u.snippet[0]}<span class="broken-mention">${u.snippet[1]}</span>${u.snippet[2]}</p>`}
      </div>
    </div>
  `;
}

/**
 * Rename id… for an ambiguous Id: pick one of the files that claim it and give it a new Id.
 * References stay as written, so they resolve to the file left with the Id.
 * @param {{group: Group, busy: boolean, onCancel: () => void, onRename: (path: string, newId: string) => void}} props
 */
function RenameClaimant({ group, busy, onCancel, onRename }) {
  const [path, setPath] = useState(group.claimants[0]?.path ?? "");
  const [newId, setNewId] = useState("");
  return html`
    <form class="repair-rename" onSubmit=${(/** @type {Event} */ e) => {
      e.preventDefault();
      onRename(path, newId.trim());
    }}>
      <label>File
        <select aria-label="File to rename" value=${path}
          onChange=${(/** @type {Event} */ e) => setPath(/** @type {HTMLSelectElement} */ (e.currentTarget).value)}>
          ${group.claimants.map((c) => html`<option value=${c.path}>${c.path}</option>`)}
        </select>
      </label>
      <label>New Id
        <input class="mono" value=${newId} placeholder=${group.id}
          onInput=${(/** @type {Event} */ e) => setNewId(/** @type {HTMLInputElement} */ (e.currentTarget).value)} />
      </label>
      <div class="repair-actions">
        <button type="button" onClick=${onCancel}>Cancel</button>
        <button type="submit" class="solid" disabled=${busy || !newId.trim()}>Rename</button>
      </div>
    </form>
  `;
}
