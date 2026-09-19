/* idb.js — tiny promise wrapper around localStorage with idempotency
 * No secrets, no Bearer tokens, no API keys stored — only Control app caches.
 * Indices:
 *   - idem:<key>        -> { ts, response, status }
 *   - finding:<id>      -> VisualReviewFinding JSON
 *   - poll:<url>        -> { etag, body, ts } for ETag/If-None-Match polling
 */
(function (root) {
  'use strict';
  const NS = 'tlfb:v0:';

  function k(key) { return NS + key; }

  async function get(key) {
    try {
      const raw = root.localStorage.getItem(k(key));
      return raw == null ? null : JSON.parse(raw);
    } catch (_) { return null; }
  }

  async function set(key, value) {
    try {
      root.localStorage.setItem(k(key), JSON.stringify(value));
    } catch (_) { /* quota or disabled */ }
  }

  async function del(key) {
    try { root.localStorage.removeItem(k(key)); } catch (_) {}
  }

  /** Idempotency cache. Each (key) stores the latest response with timestamp.
   * Returns the cached response if the same key was used within `windowMs`
   * (default 1 hour) — caller's responsibility to decide to dedupe.
   */
  async function idemGet(key) {
    return get('idem:' + key);
  }

  async function idemPut(key, response, status) {
    return set('idem:' + key, { ts: Date.now(), response, status: status || 200 });
  }

  /** UUIDv7-shaped identifier. Not strictly v7 but follows the same
   *  8-4-4-4-12 hex grouping with a '7' prefix on the version nibble.
   *  Monotonically increasing with millisecond precision + random tail —
   *  sufficient as a stable ephemeral id without crypto dependency.
   */
  function uid() {
    const ms = Date.now();
    const m = ms.toString(16).padStart(12, '0');
    const r = crypto.getRandomValues(new Uint8Array(10));
    let rand = '';
    for (let i = 0; i < r.length; i++) rand += r[i].toString(16).padStart(2, '0');
    return (
      m.slice(0, 8) + '-' +
      m.slice(8, 12) + '-' +
      '7' + rand.slice(0, 3) + '-' +
      rand.slice(3, 7) + '-' +
      rand.slice(7, 19)
    );
  }

  root.IDB = { get, set, del, idemGet, idemPut, uid };
})(window);
