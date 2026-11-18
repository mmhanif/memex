// @ts-check
// First-run Setup (SPEC §3.4): pick the Workspace folder, see what adopting it finds
// (checking writes nothing), then say who Me is. Shown instead of the shell until done:
// a white panel on the grey ground, with numbered steps.

import { useState } from "preact/hooks";
import { describe, request } from "./api.js";
import { Icon } from "./icons.js";
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
  const refused = scan === null && error !== null;

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
      <div class="setup-panel">
        <div class="setup-brand"><span class="setup-mark" aria-hidden="true">m</span>memex</div>
        <h1>Set up Memex</h1>
        <p class="setup-lede">
          Memex keeps everything as Markdown files in one folder, your Workspace. Pick a new
          folder, or an existing one to adopt: nothing in it is moved or rewritten.
        </p>
        <form class="setup-step" onSubmit=${check}>
          <div class="setup-step-head">
            <${StepMark} n=${1} done=${scan !== null} />
            <label for="setup-folder">Folder</label>
          </div>
          <div class="setup-step-body">
            <div class="setup-folder-row">
              <input
                id="setup-folder"
                class="setup-input setup-path"
                type="text"
                value=${path}
                disabled=${scan !== null}
                spellcheck=${false}
                aria-invalid=${refused ? "true" : undefined}
                aria-describedby=${refused ? "setup-folder-error" : undefined}
                onInput=${(/** @type {any} */ e) => {
                  setPath(e.currentTarget.value);
                  setError(null);
                }}
              />
              ${scan === null
                ? html`<button type="submit" class="primary" disabled=${busy || !path.trim()}>Check folder</button>`
                : html`<button type="button" onClick=${changeFolder}>Change folder</button>`}
            </div>
            ${refused &&
            html`<p class="setup-error" id="setup-folder-error" role="alert"><${Icon} name="circle-alert" />${error}</p>`}
            ${scan !== null && html`<${ScanSummary} scan=${scan} />`}
          </div>
        </form>
        ${scan !== null && html`<${MeStep} path=${path.trim()} scan=${scan} onDone=${onDone} />`}
      </div>
    </main>
  `;
}

/** A step's number, or a green tick once it's done. @param {{n: number, done?: boolean}} props */
function StepMark({ n, done = false }) {
  return done
    ? html`<span class="setup-step-mark done" role="img" aria-label="Done"><${Icon} name="check" /></span>`
    : html`<span class="setup-step-mark" aria-hidden="true">${n}</span>`;
}

/** What checking the folder found; nothing is written until Set up Memex. @param {{scan: Scan}} props */
function ScanSummary({ scan }) {
  const empty = scan.notes === 0 && scan.persons.length === 0;
  return html`
    <div class="setup-scan" role="status">
      <p>
        <strong>Found ${scan.summary}.</strong>
        ${empty ? " An empty folder: Memex will set it up." : " Memex will adopt them as they are."}
      </p>
      <p class="setup-scan-note">
        ${empty ? "" : "Problems in existing files are flagged, not fixed. "}Nothing has been written yet.
      </p>
    </div>
  `;
}

/** @param {{path: string, scan: Scan, onDone: () => void}} props */
function MeStep({ path, scan, onDone }) {
  const hasPersons = scan.persons.length > 0;
  const empty = scan.notes === 0 && !hasPersons;
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
    <form onSubmit=${apply}>
      <fieldset class="setup-step">
        <legend class="setup-step-head"><${StepMark} n=${2} />Who are you?</legend>
        <div class="setup-step-body setup-me">
          ${hasPersons
            ? html`
                <div class="setup-me-row">
                  <label class="setup-radio">
                    <input
                      type="radio"
                      name="me"
                      checked=${mode === "existing"}
                      onChange=${() => setMode("existing")}
                    />
                    I'm one of these
                  </label>
                  <select
                    class="setup-input"
                    aria-label="Person"
                    value=${personId}
                    disabled=${mode !== "existing"}
                    onChange=${(/** @type {any} */ e) => setPersonId(e.currentTarget.value)}
                  >
                    ${scan.persons.map((p) => html`<option value=${p.id}>${p.title}</option>`)}
                  </select>
                </div>
                <label class="setup-radio">
                  <input type="radio" name="me" checked=${mode === "new"} onChange=${() => setMode("new")} />
                  I'm someone new
                </label>
                ${mode === "new" && html`<${NameField} name=${name} setName=${setName} />`}
              `
            : html`<${NameField} name=${name} setName=${setName} />`}
        </div>
      </fieldset>
      ${error && html`<p class="setup-error" role="alert"><${Icon} name="circle-alert" />${error}</p>`}
      <div class="setup-footer">
        <p class="setup-adds">
          ${empty ? "Creates " : "Adds "}<code>.memex/config.yaml</code>,
          ${empty ? " the type folders, " : " any missing type folders, "}<code>notes/</code>${mode === "new"
            ? html`, <code>bookmarks.md</code> and your Person file in <code>people/</code>.`
            : html` and <code>bookmarks.md</code>.`}
        </p>
        <button type="submit" class="primary" disabled=${busy || !ready}>Set up Memex</button>
      </div>
    </form>
  `;
}

/** @param {{name: string, setName: (name: string) => void}} props */
function NameField({ name, setName }) {
  return html`
    <label class="setup-name">
      Your name
      <input
        class="setup-input"
        type="text"
        value=${name}
        autocomplete="name"
        onInput=${(/** @type {any} */ e) => setName(e.currentTarget.value)}
      />
    </label>
  `;
}
