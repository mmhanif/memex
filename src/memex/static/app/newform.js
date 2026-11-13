// @ts-check
// The + New… form (SPEC §7.4, §11.7): a Template dropdown, the title, and the type's
// fields with person pickers. Template-supplied fields follow the Template until edited.

import { signal } from "@preact/signals";
import { useEffect, useRef, useState } from "preact/hooks";
import { ApiError, describe, request } from "./api.js";
import { FIELDS, FieldInput, typeLabel, useCandidates } from "./fields.js";
import { entityHref, navigate } from "./router.js";
import { html, reloadTree } from "./state.js";

/**
 * @typedef {{type: string, prefill?: Record<string, any>}} NewRequest
 * @typedef {{key: string, name: string, display_name: string, default: boolean, hidden: boolean,
 *   error: string | null, fields: Record<string, any>, body: string}} TemplateInfo
 */

/** The open + New… form, if any. */
export const newDialog = signal(/** @type {NewRequest | null} */ (null));

/** @param {string} type @param {Record<string, any>} [prefill] */
export function openNew(type, prefill) {
  newDialog.value = { type, prefill };
}

export function NewDialog() {
  const req = newDialog.value;
  if (!req) return null;
  return html`<${NewForm} key=${req.type} type=${req.type} prefill=${req.prefill ?? {}} />`;
}

/** @param {{type: string, prefill: Record<string, any>}} props */
function NewForm({ type, prefill }) {
  const [templates, setTemplates] = useState(/** @type {TemplateInfo[]} */ ([]));
  const [template, setTemplate] = useState(/** @type {TemplateInfo | null} */ (null));
  const [title, setTitle] = useState("");
  const [values, setValues] = useState(/** @type {Record<string, any>} */ ({
    ...Object.fromEntries(FIELDS[type].filter((f) => f.default).map((f) => [f.name, f.default])),
    ...prefill,
  }));
  const [touched, setTouched] = useState(/** @type {Set<string>} */ (new Set(Object.keys(prefill))));
  const [showArchived, setShowArchived] = useState(false);
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const [fieldErrors, setFieldErrors] = useState(/** @type {Record<string, string>} */ ({}));
  const [busy, setBusy] = useState(false);
  const candidates = useCandidates();
  const titleInput = useRef(/** @type {HTMLInputElement | null} */ (null));
  const specs = FIELDS[type].filter((s) => !s.readOnly);

  useEffect(() => {
    titleInput.current?.focus();
    request("GET", `/api/templates?type=${type}`).then(
      (data) => {
        const usable = data.templates.filter((/** @type {TemplateInfo} */ t) => !t.hidden && !t.error);
        setTemplates(usable);
        choose(usable.find((/** @type {TemplateInfo} */ t) => t.key === data.default) ?? usable[0], null);
      },
      (e) => setError(describe(e)),
    );
  }, []);

  /**
   * Switch Template: its fields replace the old one's, except those the user edited.
   * @param {TemplateInfo} next
   * @param {TemplateInfo | null} previous
   */
  function choose(next, previous) {
    setTemplate(next);
    setValues((current) => {
      const updated = { ...current };
      for (const name of Object.keys(previous?.fields ?? {})) {
        if (!touched.has(name)) delete updated[name];
      }
      for (const [name, value] of Object.entries(next.fields)) {
        if (!touched.has(name)) updated[name] = value;
      }
      return updated;
    });
  }

  /** @param {string} name @param {any} value */
  function setField(name, value) {
    setTouched(new Set([...touched, name]));
    setValues({ ...values, [name]: value });
  }

  function close() {
    newDialog.value = null;
  }

  /** @param {Event} e */
  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    /** @type {Record<string, any>} */
    const fields = { title };
    for (const [name, value] of Object.entries(values)) {
      if (value != null && value !== "" && !(Array.isArray(value) && !value.length)) fields[name] = value;
    }
    try {
      const created = await request("POST", "/api/entities", {
        json: { type, fields, template: template?.name },
      });
      close();
      await reloadTree();
      navigate(entityHref(created.id));
    } catch (err) {
      setError(describe(err));
      /** @type {Record<string, string>} */
      const byField = {};
      if (err instanceof ApiError) for (const f of err.body.field_errors ?? []) byField[f.field] = f.message;
      setFieldErrors(byField);
    } finally {
      setBusy(false);
    }
  }

  return html`
    <div class="dialog-backdrop" onClick=${(/** @type {Event} */ e) => e.target === e.currentTarget && close()}>
      <form class="dialog" role="dialog" aria-label="New ${typeLabel(type)}" onSubmit=${submit}
        onKeyDown=${(/** @type {KeyboardEvent} */ e) => e.key === "Escape" && close()}>
        <h2>New ${typeLabel(type)}</h2>
        <div class="form-grid">
          <label for="new-template">Template</label>
          <select id="new-template" value=${template?.key ?? ""}
            onChange=${(/** @type {Event} */ e) => {
              const key = /** @type {HTMLSelectElement} */ (e.currentTarget).value;
              const next = templates.find((t) => t.key === key);
              if (next) choose(next, template);
            }}>
            ${templates.map((t) => html`<option value=${t.key}>${t.display_name}</option>`)}
          </select>

          <label for="new-title">${type === "glossary-term" ? "Term" : type === "person" ? "Name" : "Title"}</label>
          <span>
            <input id="new-title" ref=${titleInput} value=${title} required=${type !== "note"}
              onInput=${(/** @type {Event} */ e) => setTitle(/** @type {HTMLInputElement} */ (e.currentTarget).value)} />
            ${fieldErrors.title && html`<span class="field-error">${fieldErrors.title}</span>`}
          </span>

          ${specs.map(
            (spec) => html`
              <label for="field-${spec.name}">${spec.label}${spec.required ? " *" : ""}</label>
              <span>
                <${FieldInput}
                  spec=${spec}
                  value=${values[spec.name]}
                  onChange=${(/** @type {any} */ v) => setField(spec.name, v)}
                  candidates=${candidates}
                  showArchived=${showArchived}
                  placeholder=${spec.name === "requester" ? "Me" : undefined}
                />
                ${fieldErrors[spec.name] && html`<span class="field-error">${fieldErrors[spec.name]}</span>`}
              </span>
            `,
          )}
        </div>
        ${specs.some((s) => s.targets?.includes("person")) &&
        html`<label class="check"><input type="checkbox" checked=${showArchived}
          onChange=${(/** @type {Event} */ e) => setShowArchived(/** @type {HTMLInputElement} */ (e.currentTarget).checked)} />
          Show archived in pickers</label>`}
        ${error && html`<p class="error-text" role="alert">${error}</p>`}
        <div class="dialog-actions">
          <button type="button" onClick=${close}>Cancel</button>
          <button type="submit" class="primary" disabled=${busy || !template}>Create</button>
        </div>
      </form>
    </div>
  `;
}
