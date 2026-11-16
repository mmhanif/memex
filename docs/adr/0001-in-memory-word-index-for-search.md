---
status: accepted
---

# In-memory word index for search

SPEC §9.1 says search runs over the parse cache "so there is no separate index", with SQLite FTS5 as the fallback if p95 exceeds 50 ms on a 5,000-file / 50 MB Workspace. Scanning the cached text per query could not meet that budget, so `core/textindex.py` keeps an in-memory word index derived from the parse cache: each file's folded names, fields and body, plus a sorted vocabulary mapping every folded word to an int bitmask of the files that contain it. Nothing is written to disk, and the index is updated file by file when a hash changes. This keeps to the spirit of §9.1: the cache is still the only source, there is no on-disk cache, and FTS5 is not needed.

## Considered options

Measured on the §16.8 Workspace (Zipf prose, 16.5k distinct words) on an M-series Mac:

- **Scan each file's folded text per term.** A missed term costs one `str.find` over 50 MB, about 25–30 ms on its own, whatever the encoding. Phrases and snippets pushed queries to 40–700 ms. Rejected.
- **One joined corpus of each file's distinct words**, searched with `find(" " + term)`. That corpus is 22 MB, so each term still cost about 15 ms per scan. Multi-word queries landed at 40–55 ms, too close to the budget for the slower Windows CI runner. Rejected.
- **SQLite FTS5**, the spec's fallback. It adds a disk cache outside the Workspace. Its tokenizers also don't give §9.3's matching directly: fuzzy subsequence on names, and word-prefix with accent folding. Not needed while the in-memory index holds the budget.
- **Chosen: a vocabulary with bitmasks.** Word-prefix becomes a bisect plus an OR of masks; terms combine with `&`; names match with one regex over all names. Phrases and terms with punctuation take candidates from the vocabulary and are then checked against the folded body. p95 is about 30 ms.

## Consequences

- **Memory:** about 140 MB on top of the parse cache for a 50 MB Workspace. Folded bodies are kept so phrase checks and snippets don't have to fold text again.
- **First build:** about 3 s at 50 MB. The app warms the index on a background thread at startup (`search.warm`), and searches wait for it rather than build their own.
- **Change tracking:** `Cache.generation` moves on every change, so the index resyncs only the files whose hash changed. One edit costs about 20 ms on the next search.
- **The FTS5 trigger still applies.** If the perf job (§16.8) fails with this index, adding FTS5 is the next step.
