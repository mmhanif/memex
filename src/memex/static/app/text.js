// @ts-check
// Matching ignores case and accents (SPEC §9.3). One fold() shared by the person
// picker, the Ctrl-K palette, Search highlighting and the Bookmark Label filter, so
// they agree on what matches.

/**
 * `text` for comparison ignoring case and accents: compatibility-decomposed, every
 * combining mark (any script, not just U+0300–U+036F) dropped, then lowercased.
 * @param {string} text
 */
export function fold(text) {
  return text.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase();
}
