// @ts-check
// Person pickers for the + New… form (SPEC §11.7): type to filter, the match in bold,
// archived people hidden behind an "Include archived" switch in the popover's footer.

import { useState } from "preact/hooks";
import { Avatar } from "./avatar.js";
import { Icon } from "./icons.js";
import { html } from "./state.js";
import { fold } from "./text.js";

/**
 * @typedef {import("./fields.js").Summary} Summary
 * @typedef {{
 *   id: string,
 *   label: string,
 *   multiple: boolean,
 *   value: any,
 *   onChange: (value: any) => void,
 *   people: Summary[],
 *   showArchived: boolean,
 *   onShowArchived: (on: boolean) => void,
 *   placeholder?: string,
 * }} PickerProps
 */

/**
 * The people whose name matches the query, archived ones split off.
 * @param {Summary[]} people
 * @param {string} query
 * @param {Set<string>} exclude
 */
function matching(people, query, exclude) {
  const q = fold(query.trim());
  const hits = people.filter((p) => !exclude.has(p.id) && (!q || fold(p.title).includes(q)));
  return { live: hits.filter((p) => !p.fields.archived), archived: hits.filter((p) => p.fields.archived) };
}

/**
 * A name with the query's first match in bold.
 * @param {{text: string, query: string}} props
 */
function Highlighted({ text, query }) {
  const q = fold(query.trim());
  const at = q ? fold(text).indexOf(q) : -1;
  if (at < 0) return text;
  return html`${text.slice(0, at)}<mark>${text.slice(at, at + q.length)}</mark>${text.slice(at + q.length)}`;
}

/**
 * One person (`multiple` false) or a list of them, picked by typing.
 * @param {PickerProps} props
 */
export function PersonPicker(props) {
  const { id, label, multiple, value, onChange, people } = props;
  const list = /** @type {string[]} */ (multiple ? (Array.isArray(value) ? value : []) : []);
  const chosen = multiple ? null : people.find((p) => p.id === value);
  const [query, setQuery] = useState(/** @type {string | null} */ (null)); // null: not typing
  const [typed, setTyped] = useState(false);
  const [active, setActive] = useState(0);
  const open = query !== null;
  const { live, archived } = matching(people, query ?? "", new Set(list));
  const options = props.showArchived ? [...live, ...archived] : live;
  const hidden = props.showArchived ? 0 : archived.length;
  const name = (/** @type {string} */ v) => people.find((p) => p.id === v)?.title ?? v;

  /** @param {Summary} person */
  function pick(person) {
    if (multiple) onChange([...list, person.id]);
    else onChange(person.id);
    close();
  }

  function close() {
    setQuery(null);
    setTyped(false);
  }

  /** @param {KeyboardEvent} e */
  function onKeyDown(e) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!open) setQuery("");
      const step = e.key === "ArrowDown" ? 1 : -1;
      setActive((i) => Math.max(0, Math.min(options.length - 1, i + step)));
    } else if (e.key === "Enter" && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      const person = options[Math.min(active, options.length - 1)];
      if (open && person) pick(person);
    } else if (e.key === "Escape" && open) {
      e.stopPropagation();
      close();
    }
  }

  /** @param {FocusEvent} e */
  function onFocusOut(e) {
    const next = /** @type {Node | null} */ (e.relatedTarget);
    if (next && /** @type {HTMLElement} */ (e.currentTarget).contains(next)) return;
    if (!multiple && typed && query === "") onChange(null); // cleared the box: unset
    close();
  }

  const input = html`
    <input id=${id} role="combobox" aria-label=${label} aria-expanded=${open} aria-controls="${id}-matches"
      aria-autocomplete="list" autocomplete="off" class="picker-input ${chosen && !open ? "chosen" : ""}"
      value=${open ? query : (chosen?.title ?? (multiple ? "" : (value ?? "")))}
      placeholder=${chosen?.title ?? props.placeholder ?? (multiple ? "+ add" : "—")}
      onFocus=${() => !open && setQuery("")}
      onInput=${(/** @type {Event} */ e) => {
        setQuery(/** @type {HTMLInputElement} */ (e.currentTarget).value);
        setTyped(true);
        setActive(0);
      }}
      onKeyDown=${onKeyDown} />
  `;

  return html`
    <span class="picker ${multiple ? "multiple" : ""}" onFocusOut=${onFocusOut}>
      ${multiple &&
      list.map(
        (v) => html`<span class="chip picker-chip">
          <${Avatar} person=${people.find((p) => p.id === v)} id=${v} name=${name(v)} />
          ${" "}${name(v)}
          <button type="button" class="chip-remove" aria-label="Remove ${name(v)}"
            onClick=${() => {
              const next = list.filter((x) => x !== v);
              onChange(next.length ? next : null);
            }}><${Icon} name="x" /></button>
        </span>`,
      )}
      ${input}
      ${open &&
      html`
        <div class="picker-popover" onMouseDown=${(/** @type {Event} */ e) => e.target instanceof HTMLInputElement || e.preventDefault()}>
          <ul id="${id}-matches" role="listbox" aria-label="${label} matches">
            ${options.map(
              (p, i) => html`<li role="option" aria-selected=${i === active} class=${i === active ? "active" : ""}
                onMouseEnter=${() => setActive(i)} onClick=${() => pick(p)}>
                <${Avatar} person=${p} />${" "}
                <span class="picker-name"><${Highlighted} text=${p.title} query=${query ?? ""} /></span>${" "}
                ${p.fields.archived
                  ? html`<span class="picker-meta">archived</span>`
                  : p.fields.role && html`<span class="picker-meta">${p.fields.role}</span>`}
              </li>`,
            )}
            ${options.length === 0 && html`<li class="picker-empty" aria-disabled="true">No match</li>`}
          </ul>
          ${(hidden > 0 || props.showArchived) &&
          html`<div class="picker-foot">
            <span>${hidden > 0 ? `${hidden} archived ${hidden === 1 ? "match" : "matches"} hidden` : "Showing archived"}</span>
            <label class="toggle">
              Include archived
              <input type="checkbox" role="switch" checked=${props.showArchived}
                onChange=${(/** @type {Event} */ e) => props.onShowArchived(/** @type {HTMLInputElement} */ (e.currentTarget).checked)} />
            </label>
          </div>`}
        </div>
      `}
    </span>
  `;
}
