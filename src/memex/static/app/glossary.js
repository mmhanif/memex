// @ts-check
// `#/glossary` (SPEC §10.2): every Glossary Term A–Z, definitions inline, aliases under each.

import { describe } from "./api.js";
import { renderMarkdown } from "./markdown.js";
import { openNew } from "./newform.js";
import { entityHref } from "./router.js";
import { html, resolveMention, tree, useView } from "./state.js";

/**
 * @typedef {{id: string, title: string, aliases: string[], definition: string}} Term
 * @typedef {{letter: string, terms: Term[]}} Group
 */

export function GlossaryPage() {
  const { data, error } = useView("/api/views/glossary");
  const groups = /** @type {{groups: Group[]} | null} */ (data)?.groups;
  const readOnly = tree.value?.workspace.read_only ?? false;

  return html`
    <section class="glossary-page">
      <header class="page-head">
        <h1>Glossary</h1>
        ${!readOnly && html`<button type="button" onClick=${() => openNew("glossary-term")}>New Glossary Term</button>`}
      </header>
      ${error && html`<p class="error-text" role="alert">${describe(error)}</p>`}
      ${groups && !groups.length && html`<p class="muted">No Glossary Terms yet.</p>`}
      ${groups &&
      groups.length > 0 &&
      html`<nav class="letters" aria-label="Letters">
        ${groups.map((g) => html`<a key=${g.letter} href=${`#/glossary`} onClick=${(/** @type {MouseEvent} */ e) => {
          e.preventDefault();
          document.getElementById(`glossary-${g.letter}`)?.scrollIntoView({ block: "start" });
        }}>${g.letter}</a>`)}
      </nav>`}
      ${groups?.map(
        (g) => html`
          <section key=${g.letter} class="glossary-group" id=${`glossary-${g.letter}`}>
            <h2>${g.letter}</h2>
            <dl>
              ${g.terms.map(
                (t) => html`
                  <dt key=${`t:${t.id}`}><a href=${entityHref(t.id)}>${t.title}</a></dt>
                  <dd key=${`d:${t.id}`}>
                    ${t.aliases.length > 0 && html`<p class="aliases muted">Also: ${t.aliases.join(", ")}</p>`}
                    ${t.definition.trim()
                      ? html`<div class="markdown" dangerouslySetInnerHTML=${{ __html: renderMarkdown(t.definition, resolveMention) }}></div>`
                      : html`<p class="muted">No definition yet.</p>`}
                  </dd>
                `,
              )}
            </dl>
          </section>
        `,
      )}
    </section>
  `;
}
