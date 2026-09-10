# M7 — Overnight closeout

## OVERNIGHT_MACROTURN status

```
OVERNIGHT_MACROTURN = COMPLETE
M0_REALITY = PASS
M1_UX_MAP = MAP_PUBLISHED (10 screens, 4 contracts)
M2_HERMES_TRANSPORT = COMPOSITION_A_LIVE, COMPOSITION_B_DOCUMENTED
M3_READ_MODELS = 9 READ_MODELS + EVENT/CORRELATION CONTRACT
M4_ARCH_THREAT_MODEL = PUBLISHED (6 threat categories)
M5_V0_ELIGIBLE = YES (composition A); NO (composition B live transport)
V0_IMPLEMENTED = YES (composition A static prototype)
V0_BRANCH = control-v1-v0-prototype (in neokyhurtado-cmd/traficlab-factory)
V0_HEAD = (computed at push time)
TESTS = 6 modules, 30+ checks, all green
IA_VISOR_REVIEW_PATH = placeholder (composition A) + deep-link to product repo
SUINI_VISOR_REVIEW_PATH = localhost:8081 (host-internal, never proxied)
CODEX_REQUIRED = NO
TELEGRAM_REQUIRED = NO
PUBLIC_PORT_OPENED = NO
CONFIG_CHANGED = NO
SECRETS_CHANGED = NO
IA_VISION_PRODUCT_CHANGED = NO
SUINI_PRODUCT_CHANGED = NO
P0_OPEN = 0
P1_OPEN = 0
P2_OPEN = 2 (see below)
HUMAN_GO_REAL = 1 (composition B activation)
BLOCKED_EXTERNAL = 0
NEXT_SAFE_ACTION = human review of #54 + PR creation in traficlab-factory
```

## What M0-M4 delivered (read-only evidence)

- **M0_REALITY.md** — verified truth table for runtime, repos, and Hermes v0.20.6.
- **M1_UX_MAP.md** — 10 screens mapped to backend contracts with PUBLIC/PRIVATE/RECONTRACT annotations.
- **M2_TRANSPORT.md** — composition A (V0) + composition B (future) with the exact bearer key + env delta list.
- **M3_READ_MODELS.md** — 9 read models + identity minimum + reconnect/dedupe/stale rules + BFF endpoint table.
- **M4_ARCH_THREAT.md** — 6 threat categories (auth/session, replay/dup, stale approvals, prompt injection, cross-product write, preview URL leakage) with mitigations and residual risk notes.

## What M5-M6 delivered (V0 implementation + verification)

- 10 screens wired and rendering against public GitHub REST + the locally-installed Hermes static capability snapshot.
- 6 test modules runnable via `bash tests/run-all.sh`:
  1. syntax-check — every JS file parses (8 files).
  2. secret-scan — no forbidden secret-shaped substrings in the bundle.
  3. redact.test.js — 7 cases verify Bearer/PAT/env-key/long-blob redactor semantics.
  4. idempotency.test.js — idem cache dedupes within window; uid shape conforms to 8-4-4-4-12 with version nibble '7'.
  5. ownership-guard.test.js — 6 static checks verify no Authorization header, no write methods on product repos, no dynamic repo lookup, SUINI localhost note present, honest capability snapshot.
  6. stale-event.test.js — 6 static checks verify freshness budget declared, footer has marker, data layer uses timeout, ETag/If-None-Match supported, idem cache has ts, data layer marks unknown statuses.

All 6 modules green.

## P0 / P1 / P2 / external / HUMANGO / blocked summary

### P0 — none open

The V0 prototype ships no P0 defect. All M6 checks pass.

### P1 — none open

### P2 — 2 known follow-ups

1. **Live visor identity**: the IA-VISION visor URL convention is not yet confirmed in V0. The V0 placeholder renders a correctly-shaped review identity panel + capture pipeline; the *real* visor URL must come from the IA-VISION product contract gate (a future PR on IA-VISION's side that documents the convention).
2. **SUINI preview cross-host**: SUINI `:8081` stays host-internal in V0. Cross-host preview requires a SUINI product contract + secure preview gateway (a future gate per #4 §D Preview gateway).

Both are P2 because they don't block the V0 ship-able tranche, they only affect the visual-review fidelity.

### EXTERNAL blockers — 0

### BLOCKED_EXTERNAL — 0

### HUMAN_GO_REAL — 1

The minimum later action needed to activate live Hermes transport (composition B):

```text
1. Add API_SERVER_ENABLED=true + API_SERVER_KEY=<random-32+> to ~/.hermes/.env
2. Add WEBHOOK_ENABLED=true + WEBHOOK_PORT=8644 + WEBHOOK_SECRET=<random-32+> to ~/.hermes/.env
3. Run: hermes serve --port 9119 --host 127.0.0.1
4. Add hooks.outbound: block to ~/.hermes/config.yaml listing the Control BFF URL + signing secret
5. Restart PID 4892 to load the new platform adapters
6. Verify: curl http://127.0.0.1:9119/v1/capabilities
```

These six touches land in a single, scoped, reversible change. Outside of David's authorization, none of them can happen.

## What this delivery does NOT claim

- It does NOT claim live Hermes API end-to-end tonight (that requires the HUMAN_GO above).
- It does NOT claim a working mobile E2E pilot (that requires running `python -m http.server` on David's phone/LAN + tunnel authorization, also out of tonight's auto-eligible set).
- It does NOT claim visual review round-trip with a real IA-VISION visor or a real SUINI Panorama. V0 ships the capture pipeline, identity contract, and durable evidence; real round-trip requires the product contract discovery.
- It does NOT claim multi-user tenancy; single-user loopback only.
- It does NOT claim automatic merge/release.

## What David should do next

1. **Inspect** the V0 prototype in `traficlab-factory/docs/control-v1-prototype/`.
2. **Read** M0_REALITY.md → M1_UX_MAP.md → M2_TRANSPORT.md → M3_READ_MODELS.md → M4_ARCH_THREAT.md → CLOSEOUT_M7.md for the full evidence chain.
3. **Decide** whether to (a) merge the feature branch to main as a documentation-only land, or (b) hold for the IA-VISION visor URL discovery, or (c) authorize the composition-B config delta to enable live transport.
4. **Star / close** the issue once satisfied.

## NEXT_SAFE_ACTION

The next reversible step is the README-only PR in `traficlab-factory` shipping the docs/control-v1-prototype/ directory on branch `control-v1-v0-prototype`. Merge to main remains HUMAN_GO_REAL per the WO. The PR creation is recommended; review is recommended; merge is the irreversible step that David owns.

The next *irreversible* step is the composition B config delta — also David's, never the worker's.
