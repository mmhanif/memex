// @ts-check
// Matching ignores case and accents (SPEC §9.3). One fold() shared by the person
// picker, the Ctrl-K palette, Search highlighting and the Bookmark Label filter, so
// they agree on what matches; folding() lets the ones that highlight a match find it
// again in the original text.

/**
 * `text` for comparison ignoring case and accents: compatibility-decomposed, every
 * mark (`\p{M}`, any script) dropped, then case-folded (`Straße` → `strasse`). The
 * server's fold() (core/names.py) follows the same rule; tests/fold_cases.py holds the
 * cases both are checked on.
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
    const bare = c.normalize("NFKD").replace(/\p{M}/gu, "");
    pieces.push({ piece: Array.from(bare, caseFold).join(""), at });
    at += c.length;
  }
  const folded = pieces.map((p) => p.piece).join("");
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

const CHEROKEE = /\p{Script=Cherokee}/u;

/**
 * One character case-folded as Python's `str.casefold()` does it (Unicode full case
 * folding), which toLowerCase() alone falls short of: `ß` → `ss`, final `ς` → `σ`.
 * Lowercasing the uppercase gets those; the exceptions to that are handled first. When
 * written, this matched casefold() on every character Unicode 16 assigns.
 * @param {string} c
 */
function caseFold(c) {
  if (c === "ı") return c; // dotless i: uppercases to I, but doesn't fold to i
  if (CHEROKEE.test(c)) return c.toUpperCase(); // Cherokee folds to its uppercase
  return c.toLowerCase().toUpperCase().toLowerCase();
}
