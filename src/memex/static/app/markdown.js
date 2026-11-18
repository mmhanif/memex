// @ts-check
// Rendering safety (SPEC §11.1, R17): markdown-it with raw HTML off, then DOMPurify.

import DOMPurify from "dompurify";
import MarkdownIt from "markdown-it";

const md = new MarkdownIt({ html: false, linkify: false });

// http, https, mailto and in-app (#/…) links; inline images as data: URLs.
const SAFE_URL = /^(https?:|mailto:|#|data:image\/(png|gif|jpeg|webp);)/i;
md.validateLink = (url) => SAFE_URL.test(url.trim());

// A small in-house task-list rule: `- [ ] x` and `- [x] x` render as disabled checkboxes.
// An item whose only content is a To-do Mention renders as a live To-do row instead
// (§6.4): its box shows and edits the To-do's status, never the Note's `[ ]`.
const TASK = /^\[([ xX])\] /;
const SOLE_MENTION = /^\[[ xX]\] \[\[([^\[\]\n]+?)\]\]\s*$/;
md.core.ruler.after("inline", "task-lists", (state) => {
  const tokens = state.tokens;
  const resolveTodo = /** @type {TodoResolver | undefined} */ (state.env.resolveTodo);
  for (let i = 2; i < tokens.length; i++) {
    const inline = tokens[i];
    if (
      inline.type !== "inline" ||
      tokens[i - 1].type !== "paragraph_open" ||
      tokens[i - 2].type !== "list_item_open"
    ) {
      continue;
    }
    const first = inline.children?.[0];
    const match = first?.type === "text" ? TASK.exec(first.content) : null;
    if (!first || !inline.children || !match) continue;
    first.content = first.content.slice(match[0].length);
    const sole = SOLE_MENTION.exec(inline.content);
    const todo = sole && resolveTodo ? resolveTodo(sole[1].trim()) : null;
    const box = new state.Token("html_inline", "", 0);
    if (todo) {
      const id = escape(sole?.[1].trim() ?? "");
      const checked = todo.finished ? " checked" : "";
      box.content = `<input type="checkbox" class="checkbox" data-todo="${id}" aria-label="Done: ${escape(todo.title)}"${checked}> `;
      const meta = new state.Token("html_inline", "", 0);
      meta.content = todo.meta.map((m) => ` <span class="${escape(m.class)}">${escape(m.text)}</span>`).join("");
      inline.children.push(meta);
      tokens[i - 2].attrJoin("class", `task-list-item todo-ref${todo.finished ? " finished" : ""}`);
    } else {
      const checked = match[1] === " " ? "" : " checked";
      box.content = `<input type="checkbox" class="checkbox" disabled${checked}> `;
      tokens[i - 2].attrJoin("class", "task-list-item");
    }
    inline.children.unshift(box);
  }
  return false;
});

/** @param {string} text */
function escape(text) {
  return md.utils.escapeHtml(text);
}

/**
 * A To-do a converted task item names: whether it's finished, its title, and the bits
 * shown after it (status, Owner, due), or null when the Id names no To-do.
 * @typedef {(id: string) => {finished: boolean, title: string, meta: {class: string, text: string}[]} | null} TodoResolver
 */

/**
 * What a Mention names: its title, or nothing when it's a Broken Reference (§4.4, §4.6).
 * @typedef {(id: string) => {title: string} | null} MentionResolver
 */

// `[[id]]` → an in-app link. An inline rule, so code spans and blocks never hold Mentions.
const MENTION = /^\[\[([^\[\]\n]+?)\]\]/;
md.inline.ruler.before("link", "mention", (state, silent) => {
  if (state.src.charCodeAt(state.pos) !== 0x5b || state.src.charCodeAt(state.pos + 1) !== 0x5b) {
    return false;
  }
  const match = MENTION.exec(state.src.slice(state.pos));
  if (!match) return false;
  if (!silent) {
    const id = match[1].trim();
    const resolve = /** @type {MentionResolver | undefined} */ (state.env.resolveMention);
    const target = resolve ? resolve(id) : { title: id };
    const open = state.push("link_open", "a", 1);
    open.attrs = [
      ["href", `#/e/${encodeURIComponent(id)}`],
      ["class", target ? "mention" : "mention broken"],
    ];
    if (!target) open.attrs.push(["title", `Broken reference: nothing is called ${id}`]);
    state.push("text", "", 0).content = target ? target.title : id;
    state.push("link_close", "a", -1);
  }
  state.pos += match[0].length;
  return true;
});

DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  // validateLink can't tell links from images: data: URLs are for inline images only.
  if (node instanceof HTMLAnchorElement && /^\s*data:/i.test(node.getAttribute("href") ?? "")) {
    node.removeAttribute("href");
  }
  if (node instanceof HTMLAnchorElement && /^(https?:|mailto:)/i.test(node.getAttribute("href") ?? "")) {
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noopener noreferrer");
  }
});

/**
 * Markdown → sanitised HTML. Ids and names get the `user-content-` prefix, so a
 * heading can never clobber a global like `window.foo`.
 * @param {string} source
 * @param {MentionResolver} [resolveMention]
 * @param {TodoResolver} [resolveTodo]
 */
export function renderMarkdown(source, resolveMention, resolveTodo) {
  return DOMPurify.sanitize(md.render(source, { resolveMention, resolveTodo }), {
    SANITIZE_NAMED_PROPS: true,
    FORBID_TAGS: ["style", "form"],
    FORBID_ATTR: ["style"],
  });
}

/**
 * Split a raw file into its frontmatter block (shown as text, never HTML) and body (§5.2).
 * @param {string} text
 * @returns {{frontmatter: string | null, body: string}}
 */
export function splitFrontmatter(text) {
  const lines = text.split("\n");
  if (lines[0] !== "---") return { frontmatter: null, body: text };
  const end = lines.indexOf("---", 1);
  if (end < 0) return { frontmatter: null, body: text };
  return {
    frontmatter: lines.slice(1, end).join("\n"),
    body: lines.slice(end + 1).join("\n"),
  };
}
