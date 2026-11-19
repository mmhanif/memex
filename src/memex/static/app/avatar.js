// @ts-check
// A person's initials in a round chip, the one avatar used everywhere.

import { html, meId, sameId } from "./state.js";

/**
 * @typedef {import("./fields.js").Summary} Summary
 * @typedef {{
 *   person?: Summary,
 *   id?: string,
 *   name?: string,
 *   kind?: "stakeholder",
 *   size?: "large",
 *   alone?: boolean,
 * }} AvatarProps
 */

/** @param {string} name */
export function initials(name) {
  const words = name.split(/[\s-]+/).filter(Boolean);
  return (words.length > 1 ? words[0][0] + words[words.length - 1][0] : name.slice(0, 2)).toUpperCase();
}

/**
 * A person's initials: dark for Me, outlined for a Stakeholder. Pass the `person`, or their
 * `id` and `name` when only those are to hand. A person's own kinds outline them when they
 * are a Stakeholder and not a Team Member; `kind="stakeholder"` outlines whoever it is (a
 * Stakeholders list). `size="large"` is the Person View's header, in link tint whoever it is.
 * The name is the tooltip; the avatar is hidden from screen readers since the name sits
 * beside it, unless it stands `alone`, when it is an image labelled with the name.
 * @param {AvatarProps} props
 */
export function Avatar({ person, id = person?.id, name = person?.title ?? id ?? "", kind, size, alone = false }) {
  const kinds = person?.fields.kind;
  const stakeholder =
    kind === "stakeholder" || (Array.isArray(kinds) && kinds.includes("stakeholder") && !kinds.includes("team-member"));
  const look = size === "large" ? "" : id && sameId(id, meId()) ? "me" : stakeholder ? "stakeholder" : "";
  const cls = ["avatar", look, size].filter(Boolean).join(" ");
  return alone
    ? html`<span class=${cls} title=${name} role="img" aria-label=${name}>${initials(name)}</span>`
    : html`<span class=${cls} title=${name} aria-hidden="true">${initials(name)}</span>`;
}
