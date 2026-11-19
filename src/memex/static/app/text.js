// @ts-check
// Matching ignores case and accents (SPEC §9.3). One fold() shared by the person
// picker, the Ctrl-K palette, Search highlighting and the Bookmark Label filter, so
// they agree on what matches; folding() lets the ones that highlight a match find it
// again in the original text.

/**
 * `text` for comparison ignoring case and accents: compatibility-decomposed, every
 * combining mark (any script, not just U+0300–U+036F) dropped, then lowercased.
 * @param {string} text
 */
export function fold(text) {
  return folding(text).folded;
}

/**
 * fold(`text`) with a way back. Folding changes the length (marks go, `ﬁ` becomes
 * `fi`), so a match in `folded` can't be sliced out of `text` at the same indices:
 * `span(start, end)` turns a [start, end) match in `folded` into the [start, end) of
 * `text` it came from, whole characters only and swallowing marks that folded away.
 * @param {string} text
 * @returns {{folded: string, span: (start: number, end: number) => [number, number]}}
 */
export function folding(text) {
  /** @type {{piece: string, at: number}[]} */
  const pieces = [];
  let at = 0;
  for (const c of text) {
    pieces.push({ piece: c.normalize("NFKD").replace(/\p{M}/gu, ""), at });
    at += c.length;
  }
  // Lowercase the whole string so context-sensitive rules (Greek final sigma) hold; if
  // that changes the length, lowercase piece by piece so the map stays true.
  const joined = pieces.map((p) => p.piece).join("");
  let folded = joined.toLowerCase();
  if (folded.length !== joined.length) {
    for (const p of pieces) p.piece = p.piece.toLowerCase();
    folded = pieces.map((p) => p.piece).join("");
  }
  // from[i]: where in `text` the character that gave folded[i] starts.
  /** @type {number[]} */
  const from = [];
  for (const p of pieces) for (let i = 0; i < p.piece.length; i++) from.push(p.at);
  from.push(text.length);
  return {
    folded,
    span(start, end) {
      // A match ending inside one character's folding (`f` of `ﬁ`) takes all of it.
      let stop = end;
      while (stop < folded.length && from[stop] === from[end - 1]) stop++;
      return [from[start], from[stop]];
    },
  };
}
