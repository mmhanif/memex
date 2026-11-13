// @ts-check
// Lucide icons (vendored SVGs), drawn as CSS masks so they take the text colour.

import { html } from "./state.js";

/** @param {{name: string}} props */
export function Icon({ name }) {
  return html`<span class="icon icon-${name}" aria-hidden="true"></span>`;
}
