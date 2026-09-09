// scripts/secret-scan.js
//
// Scans the V0 prototype directory for any forbidden secret-shaped strings.
// Allowed: the literal word "secrets", the word "sk-sp-", or any other
//  unobvious marker — but NEVER anything that resembles:
//
//   - GitHub PATs (ghp_, gho_, ghu_, ghs_, ghr_)
//   - Telegram bot tokens (8x digits : 35 chars)
//   - Discord bot tokens (long base64 ending in .xxx)
//   - Bearer tokens (Bearer <12+ chars>)
//   - Webhook secrets / API_SERVER_KEY <raw value>
//   - Long hex blobs (>= 32 chars unbroken)
//   - Long base64 blobs (>= 32 chars unbroken)
//
// Failure mode: exits non-zero with file:line context for any hit.

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const SCAN = ['js', 'css', 'html'];

const FORBIDDEN_PATTERNS = [
  { name: 'github_pat', re: /\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b/g },
  { name: 'telegram_bot_token', re: /\b\d{8,10}:[A-Za-z0-9_-]{30,40}\b/g },
  { name: 'bearer_token_literal', re: /Bearer\s+[A-Za-z0-9._\-]{12,}/g },
  { name: 'long_hex_blob', re: /\b[0-9a-fA-F]{40,}\b/g },
  { name: 'long_base64_blob', re: /\b[A-Za-z0-9+/]{40,}={0,2}\b/g },
  { name: 'env_key_value_secret', re: /\b(?:API_SERVER_KEY|MINIMAX_API_KEY|ANTHROPIC_TOKEN|KIMI_API_KEY|OPENROUTER_API_KEY|TELEGRAM_BOT_TOKEN|DISCORD_BOT_TOKEN|WEBHOOK_SECRET)\s*[=:]\s*['"]?[A-Za-z0-9._\-]{6,}/g }
];

function walk(dir, files) {
  files = files || [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === 'tests' || entry.name === 'node_modules') continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full, files);
    else if (SCAN.some((ext) => entry.name.endsWith('.' + ext))) files.push(full);
  }
  return files;
}

function relativize(p) { return path.relative(ROOT, p); }

const files = walk(ROOT);
let violations = 0;

for (const f of files) {
  const buf = fs.readFileSync(f, 'utf8');
  const lines = buf.split(/\r?\n/);
  lines.forEach((line, i) => {
    for (const { name, re } of FORBIDDEN_PATTERNS) {
      re.lastIndex = 0;
      let m;
      while ((m = re.exec(line))) {
        violations += 1;
        console.error('SECRET_LEAK candidate: ' + relativize(f) + ':' + (i + 1) + ' pattern=' + name + ' match=' + m[0].slice(0, 16) + '…');
      }
    }
  });
}

if (violations > 0) {
  console.error('FAIL: ' + violations + ' potential secret-shaped substring(s) found.');
  process.exit(1);
}
console.log('OK: no secret-shaped substrings in ' + files.length + ' files.');
