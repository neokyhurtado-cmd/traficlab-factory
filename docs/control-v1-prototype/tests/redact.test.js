// tests/redact.test.js — node-side unit test for the redact patterns.
// The browser-side redact.js is structurally the same as the slice we test
// here (same regex set, same redactor semantics). Verified by injecting
// a stub window before requiring the script.

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const REDACT_SRC = fs.readFileSync(path.join(__dirname, '..', 'js', 'redact.js'), 'utf8');
const sandbox = { window: { localStorage: { getItem() { return null; }, setItem() {}, removeItem() {} } }, crypto: { getRandomValues(arr) { for (let i = 0; i < arr.length; i++) arr[i] = Math.floor(Math.random() * 256); return arr; } } };
vm.createContext(sandbox);
vm.runInContext(REDACT_SRC, sandbox);
const { Redact } = sandbox.window;

const cases = [
  { name: 'github_pat', input: 'Bearer ghp_abcdef0123456789abcdef0123456789abcd', mustNotInclude: 'ghp_abcdef0' },
  { name: 'telegram_env_key', input: 'Token TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyzABCD', mustNotInclude: '1234567890' },
  { name: 'bearer_token', input: 'Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123456789', mustNotInclude: 'abcdefghijklmnopqrstuvwxyz0' },
  { name: 'api_server_key_value', input: 'API_SERVER_KEY=abcdefghijklmnopqrstuvwxyz0123', mustNotInclude: 'abcdefghijklmnop' },
  { name: 'safe_text', input: 'safe text — no secrets here', mustBeUnchanged: true },
  { name: 'long_hex_blob', input: 'long hex 0000000000000000000000000000000000000000', mustNotInclude: '0000000000000000000000' },
  { name: 'long_base64_blob', input: 'compressed base64 ZGVhZGJlZWZkZWFkYmVlZmRlYWRiZWVmZGVhZGJlZWZkZWFk', mustNotInclude: 'ZGVhZGJlZWZkZWFkYmVlZmRlYWRiZWVmZGVhZGJlZWZkZWFk' }
];

let failed = 0;
for (const c of cases) {
  const out = Redact.redact(c.input);
  if (c.mustBeUnchanged) {
    if (out !== c.input) {
      console.error('FAIL redact changed safe text: [' + c.name + '] out=' + out);
      failed++;
    }
    continue;
  }
  if (c.mustNotInclude && out.indexOf(c.mustNotInclude) !== -1) {
    console.error('FAIL redact leaked [' + c.name + ']: input=' + c.input.slice(0, 32) + '… out=' + out);
    failed++;
  }
  // the redacted output should contain ***
  if (out.indexOf('***') === -1) {
    console.error('FAIL redact no-marker [' + c.name + ']: out=' + out);
    failed++;
  }
}
if (failed > 0) { console.error('FAIL: redact test failed ' + failed + ' case(s)'); process.exit(1); }
console.log('OK: redact.test.js (' + cases.length + ' cases)');
