// @ts-check
// `#/glossary` (SPEC §10.2), per "Glossary" in Paper: an A–Z strip, then each letter as an
// outline heading block with its Glossary Terms under it, aliases beside the term and the
// definition inline with its Mentions as page refs.

import { describe } from "./api.js";
import { Icon } from "./icons.js";
import { renderMarkdown } from "./markdown.js";
import { openNew } from "./newform.js";
import { entityHref } from "./router.js";
import { html, resolveMention, tree, useView } from "./state.js";

/**
 * @typedef {{id: string, title: string, aliases: string[], definition: string}} Term
 * @typedef {{letter: string, terms: Term[]}} Group
 */

const LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");

/** @param {number} n @param {string} one @param {string} many */
const count = (n, one, many) => `${n} ${n === 1 ? one : many}`;

export function GlossaryPage() {
  const { data, error } = useView("/api/views/glossary");
  const groups = /** @type {{groups: Group[]} | null} */ (data)?.groups;
  const readOnly = tree.value?.workspace.read_only ?? false;
  const terms = groups?.flatMap((g) => g.terms) ?? [];
  const aliases = terms.reduce((n, t) => n + t.aliases.length, 0);
  const present = new Set(groups?.map((g) => g.letter));
  // "#" (Terms that don't start with a letter) only shows when there are some.
  const strip = present.has("#") ? ["#", ...LETTERS] : LETTERS;

  return html`
    <section class="page glossary-page">
      <header class="glossary-head">
        <p class="eyebrow">${groups ? `${count(terms.length, "Term", "Terms")} · ${count(aliases, "alias", "aliases")}` : " "}</p>
        <h1 class="title">Glossary</h1>
      </header>
      <div class="glossary-bar">
        <nav class="letters" aria-label="Letters">
          ${strip.map((letter) =>
            present.has(letter)
              ? html`<a key=${letter} href="#/glossary" onClick=${(/** @type {MouseEvent} */ e) => {
                  e.preventDefault();
                  document.getElementById(`glossary-${letter}`)?.scrollIntoView({ block: "start" });
                }}>${letter}</a>`
              : html`<span key=${letter} aria-disabled="true">${letter}</span>`,
          )}
        </nav>
        ${!readOnly &&
        html`<button type="button" class="outline-button" onClick=${() => openNew("glossary-term")}>
          <${Icon} name="plus" /> Term</button>`}
      </div>
      ${error && html`<p class="error-text" role="alert">${describe(error)}</p>`}
      ${groups && !groups.length && html`<p class="block-empty">No Glossary Terms yet.</p>`}
      ${groups?.map(
        (g) => html`
          <section key=${g.letter} class="block block-heading glossary-group" id=${`glossary-${g.letter}`}>
            <div class="block-row"><span class="bullet"></span><h2 class="block-text">${g.letter}</h2></div>
            <div class="block-children">
              ${g.terms.map((t) => html`<${TermBlock} key=${t.id} term=${t} />`)}
            </div>
          </section>
        `,
      )}
    </section>
  `;
}

/** @param {{term: Term}} props */
function TermBlock({ term: t }) {
  return html`
    <div class="block glossary-term">
      <div class="block-row">
        <span class="bullet"></span>
        <div class="block-text">
          <div class="term-line">
            <a class="term-name" href=${entityHref(t.id)}>${t.title}</a>
            ${t.aliases.length > 0 && html`<span class="aliases">aka ${t.aliases.join(" · ")}</span>`}
          </div>
          ${t.definition.trim()
            ? html`<div class="markdown definition" dangerouslySetInnerHTML=${{ __html: renderMarkdown(t.definition, resolveMention) }}></div>`
            : html`<p class="definition muted">No definition yet.</p>`}
        </div>
      </div>
    </div>
  `;
}
