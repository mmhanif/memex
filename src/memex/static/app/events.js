// @ts-check
// The `changed` event stream (SPEC §5.6). Read with fetch and a stream parser, not
// EventSource, because EventSource can't send the `X-Memex` header. Reconnects with backoff.

import { relaunch } from "./api.js";

/**
 * @typedef {{path: string, hash: string | null}} Change
 * @typedef {{onChanged: (changes: Change[]) => void, onReconnect: () => void}} Handlers
 */

const FIRST_DELAY_MS = 500;
const MAX_DELAY_MS = 10_000;

/** @param {Handlers} handlers */
export function connectEvents(handlers) {
  let delay = FIRST_DELAY_MS;
  let connectedBefore = false;

  /** @param {string} frame */
  function dispatch(frame) {
    let event = "message";
    let data = "";
    for (const line of frame.split("\n")) {
      if (line.startsWith("event: ")) event = line.slice(7);
      else if (line.startsWith("data: ")) data += line.slice(6);
    }
    if (event === "ready") {
      delay = FIRST_DELAY_MS;
      if (connectedBefore) handlers.onReconnect();
      connectedBefore = true;
    } else if (event === "changed") {
      handlers.onChanged(JSON.parse(data).changes);
    }
  }

  async function readOnce() {
    const response = await fetch("/api/events", {
      headers: { "X-Memex": "1" },
      cache: "no-store",
    });
    if (response.status === 401) {
      relaunch();
      return;
    }
    if (!response.ok || !response.body) return;
    const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) return;
      buffer += value;
      let end;
      while ((end = buffer.indexOf("\n\n")) >= 0) {
        dispatch(buffer.slice(0, end));
        buffer = buffer.slice(end + 2);
      }
    }
  }

  async function loop() {
    for (;;) {
      try {
        await readOnce();
      } catch {
        // dropped: fall through to the backoff
      }
      await new Promise((resolve) => setTimeout(resolve, delay));
      delay = Math.min(delay * 2, MAX_DELAY_MS);
    }
  }

  void loop();
}
