// @ts-check
// The browser's only interface to the server (SPEC §17). Every request carries
// `X-Memex: 1` (§12); any 401 means the session has ended, so go to /relaunch.

/**
 * @typedef {{hash: string, content: string}} FileVersion
 * @typedef {{
 *   code: string,
 *   message: string,
 *   current?: FileVersion,
 *   impact?: {referrers: string[]},
 *   field_errors?: {field: string, message: string}[],
 * }} ErrorBody
 */

export class ApiError extends Error {
  /**
   * @param {number} status
   * @param {ErrorBody} body
   */
  constructor(status, body) {
    super(body.message);
    this.status = status;
    this.code = body.code;
    this.body = body;
  }
}

// Browsers refuse keepalive bodies over 64 KiB; above this, leaving relies on "Leave site?".
const KEEPALIVE_LIMIT = 60_000;

/**
 * @param {string} method
 * @param {string} url
 * @param {{json?: unknown, ifMatch?: string, keepalive?: boolean}} [options]
 * @returns {Promise<any>}
 */
export async function request(method, url, options = {}) {
  /** @type {Record<string, string>} */
  const headers = { "X-Memex": "1" };
  if (options.json !== undefined) headers["Content-Type"] = "application/json";
  if (options.ifMatch) headers["If-Match"] = `"${options.ifMatch}"`;
  const body = options.json === undefined ? undefined : JSON.stringify(options.json);
  const response = await fetch(url, {
    method,
    headers,
    body,
    keepalive: (options.keepalive ?? false) && (body?.length ?? 0) < KEEPALIVE_LIMIT,
    cache: "no-store",
  });
  if (response.status === 401) relaunch();
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new ApiError(
      response.status,
      data.error ?? { code: "internal", message: `The server said ${response.status}` },
    );
  }
  return data;
}

export function relaunch() {
  window.location.assign("/relaunch");
}

/** @param {string} path */
export function fileUrl(path) {
  return `/api/files?path=${encodeURIComponent(path)}`;
}

/**
 * A message for a failed request, fit for a banner.
 * @param {unknown} error
 */
export function describe(error) {
  if (error instanceof ApiError) return error.message;
  return "Memex isn't answering: is it still running?";
}
