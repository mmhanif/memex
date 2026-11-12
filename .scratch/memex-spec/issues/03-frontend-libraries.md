# Offline-bundleable frontend libraries

Type: research
Status: resolved
Blocked by:

## Question

Which frontend libraries can be vendored as static files (no CDN, ideally no Node build step on the workstation) for: Markdown rendering with GFM + frontmatter stripping (markdown-it vs. marked), HTML sanitisation (DOMPurify), the editor (plain textarea vs. CodeMirror 6 vs. others; note CM6 requires bundling), the Mind Map (markmap, Cytoscape.js, vis-network, D3), and an optional lightweight UI framework (Preact+htm, Alpine.js, Lit, Svelte-compiled). Report licence, bundle size, whether a prebuilt ESM/UMD file exists, and whether fonts/icons can be self-hosted.

## Research

Findings: [docs/research/frontend-libraries.md](../../../docs/research/frontend-libraries.md)

## Answer

Per [frontend-libraries research](../../../docs/research/frontend-libraries.md), with user fact: browser is **Chrome 150** (import maps supported, no build step needed for the app shell).
- Markdown: markdown-it (raw HTML off) + small task-list rule; every preview through DOMPurify. Frontmatter stripped client-side for preview only; backend owns YAML.
- Editor: plain `<textarea>` for v1; CodeMirror 6 optional later as a single prebuilt bundle committed to the repo.
- Mind Maps: Cytoscape.js. Not markmap (hard-coded CDN URLs).
- UI: Preact + htm via import map over vendored ESM files.
- Fonts/icons self-hosted (system fonts or @fontsource; Lucide/Bootstrap Icons SVGs).
