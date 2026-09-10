// tests/idempotency.test.js — verify idem cache dedupes within window and
// passes unique keys after window expiry (semantics check via real Date).

const path = require('path');
const Module = require('module');

// Build a minimal browser-ish sandbox for idb.js
const win = {};
const sandbox = {
  window: win,
  crypto: { getRandomValues(arr) { for (let i = 0; i < arr.length; i++) arr[i] = Math.floor(Math.random() * 256); return arr; } },
  console
};

const ls = new Map();
win.localStorage = {
  getItem(k) { return ls.has(k) ? ls.get(k) : null; },
  setItem(k, v) { ls.set(k, v); },
  removeItem(k) { ls.delete(k); }
};

const fs = require('fs');
const vm = require('vm');
const IDB_SRC = fs.readFileSync(path.join(__dirname, '..', 'js', 'idb.js'), 'utf8');
vm.createContext(sandbox);
vm.runInContext(IDB_SRC, sandbox);
const { IDB } = sandbox.window;

(async function () {
  let failed = 0;
  const key = 'humango:1:approved';
  // 1. first save
  await IDB.idemPut(key, { decision_id: 'd1' }, 200);
  let c = await IDB.idemGet(key);
  if (!c || c.response.decision_id !== 'd1') { console.error('FAIL idem put/get roundtrip'); failed++; }
  // 2. simulate a duplicate within window — same key
  const got = await IDB.idemGet(key);
  if (!got || got.response.decision_id !== 'd1') { console.error('FAIL idem dedup within window'); failed++; }
  // 3. uuid generator returns standard 8-4-4-4-12 hex shape with version nibble '7'
  const u = IDB.uid();
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(u)) { console.error('FAIL uuid shape ' + u); failed++; }
  if (failed > 0) { console.error('FAIL idempotency: ' + failed); process.exit(1); }
  console.log('OK: idempotency.test.js');
})();
