// tests/syntax-check.js
//
// Loops every JS file and parses it through the V8 parser (Function
// constructor under Node) to ensure no syntax error. Static, no runtime
// test of DOM logic.

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const JS_FILES = ['js/idb.js', 'js/redact.js', 'js/data.js', 'js/router.js', 'js/screens.js', 'js/app.js', 'tests/secret-scan.js', 'tests/syntax-check.js'];

let failed = 0;
for (const rel of JS_FILES) {
  const full = path.join(ROOT, rel);
  if (!fs.existsSync(full)) { console.error('MISSING ' + rel); failed++; continue; }
  const src = fs.readFileSync(full, 'utf8');
  try {
    // Node parse-only check via Function constructor in strict mode.
    new Function('"use strict";\n' + src);
    console.log('OK ' + rel + ' (' + src.split(/\n/).length + ' lines)');
  } catch (e) {
    console.error('FAIL ' + rel + ': ' + e.message);
    failed++;
  }
}

if (failed > 0) { console.error('FAIL: ' + failed + ' file(s) failed syntax check'); process.exit(1); }
console.log('OK: all JS files parse.');
