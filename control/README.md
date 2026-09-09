# TRAFFICLAB-CONTROL-V1 — V0 Skeleton

First-party mobile/desktop control surface for IA-VISION + SUINI.

**Status:** M5 V0 skeleton (isolated worktree, not merged to main).
**Branch:** `feat/trafficlab-control-v1-01-m5-v0`
**Source WO:** `neokyhurtado-cmd/suini#54`
**Macro goal:** `neokyhurtado-cmd/traficlab-factory#4`

See `suini#54` comments 5598951863..5599034906 for M0..M4 evidence.

## V0 Components

- `bff/` — Control BFF (FastAPI). Loopback only. Holds Hermes + GitHub credentials.
- `ui/` — Static SPA (vanilla HTML/CSS/JS). Mobile-first.
- `tests/` — Adversarial tests for threat model T1..T12.
- `docs/` — Schemas (control-read-model/v1.0.0, control-event/v1.0.0).

## V0 Eligibility (per M4)

All 6 criteria PASS — see suini#54 comment 5599034906.

## V0 Out of scope

- Public port / reverse proxy
- Webhook platform enable
- Multi-user / RBAC
- Push notifications to phone
- PWA install

These require HUMAN_GO_REAL.