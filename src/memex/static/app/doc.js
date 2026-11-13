// @ts-check
// The open document and its auto-save (SPEC §5.7, §11.1 client state #2).
//
// States: clean → (typing) dirty → (1 s quiet, blur, navigation, tab close) saving → clean.
// A change on disk while clean reloads in place; while dirty it becomes a conflict and
// auto-save pauses. A file deleted or moved outside the app becomes `deleted`; the editor
// keeps its text. The server's hash check settles everything; nothing retries on its own.
//
// A change on disk that leaves our text's base alone (e.g. a field edit while the Entity
// page's body is open) just moves the hash on: there is nothing to reconcile.

import { signal } from "@preact/signals";
import { ApiError, describe, fileUrl, request } from "./api.js";

/**
 * @typedef {"clean" | "dirty" | "saving" | "conflict" | "deleted"} SaveState
 * @typedef {import("./api.js").FileVersion} FileVersion
 * @typedef {{kind: "equal" | "replace" | "delete" | "insert", disk: string | null, mine: string | null}} DiffRow
 */

export const SAVE_DELAY_MS = 1000;
const NOTICE_MS = 3000;

export class OpenDoc {
  /**
   * @param {string} path
   * @param {FileVersion} version
   */
  constructor(path, version) {
    this.path = path;
    /** The version of the file the editor's text is based on. */
    this.hash = version.hash;
    /** The text on disk at `hash`. */
    this.base = version.content;
    this.text = signal(version.content);
    this.state = signal(/** @type {SaveState} */ ("clean"));
    /** What is on disk now, while in conflict. */
    this.conflict = signal(/** @type {FileVersion | null} */ (null));
    /** A failed save that wasn't a conflict ("Couldn't save"); the edits stay. */
    this.problem = signal(/** @type {string | null} */ (null));
    /** A brief note, e.g. "Updated from disk". */
    this.notice = signal(/** @type {string | null} */ (null));
    /** Bumped whenever the text is replaced from disk, so the textarea resyncs. */
    this.revision = signal(0);
    this.timer = 0;
    this.noticeTimer = 0;
    this.recheckAfterSave = false;
    /** What `compare()` diffs against on the server: the whole file, or its body. */
    this.part = "file";
    /** The save in flight, if any, so leaving can wait for it. */
    this.inflight = /** @type {Promise<void> | null} */ (null);
  }

  /** @param {string} path */
  static async open(path) {
    const version = await request("GET", fileUrl(path));
    return new OpenDoc(path, version);
  }

  /**
   * Whether a route shows this document, so going there isn't leaving it.
   * @param {import("./router.js").Route} route
   */
  ownsRoute(route) {
    return route.name === "file" && route.path === this.path;
  }

  /** Whether the deleted banner can offer Recreate. */
  get canRecreate() {
    return true;
  }

  /** @returns {Promise<FileVersion>} */
  async fetchVersion() {
    return request("GET", fileUrl(this.path));
  }

  /**
   * @param {string} text
   * @param {boolean} keepalive
   * @returns {Promise<{hash: string}>}
   */
  async put(text, keepalive) {
    return request("PUT", "/api/files", {
      json: { path: this.path, content: text },
      ifMatch: this.hash,
      keepalive,
    });
  }

  /** True while leaving would lose something: unsaved, saving, or a banner showing. */
  get guarded() {
    return this.state.value !== "clean";
  }

  /** @param {string} text */
  edit(text) {
    this.text.value = text;
    const state = this.state.value;
    if (state === "clean" || state === "dirty") {
      this.state.value = "dirty";
      this.schedule();
    }
    // saving: save() sees the text moved on. conflict, deleted: auto-save is paused.
  }

  schedule() {
    clearTimeout(this.timer);
    this.timer = window.setTimeout(() => void this.save(), SAVE_DELAY_MS);
  }

  /** Save now if there are unsaved edits, and wait for any save in flight (leaving). */
  async flush(keepalive = false) {
    if (this.inflight) await this.inflight;
    if (this.state.value === "dirty") await this.save(keepalive);
  }

  async save(keepalive = false) {
    if (this.state.value !== "dirty") return;
    this.inflight = this.saveNow(keepalive);
    try {
      await this.inflight;
    } finally {
      this.inflight = null;
    }
  }

  /** @param {boolean} keepalive */
  async saveNow(keepalive) {
    clearTimeout(this.timer);
    const sent = this.text.value;
    this.state.value = "saving";
    try {
      const saved = await this.put(sent, keepalive);
      this.hash = saved.hash;
      this.base = sent;
      this.problem.value = null;
      this.state.value = this.text.value === sent ? "clean" : "dirty";
      if (this.state.value === "dirty") this.schedule();
    } catch (error) {
      this.failed(error);
    }
    if (this.recheckAfterSave) {
      this.recheckAfterSave = false;
      await this.recheck();
    }
  }

  /** @param {unknown} error */
  failed(error) {
    const current = error instanceof ApiError && error.code === "conflict" ? error.body.current : null;
    if (current && current.content === this.base) {
      // Only something we don't edit changed: save again on top of it.
      this.hash = current.hash;
      this.state.value = "dirty";
      this.schedule();
    } else if (current) {
      this.enterConflict(current);
    } else if (error instanceof ApiError && error.code === "not_found") {
      this.state.value = "deleted";
    } else {
      this.state.value = "dirty";
      this.problem.value = `Couldn't save: ${describe(error)}`;
    }
  }

  /** @param {FileVersion} current */
  enterConflict(current) {
    clearTimeout(this.timer);
    this.conflict.value = current;
    this.state.value = "conflict";
  }

  /**
   * A `changed` event for this path. The hash we hold is our own save's echo.
   * @param {string | null} hash
   */
  onRemoteChange(hash) {
    if (hash !== null && hash === this.hash) return;
    void this.recheck();
  }

  /** Is the file on disk still the version we hold? (events, regained focus, reconnect) */
  async recheck() {
    if (this.state.value === "saving") {
      this.recheckAfterSave = true;
      return;
    }
    /** @type {FileVersion} */
    let disk;
    try {
      disk = await this.fetchVersion();
    } catch (error) {
      if (error instanceof ApiError && error.code === "not_found") {
        clearTimeout(this.timer);
        this.state.value = "deleted";
      }
      return;
    }
    // Read after the await: typing or a save may have moved it on since the check above.
    const state = /** @type {SaveState} */ (this.state.value);
    if (state === "saving") {
      this.recheckAfterSave = true;
    } else if (disk.hash !== this.hash && disk.content === this.base && state !== "conflict") {
      this.hash = disk.hash; // our text's base is unchanged
      if (state === "deleted") this.state.value = this.text.value === disk.content ? "clean" : "dirty";
      if (this.state.value === "dirty") this.schedule();
    } else if (disk.hash === this.hash) {
      // Back as it was. Without edits since, nothing is lost; otherwise let the user choose.
      if (state === "deleted" && this.text.value === disk.content) this.state.value = "clean";
      else if (state === "deleted") this.enterConflict(disk);
    } else if (state === "clean") {
      this.replaceText(disk);
      this.say("Updated from disk");
    } else if (state === "dirty" || state === "deleted") {
      this.enterConflict(disk);
    } else if (state === "conflict") {
      this.conflict.value = disk;
    }
  }

  /** Conflict banner: Reload, discarding my edits. */
  reload() {
    const current = this.conflict.value;
    if (!current) return;
    this.conflict.value = null;
    this.replaceText(current);
  }

  /** Conflict banner: Keep mine, overwriting what is on disk now. */
  async keepMine() {
    const current = this.conflict.value;
    if (!current) return;
    this.hash = current.hash;
    this.conflict.value = null;
    this.state.value = "dirty";
    await this.save();
  }

  /**
   * Conflict banner: Compare, a side-by-side line diff computed on the server.
   * @returns {Promise<DiffRow[]>}
   */
  async compare() {
    const diff = await request("POST", "/api/diff", {
      json: { path: this.path, content: this.text.value, part: this.part },
    });
    return diff.rows;
  }

  /** Deleted banner: Recreate, saving the editor's text at the original path. */
  async recreate() {
    const sent = this.text.value;
    try {
      const created = await request("POST", "/api/files", {
        json: { path: this.path, content: sent },
      });
      this.hash = created.hash;
      this.base = sent;
      this.problem.value = null;
      this.state.value = this.text.value === sent ? "clean" : "dirty";
      if (this.state.value === "dirty") this.schedule();
    } catch (error) {
      if (error instanceof ApiError && error.code === "exists") {
        this.state.value = "dirty";
        await this.recheck(); // someone else put a file there: compare against it
      } else {
        this.problem.value = `Couldn't recreate: ${describe(error)}`;
      }
    }
  }

  /** @param {FileVersion} version */
  replaceText(version) {
    clearTimeout(this.timer);
    this.hash = version.hash;
    this.base = version.content;
    this.text.value = version.content;
    this.state.value = "clean";
    this.revision.value += 1;
  }

  /** @param {string} message */
  say(message) {
    clearTimeout(this.noticeTimer);
    this.notice.value = message;
    this.noticeTimer = window.setTimeout(() => (this.notice.value = null), NOTICE_MS);
  }

  dispose() {
    clearTimeout(this.timer);
    clearTimeout(this.noticeTimer);
  }
}

/** An Entity page's body (SPEC §11.5): saved with a body replace, frontmatter untouched. */
export class BodyDoc extends OpenDoc {
  /**
   * @param {string} id
   * @param {string} path
   * @param {FileVersion} version
   */
  constructor(id, path, version) {
    super(path, version);
    this.id = id;
    this.part = "body";
  }

  /** @param {string} id */
  static async open(id) {
    const entity = await request("GET", `/api/entities/${encodeURIComponent(id)}`);
    return new BodyDoc(id, entity.path, { hash: entity.hash, content: entity.body });
  }

  /** @param {import("./router.js").Route} route */
  ownsRoute(route) {
    return route.name === "entity" && route.id === this.id;
  }

  get canRecreate() {
    return false;
  }

  async fetchVersion() {
    const entity = await request("GET", `/api/entities/${encodeURIComponent(this.id)}`);
    return { hash: entity.hash, content: entity.body };
  }

  /**
   * @param {string} text
   * @param {boolean} keepalive
   */
  async put(text, keepalive) {
    return request("PUT", `/api/entities/${encodeURIComponent(this.id)}/body`, {
      json: { body: text },
      ifMatch: this.hash,
      keepalive,
    });
  }
}
