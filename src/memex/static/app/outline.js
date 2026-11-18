// @ts-check
// A rendered body as outline blocks (SPEC §11.5): each heading becomes a block whose
// children (what follows, up to the next heading of its level or higher) hang off a guide,
// and every bulleted item gets a bullet. A bullet whose block has children is a button
// that collapses them. Collapsing is a view of the page only: nothing is written.

const HEADING = /^H([1-6])$/;

/**
 * Sanitised HTML in, the same content as outline blocks out. It only moves nodes and adds
 * bullets, so it can't make the HTML less safe.
 * @param {string} source HTML from `renderMarkdown`
 */
export function outlineHtml(source) {
  const template = document.createElement("template");
  template.innerHTML = source;
  const root = template.content;
  root.querySelectorAll("ul > li").forEach((li) => li.prepend(bullet(li, hasChildList(li))));
  groupHeadings(root);
  return [...root.childNodes].map((n) => (n instanceof Element ? n.outerHTML : n.textContent ?? "")).join("");
}

/**
 * Wrap each heading and what follows it in a block. A deeper heading nests inside.
 * @param {DocumentFragment} root
 */
function groupHeadings(root) {
  /** @type {{level: number, children: Node}[]} */
  const stack = [{ level: 0, children: root }];
  for (const node of [...root.childNodes]) {
    const match = node instanceof Element ? HEADING.exec(node.tagName) : null;
    if (!match) {
      stack[stack.length - 1].children.appendChild(node);
      continue;
    }
    const level = Number(match[1]);
    while (stack[stack.length - 1].level >= level) stack.pop();
    const heading = /** @type {Element} */ (node);
    const block = document.createElement("section");
    block.className = "block block-heading";
    const row = document.createElement("div");
    row.className = "block-row";
    const children = document.createElement("div");
    children.className = "block-children";
    heading.classList.add("block-text");
    stack[stack.length - 1].children.appendChild(block);
    row.append(bullet(heading, true), heading);
    block.append(row, children);
    stack.push({ level, children });
  }
  // A heading with nothing under it has nothing to collapse.
  root.querySelectorAll(".block-heading").forEach((block) => {
    const children = block.querySelector(":scope > .block-children");
    if (children && !children.textContent?.trim() && !children.querySelector("img, input")) {
      children.remove();
      const button = block.querySelector(":scope > .block-row > .bullet");
      button?.replaceWith(bullet(block, false));
    }
  });
}

/** @param {Element} li */
function hasChildList(li) {
  return [...li.children].some((c) => c.tagName === "UL" || c.tagName === "OL");
}

/**
 * A bullet: a button when there's something to collapse, else a dot.
 * @param {Element} owner the item or heading it stands for
 * @param {boolean} collapsible
 */
function bullet(owner, collapsible) {
  if (!collapsible) {
    const dot = document.createElement("span");
    dot.className = "bullet";
    dot.setAttribute("aria-hidden", "true");
    return dot;
  }
  const button = document.createElement("button");
  button.type = "button";
  button.className = "bullet";
  button.setAttribute("aria-expanded", "true");
  button.setAttribute("aria-label", `Collapse ${label(owner)}`);
  return button;
}

/** An item's own text, without its sub-items. @param {Element} owner */
function label(owner) {
  const copy = /** @type {Element} */ (owner.cloneNode(true));
  copy.querySelectorAll("ul, ol, .bullet").forEach((n) => n.remove());
  const text = (copy.textContent ?? "").replace(/\s+/g, " ").trim();
  return text.length > 60 ? `${text.slice(0, 59)}…` : text;
}

/**
 * The click handler for a body's outline: a bullet button collapses or expands its block.
 * @param {Event} e
 */
export function toggleBlock(e) {
  const button = /** @type {Element} */ (e.target).closest?.("button.bullet");
  if (!button) return;
  const block = button.closest("li, .block");
  if (!block) return;
  const collapsed = block.classList.toggle("collapsed");
  const text = (button.getAttribute("aria-label") ?? "").replace(/^(Collapse|Expand) /, "");
  button.setAttribute("aria-expanded", String(!collapsed));
  button.setAttribute("aria-label", `${collapsed ? "Expand" : "Collapse"} ${text}`);
}
