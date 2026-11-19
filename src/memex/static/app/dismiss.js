// @ts-check
// Popovers (menus, pickers, an outline cell's editor) close the way a menu would: on a
// click anywhere outside them, or on Escape. One hook so they all agree.

import { useLayoutEffect, useRef } from "preact/hooks";

/**
 * While `open`, call `close` on a mousedown outside `ref`'s element or on Escape anywhere.
 * `close` may change between renders; the latest one is called.
 * @param {{current: Element | null}} ref
 * @param {boolean} open
 * @param {() => void} close
 */
export function useDismiss(ref, open, close) {
  const latest = useRef(close);
  latest.current = close;
  // Layout effect: listening from the moment the popover is drawn, not a frame later.
  useLayoutEffect(() => {
    if (!open) return;
    /** @param {MouseEvent} e */
    const away = (e) => {
      if (!ref.current?.contains(/** @type {Node} */ (e.target))) latest.current();
    };
    /** @param {KeyboardEvent} e */
    const escape = (e) => {
      if (e.key === "Escape") latest.current();
    };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);
}
