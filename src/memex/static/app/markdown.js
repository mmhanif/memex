// @ts-check
// Rendering safety (SPEC §11.1, R17): markdown-it with raw HTML off, then DOMPurify.

import DOMPurify from "dompurify";
import MarkdownIt from "markdown-it";

const md = new MarkdownIt({ html: false, linkify: false });

// http, https, mailto and in-app (#/…) links; inline images as data: URLs.
const SAFE_URL = /^(https?:|mailto:|#|data:image\/(png|gif|jpeg|webp);)/i;
md.validateLink = (url) => SAFE_URL.test(url.trim());

// A small in-house task-list rule: `- [ ] x` and `- [x] x` render as disabled checkboxes.
const TASK = /^\[([ xX])\] /;
md.core.ruler.after("inline", "task-lists", (state) => {
  const tokens = state.tokens;
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
    const box = new state.Token("html_inline", "", 0);
    const checked = match[1] === " " ? "" : " checked";
    box.content = `<input type="checkbox" disabled${checked}> `;
    inline.children.unshift(box);
    tokens[i - 2].attrJoin("class", "task-list-item");
  }
  return false;
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
 */
export function renderMarkdown(source) {
  return DOMPurify.sanitize(md.render(source), {
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
