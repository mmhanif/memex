// @ts-check
// First-run Setup (SPEC §3.4): pick the Workspace folder, see what adopting it finds
// (checking writes nothing), then say who Me is. Shown instead of the shell until done.

import { useState } from "preact/hooks";
import { describe, request } from "./api.js";
import { html } from "./state.js";

/**
 * @typedef {{id: string, title: string}} PersonChoice
 * @typedef {{summary: string, notes: number, persons: PersonChoice[]}} Scan
 */

/** @param {{path: string, onDone: () => void}} props */
export function SetupPage({ path: initialPath, onDone }) {
  const [path, setPath] = useState(initialPath);
  const [scan, setScan] = useState(/** @type {Scan | null} */ (null));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(/** @type {string | null} */ (null));

  /** @param {Event} event */
  async function check(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setScan(await request("POST", "/api/setup/scan", { json: { path: path.trim() } }));
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  }

  function changeFolder() {
    setScan(null);
    setError(null);
  }

  return html`
    <main class="setup">
      <h1>Set up Memex</h1>
      <p class="muted">
        Memex keeps everything as Markdown files in one folder, your Workspace. Pick a new
        folder, or an existing one to adopt: nothing in it is moved or rewritten.
      </p>
      <form class="setup-step" onSubmit=${check}>
        <label>
          Folder
          <input
            type="text"
            value=${path}
            disabled=${scan !== null}
            spellcheck=${false}
            onInput=${(/** @type {any} */ e) => setPath(e.currentTarget.value)}
          />
        </label>
        ${scan === null
          ? html`<button type="submit" class="primary" disabled=${busy || !path.trim()}>Check folder</button>`
          : html`<button type="button" onClick=${changeFolder}>Change folder</button>`}
      </form>
      ${scan === null && error && html`<p class="error-text" role="alert">${error}</p>`}
      ${scan !== null && html`<${MeStep} path=${path.trim()} scan=${scan} onDone=${onDone} />`}
    </main>
  `;
}

/** @param {{path: string, scan: Scan, onDone: () => void}} props */
function MeStep({ path, scan, onDone }) {
  const hasPersons = scan.persons.length > 0;
  const [mode, setMode] = useState(/** @type {"new" | "existing"} */ ("new"));
  const [name, setName] = useState("");
  const [personId, setPersonId] = useState(scan.persons[0]?.id ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const ready = mode === "new" ? name.trim() !== "" : personId !== "";

  /** @param {Event} event */
  async function apply(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const me = mode === "new" ? { name: name.trim() } : { id: personId };
    try {
      await request("POST", "/api/setup/apply", { json: { path, me } });
      onDone();
    } catch (e) {
      setError(describe(e));
      setBusy(false);
    }
  }

  return html`
    <form class="setup-step" onSubmit=${apply}>
      <p role="status">
        ${scan.notes === 0 && !hasPersons
          ? html`An empty folder: ${scan.summary}. Memex will set it up.`
          : html`Found ${scan.summary}. Memex will adopt them as they are.`}
      </p>
      ${hasPersons
        ? html`
            <fieldset class="setup-me">
              <legend>Who are you?</legend>
              <label class="check">
                <input
                  type="radio"
                  name="me"
                  checked=${mode === "existing"}
                  onChange=${() => setMode("existing")}
                />
                I'm one of these
              </label>
              <label>
                Person
                <select
                  value=${personId}
                  disabled=${mode !== "existing"}
                  onChange=${(/** @type {any} */ e) => setPersonId(e.currentTarget.value)}
                >
                  ${scan.persons.map((p) => html`<option value=${p.id}>${p.title}</option>`)}
                </select>
              </label>
              <label class="check">
                <input type="radio" name="me" checked=${mode === "new"} onChange=${() => setMode("new")} />
                I'm someone new
              </label>
              ${mode === "new" && html`<${NameField} name=${name} setName=${setName} />`}
            </fieldset>
          `
        : html`<${NameField} name=${name} setName=${setName} />`}
      ${error && html`<p class="error-text" role="alert">${error}</p>`}
      <button type="submit" class="primary" disabled=${busy || !ready}>Set up Memex</button>
    </form>
  `;
}

/** @param {{name: string, setName: (name: string) => void}} props */
function NameField({ name, setName }) {
  return html`
    <label>
      Your name
      <input
        type="text"
        value=${name}
        autocomplete="name"
        onInput=${(/** @type {any} */ e) => setName(e.currentTarget.value)}
      />
    </label>
  `;
}
