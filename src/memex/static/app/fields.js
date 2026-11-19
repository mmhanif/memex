// @ts-check
// Typed fields for the properties card and the + New… form (SPEC §4.3, §11.5, §11.7).
// The server validates every write; this table only decides how each field is edited.

import { useEffect, useRef, useState } from "preact/hooks";
import { ApiError, describe, request } from "./api.js";
import { Avatar } from "./avatar.js";
import { useDismiss } from "./dismiss.js";
import { entityHref } from "./router.js";
import { html, viewVersion } from "./state.js";

/**
 * @typedef {"text" | "date" | "enum" | "ref" | "refs" | "texts" | "kinds"} Shape
 * @typedef {{
 *   name: string,
 *   label: string,
 *   shape: Shape,
 *   allowed?: string[],
 *   targets?: string[],
 *   required?: boolean,
 *   readOnly?: boolean,
 *   default?: string,
 * }} FieldSpec
 * @typedef {{id: string, type: string, title: string, path: string, hash: string,
 *   fields: Record<string, any>, ambiguous: boolean,
 *   warnings: import("./state.js").FileWarning[]}} Summary
 */

export const TYPES = [
  { key: "note", label: "Note" },
  { key: "theme", label: "Theme" },
  { key: "project", label: "Project" },
  { key: "deliverable", label: "Deliverable" },
  { key: "person", label: "Person" },
  { key: "todo", label: "To-do" },
  { key: "glossary-term", label: "Glossary Term" },
];

/** @param {string} type */
export function typeLabel(type) {
  return TYPES.find((t) => t.key === type)?.label ?? type;
}

export const WORK_STATUSES = ["not-started", "active", "on-hold", "blocked", "done", "cancelled"];
const TODO_STATUSES = ["open", "done", "cancelled"];
const WORK = ["theme", "project", "deliverable"];

/** @type {(name: string, label: string) => FieldSpec} */
const person = (name, label) => ({ name, label, shape: "ref", targets: ["person"] });
/** @type {(name: string, label: string) => FieldSpec} */
const people = (name, label) => ({ name, label, shape: "refs", targets: ["person"] });
/** @type {FieldSpec[]} */
const TAGS = [person("lead", "Lead"), people("team", "Team"), people("stakeholders", "Stakeholders")];
/** @type {FieldSpec} */
const LABELS = { name: "labels", label: "Labels", shape: "texts" };
/** @type {FieldSpec} */
const ARCHIVED = { name: "archived", label: "Archived", shape: "date", readOnly: true };

/** @type {Record<string, FieldSpec[]>} Typed fields, in card order. `title` and `created` are shown apart. */
export const FIELDS = {
  theme: [...TAGS, LABELS, ARCHIVED],
  project: [
    { name: "theme", label: "Theme", shape: "ref", targets: ["theme"] },
    { name: "status", label: "Status", shape: "enum", allowed: WORK_STATUSES, required: true, default: "not-started" },
    ...TAGS,
    { name: "start", label: "Start", shape: "date" },
    { name: "due", label: "Due", shape: "date" },
    LABELS,
  ],
  deliverable: [
    { name: "project", label: "Project", shape: "ref", targets: ["project"], required: true },
    { name: "status", label: "Status", shape: "enum", allowed: WORK_STATUSES, required: true, default: "not-started" },
    ...TAGS,
    { name: "start", label: "Start", shape: "date" },
    { name: "due", label: "Due", shape: "date" },
    LABELS,
  ],
  person: [
    { name: "kind", label: "Kind", shape: "kinds", allowed: ["team-member", "stakeholder"], required: true },
    person("manager", "Manager"),
    { name: "role", label: "Role", shape: "text" },
    { name: "organisation", label: "Organisation", shape: "text" },
    { name: "email", label: "Email", shape: "text" },
    ARCHIVED,
  ],
  todo: [
    { ...person("owner", "Owner"), required: true },
    person("requester", "Requester"),
    { name: "status", label: "Status", shape: "enum", allowed: TODO_STATUSES, required: true, default: "open" },
    { name: "due", label: "Due", shape: "date" },
    { name: "completed", label: "Completed", shape: "date", readOnly: true },
    { name: "about", label: "About", shape: "ref", targets: WORK },
    { name: "source", label: "Source", shape: "ref", targets: ["note"], readOnly: true },
  ],
  note: [
    { name: "date", label: "Date", shape: "date" },
    people("people", "Participants"),
    { name: "about", label: "About", shape: "refs", targets: WORK },
    LABELS,
  ],
  "glossary-term": [{ name: "aliases", label: "Aliases", shape: "texts" }, LABELS],
};

/**
 * One hash-checked field write from a list, row or card (§11.5); `null` unsets. Resolves
 * to a message for the row, or null when it saved. The caller refetches its view.
 * @param {Summary} item
 * @param {string} name
 * @param {any} value
 * @returns {Promise<string | null>}
 */
export async function writeField(item, name, value) {
  try {
    await request("PATCH", `/api/entities/${encodeURIComponent(item.id)}`, {
      json: value == null ? { set: {}, unset: [name] } : { set: { [name]: value }, unset: [] },
      ifMatch: item.hash,
    });
    return null;
  } catch (e) {
    return e instanceof ApiError && e.code === "conflict" ? "It changed on disk: try again" : describe(e);
  }
}

/** Every typed Entity, archived ones included, for pickers. Refetched on `changed`. */
export function useCandidates() {
  const [all, setAll] = useState(/** @type {Summary[]} */ ([]));
  const version = viewVersion.value;
  useEffect(() => {
    let cancelled = false;
    request("GET", "/api/entities?include_archived=true").then(
      (data) => !cancelled && setAll(data.entities),
      () => {},
    );
    return () => {
      cancelled = true;
    };
  }, [version]);
  return all;
}

/**
 * @typedef {{
 *   spec: FieldSpec,
 *   value: any,
 *   onChange: (value: any) => void,
 *   candidates: Summary[],
 *   names?: Record<string, string>,
 *   broken?: Set<string>,
 *   showArchived?: boolean,
 *   disabled?: boolean,
 *   placeholder?: string,
 *   inputId?: string,
 *   ariaLabel?: string,
 * }} InputProps
 */

/**
 * One field's editor. `onChange(null)` means unset. Text-like inputs report on blur
 * or Enter, so each keystroke isn't a write.
 * @param {InputProps} props
 */
export function FieldInput(props) {
  const { spec, value, onChange, disabled, ariaLabel } = props;
  const id = props.inputId ?? `field-${spec.name}`;
  if (spec.readOnly) return html`<span class="field-value" id=${id}>${display(props)}</span>`;
  switch (spec.shape) {
    case "enum":
      return html`
        <select id=${id} value=${value ?? ""} disabled=${disabled} aria-label=${ariaLabel}
          onChange=${(/** @type {Event} */ e) => onChange(target(e).value || null)}>
          ${!spec.required && html`<option value="">—</option>`}
          ${value && !spec.allowed?.includes(value) && html`<option value=${value}>${value} (invalid)</option>`}
          ${spec.allowed?.map((v) => html`<option value=${v}>${v}</option>`)}
        </select>
      `;
    case "date":
      return html`<input id=${id} type="date" value=${typeof value === "string" ? value : ""} disabled=${disabled}
        aria-label=${ariaLabel}
        onChange=${(/** @type {Event} */ e) => onChange(target(e).value || null)} />`;
    case "text":
      return html`<${TextInput} id=${id} value=${value == null ? "" : String(value)} disabled=${disabled}
        ariaLabel=${ariaLabel}
        placeholder=${props.placeholder} onCommit=${(/** @type {string} */ v) => onChange(v.trim() || null)} />`;
    case "texts":
      return html`<${TextInput} id=${id} value=${Array.isArray(value) ? value.join(", ") : ""} disabled=${disabled}
        ariaLabel=${ariaLabel}
        placeholder="comma, separated"
        onCommit=${(/** @type {string} */ v) => {
          const list = v.split(",").map((s) => s.trim()).filter(Boolean);
          onChange(list.length ? list : null);
        }} />`;
    case "kinds":
      return html`
        <span class="checks" id=${id}>
          ${spec.allowed?.map((k) => {
            const list = Array.isArray(value) ? value : [];
            return html`<label class="check">
              <input type="checkbox" checked=${list.includes(k)} disabled=${disabled}
                onChange=${(/** @type {Event} */ e) => {
                  const next = target(e).checked ? [...list, k] : list.filter((x) => x !== k);
                  onChange(next.length ? next : null);
                }} />
              ${k}
            </label>`;
          })}
        </span>
      `;
    case "ref":
      return html`<${RefSelect} ...${props} id=${id} />`;
    case "refs":
      return html`<${RefChecklist} ...${props} id=${id} />`;
  }
  return null;
}

/** @param {Event} e */
function target(e) {
  return /** @type {HTMLInputElement} */ (e.currentTarget);
}

/** @param {{id: string, value: string, disabled?: boolean, placeholder?: string, ariaLabel?: string, onCommit: (v: string) => void}} props */
function TextInput({ id, value, disabled, placeholder, ariaLabel, onCommit }) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const commit = () => draft !== value && onCommit(draft);
  return html`<input id=${id} value=${draft} disabled=${disabled} placeholder=${placeholder} aria-label=${ariaLabel}
    onInput=${(/** @type {Event} */ e) => setDraft(target(e).value)}
    onBlur=${commit}
    onKeyDown=${(/** @type {KeyboardEvent} */ e) => e.key === "Enter" && (e.preventDefault(), commit())} />`;
}

/**
 * @param {InputProps} props
 * @param {string} keep an Id to offer even if archived (the current value)
 */
function choices({ spec, candidates, showArchived }, keep) {
  return candidates.filter(
    (c) => spec.targets?.includes(c.type) && (showArchived || !c.fields.archived || c.id === keep),
  );
}

/** @param {InputProps & {id: string}} props */
function RefSelect(props) {
  const { spec, value, onChange, disabled, id, names } = props;
  const options = choices(props, value);
  const known = !value || options.some((c) => c.id === value);
  return html`
    <select id=${id} value=${value ?? ""} disabled=${disabled} aria-label=${props.ariaLabel}
      class=${props.broken?.has(value) ? "ref broken" : "ref"}
      onChange=${(/** @type {Event} */ e) => onChange(target(e).value || null)}>
      <option value="">${props.placeholder ?? "—"}</option>
      ${!known && html`<option value=${value}>${names?.[value] ?? value}${props.broken?.has(value) ? " (broken)" : ""}</option>`}
      ${options.map((c) => html`<option value=${c.id}>${c.title}${spec.targets && spec.targets.length > 1 ? ` (${typeLabel(c.type)})` : ""}</option>`)}
    </select>
  `;
}

/**
 * Tags as an avatar checklist: chips for who is on, a dropdown to tick people on or off.
 * @param {InputProps & {id: string}} props
 */
function RefChecklist(props) {
  const { value, onChange, disabled, id, names, broken } = props;
  const list = /** @type {string[]} */ (Array.isArray(value) ? value : []);
  const options = choices(props, "");
  const title = (/** @type {string} */ v) => names?.[v] ?? options.find((c) => c.id === v)?.title ?? v;
  const box = useRef(/** @type {HTMLDetailsElement | null} */ (null));
  // The <details> keeps its own open state, so listen always and close only if open.
  useDismiss(box, true, () => {
    if (box.current?.open) box.current.open = false;
  });
  /** @param {string} v @param {boolean} on */
  const toggle = (v, on) => {
    const next = on ? [...list, v] : list.filter((x) => x !== v);
    onChange(next.length ? next : null);
  };
  return html`
    <details class="checklist" id=${id} ref=${box}>
      <summary class=${disabled ? "disabled" : ""} aria-label=${props.ariaLabel}>
        ${list.length
          ? list.map((v) => html`<span class="chip ${broken?.has(v) ? "broken" : ""}" title=${title(v)}>
              <${Avatar} id=${v} name=${title(v)} />${title(v)}
            </span>`)
          : html`<span class="muted">None</span>`}
      </summary>
      ${!disabled &&
      html`<div class="checklist-menu">
        ${[...new Set([...list.filter((v) => !options.some((c) => c.id === v)), ...options.map((c) => c.id)])].map(
          (v) => html`<label class="check">
            <input type="checkbox" checked=${list.includes(v)}
              onChange=${(/** @type {Event} */ e) => toggle(v, target(e).checked)} />
            ${title(v)}
          </label>`,
        )}
        ${options.length === 0 && html`<span class="muted">Nothing to pick yet</span>`}
      </div>`}
    </details>
  `;
}

/** @param {InputProps} props */
function display({ spec, value, names }) {
  if (value == null || value === "") return html`<span class="muted">—</span>`;
  if (spec.shape === "ref") {
    const type = spec.targets?.length === 1 ? spec.targets[0] : undefined;
    return html`<a href=${entityHref(value, type)}>${names?.[value] ?? value}</a>`;
  }
  return Array.isArray(value) ? value.join(", ") : String(value);
}
