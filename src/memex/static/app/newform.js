// @ts-check
// The + New… form (SPEC §7.4, §11.7): a modal with the title, a live Id/path preview,
// the type's fields in a properties well (Template dropdown first, person pickers), and
// the Template's body. Template-supplied fields follow the Template until edited.

import { signal } from "@preact/signals";
import { useEffect, useRef, useState } from "preact/hooks";
import { ApiError, describe, request } from "./api.js";
import { FIELDS, FieldInput, typeLabel, useCandidates } from "./fields.js";
import { Icon } from "./icons.js";
import { renderMarkdown } from "./markdown.js";
import { outlineHtml } from "./outline.js";
import { PersonPicker } from "./picker.js";
import { entityHref, navigate } from "./router.js";
import { html, reloadTree } from "./state.js";

/**
 * @typedef {{type: string, prefill?: Record<string, any>, template?: string}} NewRequest
 * @typedef {{key: string, name: string, display_name: string, default: boolean, hidden: boolean,
 *   source: "blank" | "builtin" | "custom", path: string | null,
 *   error: string | null, fields: Record<string, any>, body: string}} TemplateInfo
 */

/** The open + New… form, if any. */
export const newDialog = signal(/** @type {NewRequest | null} */ (null));

/**
 * @param {string} type
 * @param {Record<string, any>} [prefill]
 * @param {string} [template] a Template name to preselect instead of the default
 */
export function openNew(type, prefill, template) {
  newDialog.value = { type, prefill, template };
}

/**
 * The Templates a picker offers for a type (hidden and broken ones left out), and its default.
 * @param {string} type
 * @returns {Promise<{usable: TemplateInfo[], fallback: TemplateInfo}>}
 */
export async function fetchTemplates(type) {
  const data = await request("GET", `/api/templates?type=${encodeURIComponent(type)}`);
  /** @type {TemplateInfo[]} */
  const usable = data.templates.filter((/** @type {TemplateInfo} */ t) => !t.hidden && !t.error);
  return { usable, fallback: usable.find((t) => t.key === data.default) ?? usable[0] };
}

/**
 * A Template's headings, e.g. "Goal · Scope · Risks · Decisions".
 * @param {TemplateInfo} t
 */
export function templateHeadings(t) {
  return [...t.body.matchAll(/^#{1,6}\s+(.+?)\s*#*$/gm)].map((m) => m[1]).join(" · ");
}

/**
 * The fields a Template sets, by their labels: "Date and Participants".
 * @param {string} type
 * @param {TemplateInfo} t
 */
function templateSets(type, t) {
  const labels = FIELDS[type].filter((f) => f.name in t.fields).map((f) => f.label);
  return labels.length > 1 ? `${labels.slice(0, -1).join(", ")} and ${labels[labels.length - 1]}` : labels[0] ?? "";
}

export function NewDialog() {
  const req = newDialog.value;
  if (!req) return null;
  return html`<${NewForm} key=${req.type} type=${req.type} prefill=${req.prefill ?? {}} initial=${req.template} />`;
}

/** @param {{type: string, prefill: Record<string, any>, initial?: string}} props */
function NewForm({ type, prefill, initial }) {
  const [templates, setTemplates] = useState(/** @type {TemplateInfo[]} */ ([]));
  const [template, setTemplate] = useState(/** @type {TemplateInfo | null} */ (null));
  const [title, setTitle] = useState("");
  const [values, setValues] = useState(/** @type {Record<string, any>} */ ({
    ...Object.fromEntries(FIELDS[type].filter((f) => f.default).map((f) => [f.name, f.default])),
    ...prefill,
  }));
  const [touched, setTouched] = useState(/** @type {Set<string>} */ (new Set(Object.keys(prefill))));
  const [showArchived, setShowArchived] = useState(false);
  const [placement, setPlacement] = useState(/** @type {{id: string, path: string, created: string} | null} */ (null));
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const [fieldErrors, setFieldErrors] = useState(/** @type {Record<string, string>} */ ({}));
  const [busy, setBusy] = useState(false);
  const candidates = useCandidates();
  const people = candidates.filter((c) => c.type === "person");
  const titleInput = useRef(/** @type {HTMLInputElement | null} */ (null));
  const form = useRef(/** @type {HTMLFormElement | null} */ (null));
  const specs = FIELDS[type].filter((s) => !s.readOnly);
  const label = typeLabel(type);
  const dated = type === "note" && Boolean(values.date);

  useEffect(() => {
    titleInput.current?.focus();
    fetchTemplates(type).then(
      ({ usable, fallback }) => {
        setTemplates(usable);
        choose(usable.find((t) => t.name === initial) ?? fallback, null);
      },
      (e) => setError(describe(e)),
    );
  }, []);

  // The live Id/path preview: where Create would put the file.
  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(() => {
      const fields = { title, ...(type === "note" && values.date ? { date: values.date } : {}) };
      request("POST", "/api/entities/placement", { json: { type, fields } }).then(
        (found) => !cancelled && setPlacement(found),
        () => {},
      );
    }, 120);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [title, values.date]);

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
    if (busy || !template) return;
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

  /** @param {KeyboardEvent} e */
  function onKeyDown(e) {
    if (e.key === "Escape") close();
    else if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      form.current?.requestSubmit();
    }
  }

  const slash = placement ? placement.path.lastIndexOf("/") + 1 : 0;
  const preview = template ? template.body.replaceAll("{{title}}", title || "Untitled") : "";

  return html`
    <div class="dialog-backdrop" onClick=${(/** @type {Event} */ e) => e.target === e.currentTarget && close()}>
      <form class="dialog new-form" role="dialog" aria-label="New ${label}" ref=${form} onSubmit=${submit}
        onKeyDown=${onKeyDown}>
        <header class="new-head">
          <div>
            <h2>New ${label}</h2>
            <p class="new-path" aria-live="polite">
              ${placement &&
              html`${placement.path.slice(0, slash)}<b>${placement.id}</b>${placement.path.slice(slash + placement.id.length)}`}
            </p>
          </div>
          <button type="button" class="icon-button" aria-label="Close" onClick=${close}><${Icon} name="x" /></button>
        </header>

        <div class="new-title">
          <input id="new-title" ref=${titleInput} value=${title} required=${type !== "note"}
            aria-label=${type === "glossary-term" ? "Term" : type === "person" ? "Name" : "Title"}
            placeholder=${type === "glossary-term" ? "Term" : type === "person" ? "Name" : "Title"}
            onInput=${(/** @type {Event} */ e) => setTitle(/** @type {HTMLInputElement} */ (e.currentTarget).value)} />
          ${fieldErrors.title && html`<span class="field-error">${fieldErrors.title}</span>`}
        </div>

        <div class="well new-props">
          <div class="prop">
            <span class="prop-key">Template</span>
            <span class="prop-value">
              <${TemplatePicker} type=${type} templates=${templates} value=${template}
                onChange=${(/** @type {TemplateInfo} */ next) => choose(next, template)} onManage=${close} />
              ${template &&
              html`<span class="template-hint">${templateSets(type, template) ? `sets ${templateSets(type, template)}` : templateHeadings(template)}</span>`}
            </span>
          </div>
          ${specs.map(
            (spec) => html`
              <div class="prop">
                <label class="prop-key" for="field-${spec.name}">${spec.label}${spec.required ? " *" : ""}</label>
                <span class="prop-value">
                  ${spec.targets?.length === 1 && spec.targets[0] === "person"
                    ? html`<${PersonPicker}
                        id="field-${spec.name}"
                        label=${spec.label}
                        multiple=${spec.shape === "refs"}
                        value=${values[spec.name]}
                        onChange=${(/** @type {any} */ v) => setField(spec.name, v)}
                        people=${people}
                        showArchived=${showArchived}
                        onShowArchived=${setShowArchived}
                        placeholder=${spec.name === "requester" ? "Me" : undefined}
                      />`
                    : html`<${FieldInput}
                        spec=${spec}
                        value=${values[spec.name]}
                        onChange=${(/** @type {any} */ v) => setField(spec.name, v)}
                        candidates=${candidates}
                        showArchived=${showArchived}
                      />`}
                  ${fieldErrors[spec.name] && html`<span class="field-error">${fieldErrors[spec.name]}</span>`}
                </span>
              </div>
            `,
          )}
        </div>

        ${preview.trim() &&
        html`<div class="new-body">
          <div class="new-body-head"><span class="eyebrow">Body</span><span>from Template · copied once, edit after creating</span></div>
          <div class="body-preview outline" dangerouslySetInnerHTML=${{ __html: outlineHtml(renderMarkdown(preview)) }}></div>
        </div>`}

        ${error && html`<p class="error-text" role="alert">${error}</p>`}
        <footer class="new-actions">
          <span class="new-foot">
            ${dated
              ? "date-prefixed Id because the Note has a Date"
              : placement && `created ${placement.created} · opens the new ${label}`}
          </span>
          <button type="button" onClick=${close}>Cancel</button>
          <button type="submit" class="solid" disabled=${busy || !template}>
            Create ${label}<kbd aria-hidden="true">Ctrl ↵</kbd>
          </button>
        </footer>
      </form>
    </div>
  `;
}

/**
 * The Template dropdown: each usable Template with its headings, custom ones marked
 * with their path, the default starred.
 * @param {{type: string, templates: TemplateInfo[], value: TemplateInfo | null,
 *   onChange: (t: TemplateInfo) => void, onManage: () => void}} props
 */
function TemplatePicker({ templates, value, onChange, onManage }) {
  const [open, setOpen] = useState(false);
  const box = useRef(/** @type {HTMLSpanElement | null} */ (null));
  const list = useRef(/** @type {HTMLUListElement | null} */ (null));
  useEffect(() => {
    if (!open) return;
    list.current?.querySelector(/** @type {"li"} */ ("[aria-selected=true]"))?.focus();
    /** @param {MouseEvent} e */
    const away = (e) => box.current?.contains(/** @type {Node} */ (e.target)) || setOpen(false);
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);

  /** @param {TemplateInfo} t */
  function pick(t) {
    onChange(t);
    setOpen(false);
    box.current?.querySelector("button")?.focus();
  }

  /** @param {KeyboardEvent} e */
  function onKeyDown(e) {
    const items = /** @type {HTMLElement[]} */ ([...(list.current?.querySelectorAll("[role=option]") ?? [])]);
    const at = items.indexOf(/** @type {HTMLElement} */ (document.activeElement));
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      items[Math.max(0, Math.min(items.length - 1, at + (e.key === "ArrowDown" ? 1 : -1)))]?.focus();
    } else if ((e.key === "Enter" || e.key === " ") && !e.ctrlKey && !e.metaKey && at >= 0) {
      e.preventDefault();
      pick(templates[at]);
    } else if (e.key === "Escape") {
      e.stopPropagation();
      setOpen(false);
      box.current?.querySelector("button")?.focus();
    }
  }

  return html`
    <span class="template-picker" ref=${box}>
      <button type="button" class="template-button" aria-label="Template" aria-haspopup="listbox" aria-expanded=${open}
        disabled=${!value} onClick=${() => setOpen(!open)}>
        ${value && html`${value.default ? "★ " : ""}${value.display_name}`}<${Icon} name="chevron-down" />
      </button>
      ${open &&
      html`<div class="template-menu">
        <ul role="listbox" aria-label="Templates" ref=${list} onKeyDown=${onKeyDown}>
          ${templates.map(
            (t) => html`<li role="option" tabindex="-1" aria-selected=${t.key === value?.key} onClick=${() => pick(t)}>
              <span class="template-star">${t.default ? "★" : ""}</span>${t.default ? " " : ""}
              <span class="template-text">
                <span class="template-name">${t.display_name}${t.source === "custom" ? html` <span class="custom-badge">custom</span>` : ""}</span>${" "}
                <span class="template-sub ${t.source === "custom" ? "mono" : ""}">
                  ${t.source === "custom" ? t.path : templateHeadings(t) || (Object.keys(t.fields).length ? "" : "no fields, empty body")}
                </span>
              </span>
              ${t.key === value?.key && html`<${Icon} name="check" />`}
            </li>`,
          )}
        </ul>
        <div class="template-foot">
          <span>Switching keeps fields you've edited</span>
          <a href="#/settings" onClick=${onManage}>Manage Templates</a>
        </div>
      </div>`}
    </span>
  `;
}
