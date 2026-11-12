# Offline-bundleable frontend libraries

Ticket: [03-frontend-libraries](../../.scratch/memex-spec/issues/03-frontend-libraries.md)
Researched: 2026-11-11 (versions are the npm `latest` dist-tag on that date)

## Question

Which frontend libraries can be vendored as static files (no CDN, ideally no Node build step on the workstation) for:

- Markdown rendering with GFM and frontmatter stripping
- HTML sanitisation
- the editor
- the Mind Map
- an optional lightweight UI framework

For each, the ticket asks for licence, bundle size, whether a prebuilt ESM/UMD file exists, and whether fonts/icons can be self-hosted.

## Method

- **Metadata:** licence, version and dependencies come from the npm registry (`https://registry.npmjs.org/<pkg>/latest`).
- **Bundle sizes:** I downloaded each published tarball and measured the shipped files. "gz" means `gzip -9`.
- **CodeMirror 6:** npm ships no browser bundle for it, so I bundled it with esbuild (`--bundle --minify --format=esm`) and measured the output.
- **Parser behaviour:** I checked it by running markdown-it 15.0.3 and marked 18.2.0 under Node 23 on a sample document. The sample had frontmatter, a table, strikethrough, a bare URL, task-list items and a raw `<script>`.
- **Network calls:** I searched every candidate's browser build for hard-coded `http(s)://` URLs, looking for anything that would fetch from the network at runtime.

## Summary table

| Role | Package (version) | Licence | Prebuilt browser file (in npm tarball) | Size min / gz | Air-gap notes |
|---|---|---|---|---|---|
| Markdown | markdown-it 15.0.3 | MIT (deps: entities BSD-2-Clause; linkify-it, mdurl, uc.micro, punycode.js MIT) | `dist/browser/markdown-it.umd.min.js` (UMD, global `markdownit`), `dist/browser/markdown-it.esm.min.mjs` | 101 KB / 41 KB (UMD) | Self-contained. Raw HTML is escaped by default |
| Markdown | marked 18.2.0 | MIT, zero deps | `lib/marked.umd.js`, `lib/marked.esm.js` | 51 KB / 16 KB | Self-contained. Passes raw HTML through |
| Frontmatter plugin | markdown-it-front-matter 0.2.4 | MIT | `index.js` (CommonJS only) | 3.6 KB / 1.2 KB | Easier to write yourself (see below) |
| YAML (only if the client parses it) | js-yaml 5.5.0 | MIT | `dist/browser/js-yaml.umd.min.js`, `.esm.min.mjs` | 63 KB / 19 KB | Self-contained |
| Sanitiser | dompurify 3.4.17 | MPL-2.0 OR Apache-2.0 | `dist/purify.min.js` (UMD), `dist/purify.es.mjs` | 30 KB / 12 KB | Self-contained |
| Editor | plain `<textarea>` | n/a | n/a | 0 | n/a |
| Editor | CodeMirror 6 (`codemirror` 6.0.2 + `@codemirror/lang-markdown` 6.5.2) | MIT (all 22 transitive packages) | **None.** ESM with bare imports only | measured bundle: basicSetup + markdown 613 KB / 208 KB; minimal setup + markdown 517 KB / 178 KB | Needs a one-off bundle step |
| Editor (alt) | overtype 2.7.0 | MIT | `dist/overtype.min.js` | 140 KB / 40 KB | Self-contained |
| Mind Map | cytoscape 3.35.0 | MIT, zero deps | `dist/cytoscape.min.js` (UMD), `dist/cytoscape.esm.min.mjs` | 443 KB / 139 KB | Self-contained |
| Mind Map | markmap-view 0.18.13 | MIT | `dist/browser/index.js` (IIFE, needs global `d3`) | 50 KB / 12 KB, plus d3 below | Self-contained. **Avoid markmap-lib / markmap-autoloader** (see below) |
| Mind Map | vis-network 10.1.5 | Apache-2.0 OR MIT | `standalone/umd/vis-network.min.js`, `standalone/esm/vis-network.min.js` | 654 KB / 155 KB | Self-contained, CSS injected |
| Mind Map | d3 7.9.2 | ISC | `dist/d3.min.js` (UMD) | 281 KB / 93 KB | Self-contained |
| UI | preact 11.2.0 | MIT | `dist/preact.mjs`, `hooks/dist/hooks.mjs` (ESM, bare `preact` import) | 12 KB / 5 KB (core) | Needs an import map |
| UI | htm 3.1.1 | Apache-2.0 | `dist/htm.module.js`. `preact/standalone.module.js` bundles Preact 10 + hooks + htm | 1.2 KB / 0.7 KB; standalone 13 KB / 5.3 KB | Self-contained |
| UI | alpinejs 3.17.5 | MIT (bundles @vue/reactivity, MIT) | `dist/cdn.min.js`, `dist/module.esm.min.js` | 56 KB / 20 KB | Self-contained. Needs `unsafe-eval` unless you use the CSP build |
| UI | lit 3.3.3 | BSD-3-Clause | **None in npm.** Single-file bundles are published in the `lit/dist` GitHub repo | n/a | Download once and vendor |
| UI | svelte 5.57.3 | MIT | n/a. It is a compiler | n/a | **Requires a build step** |
| Icons | lucide-static 1.72.0 / bootstrap-icons 1.13.2 | ISC / MIT | Static SVG files and sprites (+ icon font) | per icon | Self-hostable |
| Fonts | @fontsource/inter, @fontsource/jetbrains-mono 5.3.0 | OFL-1.1 | `.woff2` files + CSS | about 20-50 KB per weight | Self-hostable |

Sources: npm registry entries for each package, e.g. <https://www.npmjs.com/package/markdown-it>, <https://www.npmjs.com/package/marked>, <https://www.npmjs.com/package/dompurify>, <https://www.npmjs.com/package/cytoscape>, <https://www.npmjs.com/package/markmap-view>, <https://www.npmjs.com/package/vis-network>, <https://www.npmjs.com/package/d3>, <https://www.npmjs.com/package/preact>, <https://www.npmjs.com/package/htm>, <https://www.npmjs.com/package/alpinejs>, <https://www.npmjs.com/package/lit>, <https://www.npmjs.com/package/svelte>. Each tarball contains a `LICENSE` file that agrees with the registry field. DOMPurify ships both `LICENSE` (Apache-2.0) and `LICENSE-MPL`. vis-network ships `LICENSE-APACHE-2.0` and `LICENSE-MIT`.

## Findings

### 1. Markdown rendering: markdown-it vs. marked

Neither parser strips YAML frontmatter natively. Both render a leading `---` block as `<hr>` + `<h2>`, which I confirmed by running them.

| Feature (tested) | markdown-it 15 (defaults) | marked 18 (defaults) |
|---|---|---|
| GFM tables | yes | yes |
| Strikethrough | yes (`<s>`) | yes (`<del>`) |
| Task lists `- [ ]` | **no** (needs a plugin; `markdown-it-task-lists` is ISC but last published 2018) | **yes** (disabled checkboxes) |
| Bare-URL autolink | opt-in (`linkify: true`) | yes |
| Raw HTML such as `<script>` | **escaped** (`html: false` is the default) | **passed through verbatim** |
| Source line map on tokens (useful for editor/preview scroll sync) | yes (`token.map`) | no |
| Plugin ecosystem | large, rule-based | extensions API |

**Frontmatter stripping.** Two options:

- Use `markdown-it-front-matter`. It is CommonJS only, so you would wrap it yourself.
- Strip the frontmatter yourself. A leading `^---\r?\n[\s\S]*?\r?\n---\r?\n` regex is enough for preview.

The backend is Python and already has to parse frontmatter. The cleaner split is for `GET /api/files` to return the body and the frontmatter separately, or for the client to strip the block only for the preview. Then no YAML parser is needed in the browser. If one is needed later, js-yaml 5 ships a browser build (19 KB gz).

**Verdict.** Both are fine.

- **markdown-it** is the safer default (escapes HTML) and offers line maps for scroll sync. It costs 25 KB gz more and needs task-list support. That is a small plugin or about 30 lines of a core rule.
- **marked** is smaller and does task lists out of the box. Its output must always go through DOMPurify.

### 2. Sanitisation: DOMPurify

- **Licence:** dual-licensed MPL-2.0 OR Apache-2.0. Apache-2.0 is enterprise-friendly ([README](https://github.com/cure53/DOMPurify), `LICENSE`, `LICENSE-MPL` in the tarball).
- **Files:** the README recommends `dist/purify.min.js` as the "minified and tested production version", loaded with a plain `<script>` tag. An ES module (`dist/purify.es.mjs`) also ships.
- **Size:** 12 KB gz.
- **Browsers:** all modern browsers. No IE support.

**Use it regardless of parser.** Workspace files are edited externally by VS Code and agents (map.md Notes), so preview HTML should never be trusted.

### 3. Editor

**Plain `<textarea>`.** Zero dependencies, accessible, no bundling. It has no syntax highlighting, though tab/indent and list-continuation can be added in about 100 lines.

**CodeMirror 6.**

- **No usable browser file on npm.** The official guide says the modules "aren't directly loadable by the browser" and that ES module dependency handling is "still too primitive to load collections of NPM-distributed modules", so a bundler is required (<https://codemirror.net/examples/bundle/>).
- **Bundle size:** I measured an esbuild bundle of `basicSetup` + `markdown()` at 613 KB min / 208 KB gz. A minimal setup (view, state, history/keymap, highlighting, markdown) came to 517 KB / 178 KB.
- **Why it is that large:** `@codemirror/lang-markdown` pulls in `lang-html`, which pulls in `lang-css` and `lang-javascript` for embedded code.
- **Licence:** every one of the 22 resolved packages is MIT.
- **Feasible offline:** run the bundle **once on a developer machine** and commit the single output `.js` to the repo's vendored static folder. The workstation never needs Node. The cost is a small `vendor/build-codemirror` script and a regeneration step when upgrading.

**OverType 2.7.0.**

- MIT, ships a prebuilt `dist/overtype.min.js` (40 KB gz).
- It is a transparent-textarea overlay that styles Markdown in place.
- It is a middle ground: no build step and some highlighting. It is a much younger, single-maintainer project than CodeMirror.

**Others considered and not recommended:**

- **EasyMDE** depends on CodeMirror 5 (legacy) and marked.
- **Toast UI Editor 3.2.2** is a large ProseMirror stack.
- **ink-mde** is CM6 + Solid and still needs bundling.

### 4. Mind Map

The context matters here:

- Mind Maps are **read-only, centred on a Theme or on People, and nodes click through to the Entity** (map.md Notes).
- Relationships are frontmatter references.
- **The People map is a graph, not a tree.** One Stakeholder can be tagged to several Themes, Projects and Deliverables.
- The data comes from the backend's Entity index, **not from Markdown**.

**Cytoscape.js 3.35.0.**

- MIT, "No external dependencies" (<https://js.cytoscape.org/>).
- Ships `dist/cytoscape.min.js` (UMD) and `dist/cytoscape.esm.min.mjs`, 139 KB gz.
- Built-in layouts, confirmed in the shipped source: `null`, `random`, `preset`, `grid`, `circle`, `concentric`, `breadthfirst`, `cose`. `breadthfirst` with a root, or `concentric`, fits an "Entity at the centre" view directly.
- Tap events give click-through. Renders to canvas and handles graphs and compound nodes.
- No network URLs in the build.

**markmap-view 0.18.13 + d3.**

- `markmap-view`'s browser build is an IIFE that takes `d3` as a global (`})(this.markmap = ..., d3)`). Total about 105 KB gz.
- `Markmap.create(svg, opts, data)` renders a **tree** of `{content, children}` nodes with a nice collapsible horizontal layout (source: `dist/browser/index.js`).
- Good for the Theme → Project → Deliverable hierarchy. It cannot express a Person linked to many Entities without duplicating nodes.
- **Air-gap caution:** the `markmap-lib` browser build (171 KB gz) and `markmap-autoloader` contain hard-coded jsDelivr/unpkg URL providers (`https://cdn.jsdelivr.net/npm/${path}`, `https://unpkg.com/${path}`) used to load KaTeX, highlight.js and other assets. Use **only** `markmap-view` with locally built data, or not at all.
- The markmap docs site returned 404 for the package doc pages on the research date, so these facts are from the shipped code.

**vis-network 10.1.5.**

- Apache-2.0 OR MIT. Standalone UMD/ESM builds, 155 KB gz.
- Physics-based network with hierarchical layout.
- Capable, but the largest option, and Cytoscape covers the same ground.

**D3 7.9.2.**

- ISC, `dist/d3.min.js` 93 KB gz.
- Maximum control, but you write the layout, zoom and interaction yourself (`d3-hierarchy` for trees, `d3-force` for graphs).
- Only worth it if the other options' visual style is unacceptable.

### 5. Optional UI framework

**Preact 11.2.0 + htm 3.1.1.**

- Preact's official no-build guide uses an **import map** plus **htm** tagged templates, so "no build step is needed" (<https://preactjs.com/guide/v10/no-build-workflows>).
- The guide's examples point the import map at esm.sh. For Memex the entries just point at vendored files instead: `preact/dist/preact.mjs` and `preact/hooks/dist/hooks.mjs`, about 5 KB gz for the core.
- Simplest alternative: `htm/preact/standalone.module.js` is one self-contained file (5.3 KB gz) bundling htm + Preact **10** + hooks (htm's devDependency is `preact ^10.2.0`). htm itself was last published 2022-04-26: stable, but no longer actively developed.
- Licences: MIT (Preact) and Apache-2.0 (htm).

**Alpine.js 3.17.5.**

- MIT. `dist/cdn.min.js` is the self-contained file despite its name: it makes no CDN fetches, and the only URL inside is an error-message link. 20 KB gz.
- The standard build evaluates attribute expressions with runtime-created functions, which violates CSP `unsafe-eval`. The CSP build drops assignments, arrow functions, template literals, globals and `x-html` (<https://alpinejs.dev/advanced/csp>).
- Fine for small sprinkles. Awkward for a tree + editor + views SPA.

**Lit 3.3.3.**

- BSD-3-Clause. The npm package is ESM with bare imports and spans 4 packages.
- The official "pre-built, single-file bundles" (`lit-core.min.js`, `lit-all.min.js`) are published in the `lit/dist` GitHub repo and documented via jsDelivr URLs (<https://lit.dev/docs/getting-started/>).
- They can be downloaded once and vendored. The docs caution that they include more code than you may need.

**Svelte 5.57.3.** MIT, but it is a compiler. Output only exists after a Node build, so it fails the "no Node build step" preference.

**Vanilla JS + ES modules.** Viable for this size of app. It would mean hand-written DOM updates for the tree and views.

### 6. Fonts and icons

All self-hostable. None of the candidates above require web fonts.

- **Fonts:** a system font stack needs nothing. For a fixed look, `@fontsource/*` (OFL-1.1) ships `.woff2` files + CSS that can be copied into `static/fonts/` and referenced with relative URLs.
- **Icons:** `lucide-static` (ISC) and `bootstrap-icons` (MIT) ship plain SVG files and sprites, so inline the few needed icons or serve a sprite.
- vis-network injects its own CSS. Cytoscape draws to canvas and needs no assets.

## Recommendation

1. **Markdown:** **markdown-it 15** (`dist/browser/markdown-it.esm.min.mjs` or the UMD file, MIT, 41 KB gz).
   - Raw HTML stays escaped by default, and line maps are available for scroll sync.
   - Add a small in-house task-list rule.
   - Strip frontmatter in the client with a regex for preview. Have the Python backend own YAML parsing, so there is no YAML library in the browser.
   - **marked** is an acceptable lighter alternative if task lists out of the box matter more.
2. **Sanitiser:** **DOMPurify 3** (`dist/purify.min.js`, Apache-2.0 option, 12 KB gz). Run every preview render through it.
3. **Editor:** ship a **plain `<textarea>`** first (zero deps), with small helpers for tab and list-continuation.
   - If highlighting is wanted later, build **CodeMirror 6** once on a dev machine with esbuild and commit the single bundle. Budget about 180-210 KB gz. All MIT. No Node needed on the workstation.
4. **Mind Map:** **Cytoscape.js** (`dist/cytoscape.esm.min.mjs`, MIT, zero deps, 139 KB gz).
   - It handles the People maps as true graphs. `breadthfirst`/`concentric` layouts centre on the focal Entity, and tap events give click-through.
   - Do **not** vendor `markmap-lib` or `markmap-autoloader`: they contain CDN loader URLs.
5. **UI framework:** **Preact + htm via a vendored import map**, or the single-file `htm/preact/standalone.module.js` for zero configuration. MIT/Apache-2.0, about 5 KB gz, no build step.
   - Avoid Svelte (needs a compiler).
   - Alpine needs `unsafe-eval` or its restricted CSP build.
6. **Fonts/icons:** system font stack (or `@fontsource` woff2, OFL), and Lucide or Bootstrap Icons SVGs copied into `static/`.

**Total vendored payload** for the recommended set without CodeMirror: about 200 KB gz, all prebuilt, no Node at runtime or install.

### Open caveats

- Pin exact versions in a `static/vendor/VERSIONS` manifest with the licence files copied alongside, so the internal licence review has one place to look.
- Check whether the corporate browser baseline supports import maps. All current evergreen browsers do; if it does not, use the htm standalone file.
