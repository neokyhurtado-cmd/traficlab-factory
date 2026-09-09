/* redact.js — log/data redaction (T4 / M4 mitigation #5)
 * Strict blacklist for any Bearer / token / PAT / API key shape that
 * accidentally leaks into a log line, an evidence field, or a UI snippet.
 * IMPORTANT: this is fail-closed. The browser is never expected to hold
 * secrets; if it ever does, we MUST scrub them from log streams.
 */
(function (root) {
  'use strict';

  const PATTERNS = [
    // GitHub PATs (ghp_, gho_, ghu_, ghs_, ghr_)
    /\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b/g,
    // Hermes/API keys with prefix and long suffix (heuristic)
    /\b(?:API_SERVER_KEY|MINIMAX_API_KEY|ANTHROPIC_TOKEN|KIMI_API_KEY|OPENROUTER_API_KEY|TELEGRAM_BOT_TOKEN|DISCORD_BOT_TOKEN|WHATSAPP|WEBHOOK_SECRET)[\s=:]+\S{4,}/gi,
    // Generic Bearer tokens
    /\bBearer\s+[A-Za-z0-9._\-]{12,}\b/gi,
    // Long hex/base64 blobs that smell like secrets (>= 32 chars unbroken)
    /\b[A-Fa-f0-9]{32,}\b/g,
    /\b[A-Za-z0-9+/]{32,}={0,2}\b/g,
  ];

  function redact(input) {
    if (input == null) return input;
    if (typeof input !== 'string') input = String(input);
    let out = input;
    for (const re of PATTERNS) {
      out = out.replace(re, (m) => {
        if (m.length <= 6) return '***';
        return m.slice(0, 3) + '***' + m.slice(-3);
      });
    }
    return out;
  }

  /** Walk a JSON-like object and redact string fields. */
  function walk(value) {
    if (value == null) return value;
    if (typeof value === 'string') return redact(value);
    if (Array.isArray(value)) return value.map(walk);
    if (typeof value === 'object') {
      const out = {};
      for (const k of Object.keys(value)) out[k] = walk(value[k]);
      return out;
    }
    return value;
  }

  function safeJSON(obj) {
    try { return JSON.stringify(walk(obj)); } catch (_) { return '***'; }
  }

  function safeLog(...args) {
    const cleaned = args.map((a) => (typeof a === 'object' ? safeJSON(a) : redact(String(a))));
    // eslint-disable-next-line no-console
    console.log('[tlfb]', ...cleaned);
  }

  root.Redact = { redact, walk, safeJSON, safeLog };
})(window);
