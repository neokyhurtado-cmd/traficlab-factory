# TrafficLab Control V0 — static prototype (composition A)

This directory contains the V0 prototype of the **TRAFFICLAB-CONTROL-V1** first-party
mobile/desktop control surface. Composition A is the **read-only transport** that is
shippable WITHOUT any privileged Hermes configuration change.

## What this prototype does (V0)

- Mobile-first responsive PWA-installable HTML/JS/CSS.
- All 10 required screens from `traficlab-factory#4`:
  1. Home / Command
  2. Mission Control
  3. IA-VISION Project
  4. SUINI Project
  5. Visual Review Hub (IA-VISION + SUINI modes)
  6. Goal / Run Detail
  7. PR / Review Lab
  8. Evidence Timeline
  9. Human-Go Inbox
  10. System Health
- Reads only public GitHub REST + the locally-installed Hermes static
  capability snapshot. **No Authorization header is ever sent by the browser.**
- Persists VisualReviewFinding + HUMAN-GO decisions in localStorage as
  durable evidence with idempotency-key dedupe.
- Honest `NOT_AVAILABLE_YET` / `PARTIAL` / `AVAILABLE_NOW` annotations on
  capabilities that depend on Hermes daemons not yet enabled.

## What this prototype does NOT do (yet)

- It does NOT talk to a live Hermes API server (`hermes serve` is not
  enabled on this host). Composition B adapters are written but feature-flagged
  off.
- It does NOT proxy IA-VISION visor streams or SUINI `:8081`. The Control
  product never becomes a second simulation owner; SUINI remains canonical.
- It does NOT post HUMAN-GO actions or VisualReviewFinding captures to
  HERMES-ORCH. Local durable records only; promotion requires composition B
  + David's authorization.

## File layout

```
control-v1-prototype/
├── index.html              # SPA shell
├── css/
│   ├── app.css             # design system: scientific + cinematic + operational
│   └── mobile.css          # mobile-only overrides
├── assets/
│   └── favicon.svg
└── js/
    ├── idb.js              # localStorage wrapper + idempotency-key cache
    ├── redact.js           # log/UI redaction; never leak Bearer / PAT shapes
    ├── data.js             # GitHub REST adapter + Hermes static snapshot
    ├── router.js           # hash-based screen router
    ├── screens.js          # 10 screens
    └── app.js              # bootstrap, status, toast, freshness loop
```

## Security properties

- No `Authorization` header ever set. `credentials: 'omit'` on every fetch.
- Loopback or local static serve only.
- Idempotency-key dedupe for HUMAN-GO actions (1-hour window).
- Bearer / PAT / API-key regex redactor on all console output and JSON.
- Strict CSP-friendly: no inline scripts/styles.
- Cross-product write guard: the browser cannot mutate product repo state.
- `authority-hierarchy.md` enforced: TrafficLab Control observes; it does
  not simulate.

## How to run locally

```bash
# any static server on loopback, e.g.:
python -m http.server 8080
# or
npx serve .
# then open http://localhost:8080/docs/control-v1-prototype/
```

## How the V0 prototype fits the WO eligibility matrix

```
ONE_OFFICIAL_HERMES_CONVERSATION_CONTRACT = PROVEN   (v0.20.6 docs at $LOCALAPPDATA/...)
ONE_PROGRESS_OR_EVENT_CONTRACT           = PROVEN   (v0.20.6 docs + static snapshot)
CONTROL_CODE_HOME                        = PROVEN   (traficlab-factory; branch control-v1-v0-prototype)
NO_CONFIG_OR_SECRET_CHANGE_REQUIRED      = YES      (composition A only; static server)
NO_PUBLIC_EXPOSURE_REQUIRED              = YES      (loopback / local serve only)
NO_HERMES_CORE_FORK_REQUIRED             = YES      (no edits to $LOCALAPPDATA/hermes/...)
NO_PRODUCT_REPO_MUTATION_REQUIRED        = YES      (composition A reads public REST only)
```

All seven gates are YES for V0 prototype. The only gates not currently YES for
live end-to-end Hermes transport are `NO_CONFIG_OR_SECRET_CHANGE_REQUIRED` and
`NO_PUBLIC_EXPOSURE_REQUIRED`; both unlock only when David explicitly approves
the bounded configuration delta documented in `M4_ARCH_THREAT.md` and the
Health screen's "Human authorization log" section.

## Future gates (composition B)

These are document-only at this revision; they activate only after David
authorizes the configuration delta:

- Hermes API server (port 9119 loopback JSON-RPC/WebSocket).
- Hermes webhooks (port 8644 inbound webhook).
- Hermes outbound hooks (sign posts to the Control BFF).
- Hermes MCP server adapter (stdio).
- Hermes peer adapter (cross-machine).
- Multi-user auth provider for tunneled deployments.
