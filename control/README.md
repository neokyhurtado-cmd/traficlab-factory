# TRAFFICLAB-CONTROL-V1 — Panel de David

First-party mobile/desktop control surface for IA-VISION + SUINI.

**Status:** V0.1 — Mission Control, Evidence Timeline and Human-Go Inbox on real sources.
**Source WO:** `neokyhurtado-cmd/suini#54`
**Macro goal:** `neokyhurtado-cmd/traficlab-factory#4`

V0 (the BFF + UI skeleton) merged to `main` via PR #6 → `c193d0c`. See `suini#54`
comments 5598951863..5599034906 for M0..M4 evidence, and the
`CONTROL_V0_RECONCILIATION` comment for how the branch history reconciles.

## Components

| Path | Purpose |
|---|---|
| `bff/main.py` | FastAPI BFF: auth, security headers, endpoints, SSE. Loopback only. |
| `bff/sources.py` | Read-only evidence readers (kanban `mode=ro`, git, `gh api`, TCP probes). |
| `bff/readmodels.py` | Mission Control / Evidence Timeline / Human-Go Inbox projections. |
| `ui/` | Static SPA (vanilla HTML/CSS/JS), mobile-first, no build step. |
| `tests/test_adversarial.py` | Adversarial suite — 223 assertions (T1..T12, F2.x, F3.x). |
| `tests/smoke_viewports.py` | Playwright mobile + desktop viewport smoke — 60 assertions. |

## Panel surfaces (V0.1)

| Endpoint | Read model | Source of truth |
|---|---|---|
| `GET /api/v1/mission` | `MissionControl` | kanban.db + git + `gh api` + test marker |
| `GET /api/v1/timeline` | `EvidenceTimeline` | kanban.db `task_events` |
| `GET /api/v1/human-go` | `HumanGoInbox` | blocked tasks + open PRs |
| `GET /api/v1/products` | `ProductCardList` | remote `main` SHA + live TCP probes |

All four are **GET-only and read-only** (asserted by F3.5). Sources are opened
read-only: SQLite via `file:...?mode=ro`, git and `gh` behind verb allow-lists
that reject `push`/`commit`/`merge`/`checkout` and every `gh` verb except `api`.

### The honesty contract

Every displayed field is a `Fact`: value + `source` + `state` + `captured_at`.
When a source is unreachable the state is `NOT_AVAILABLE_YET` with a
human-readable reason, and the UI renders that reason. Nothing is ever
back-filled with a plausible default, and an unproven target exposes **no
clickable link**. This is enforced by F3.6 and F3.8.

Product ownership is one-directional: this panel reads IA-VISION and SUINI
status; it never writes their code, DB, runtime or schema.

## Running

```bash
python -m uvicorn control.bff.main:app --host 127.0.0.1 --port 9118 --no-access-log

python control/tests/test_adversarial.py                         # 223 assertions
python control/tests/smoke_viewports.py http://127.0.0.1:9118/   # 60 assertions
```

The BFF deliberately cannot trigger a test run over HTTP — that would be a
remote-execution primitive. The suite writes `control/tests/last_run.json` and
Mission Control displays that marker with its timestamp, so a stale result
cannot masquerade as a fresh one.

### Environment overrides

| Variable | Default | Purpose |
|---|---|---|
| `BFF_HOST` / `BFF_PORT` | `127.0.0.1` / `9118` | Bind target; non-loopback host is refused at boot. |
| `CONTROL_DB` | `~/AppData/Local/hermes/control.db` | Findings + events store. |
| `CONTROL_KANBAN_DB` | traficlabpro board | Kanban board read (read-only). |
| `CONTROL_REPO_ROOT` | repo root | Which worktree Mission Control reports on. |

## Out of scope (HUMAN_GO_REAL)

- Merge to `main`, release/deploy
- Public port / reverse proxy / VPN exposure
- `config.yaml`, `.env`, provider/model, gateway or secret changes
- Persistent daemon enablement
- Any write to IA-VISION or SUINI product code, data, runtime or schema
- Multi-user / RBAC, push notifications, PWA install
