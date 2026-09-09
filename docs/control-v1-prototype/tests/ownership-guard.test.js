// tests/ownership-guard.test.js
//
// Verifies that the browser-side Data layer never carries an Authorization
// header nor any product-write surface. The test reads the production
// data.js source and confirms:

const fs = require('fs');
const path = require('path');

const DATA_SRC = fs.readFileSync(path.join(__dirname, '..', 'js', 'data.js'), 'utf8');

let failed = 0;
function check(name, cond) {
  if (cond) console.log('OK ' + name); else { console.error('FAIL ' + name); failed++; }
}

// 1. No Authorization header set anywhere in the data layer.
check('no_authorization_header_in_data',
  !/Authorization\s*[:=]/i.test(DATA_SRC));

// 2. credentials: 'omit' is set on every fetch call (no cookies, no
//    credentials — proves no Hermes key leaks to the browser).
const fetchMatches = DATA_SRC.match(/fetch\([^)]*\)/g) || [];
const allOmit = fetchMatches.every((s) => s.includes("credentials: 'omit'"));
check('all_fetches_credentials_omit', allOmit || fetchMatches.length === 0);

// 3. The data layer never calls PUT, POST, PATCH, or DELETE on the
//    product repos (cross-product write guard from M4 §T5).
const writeMethodRegex = /\bfetch\([^)]*method\s*:\s*['"`](PUT|POST|PATCH|DELETE)['"`]/i;
check('no_write_methods_on_product_repos', !writeMethodRegex.test(DATA_SRC));

// 4. The repository list is hardcoded — no dynamic user input feeds repo
//    slugs (prevents accidental cross-product writes via repo aliasing).
const hasDynamicRepo = /PRODUCT_REPOS\s*\[\s*[^]]+\s*\]/.test(DATA_SRC) ||
                       /repos\[[^\]]+\]/.test(DATA_SRC);
check('no_dynamic_repo_lookup', !hasDynamicRepo);

// 5. Cross-product control UI annotation in the SUINI runtime card —
//    localhost-only and the Control explicitly does not proxy.
const screensSrc = fs.readFileSync(path.join(__dirname, '..', 'js', 'screens.js'), 'utf8');
check('suini_localhost_and_no_proxy',
  /localhost:8081/.test(screensSrc) && /does not proxy/i.test(screensSrc));

// 6. The HERMES static snapshot marks webhooks / peers / api_server as
//    "available-not-enabled" — V0 never claims a live capability that
//    isn't actually enabled.
const HERMES = DATA_SRC.match(/HERMES\s*=\s*\{[\s\S]*?\n\s*\};\n/);
check('capabilities_honest_snapshot',
  HERMES && /api_server_enabled:\s*false/.test(HERMES[0]) && /webhook_enabled:\s*false/.test(HERMES[0]));

if (failed > 0) { console.error('FAIL ownership-guard ' + failed + ' check(s)'); process.exit(1); }
console.log('OK: ownership-guard.test.js (6 checks)');
