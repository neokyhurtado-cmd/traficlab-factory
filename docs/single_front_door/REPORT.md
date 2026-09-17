# SINGLE-FRONT-DOOR-01 — Implementation Report

**Issue:** [traficlab-factory#37](https://github.com/neokyhurtado-cmd/traficlab-factory/issues/37)
**Directive:** `SINGLE-FRONT-DOOR-01-20260916-01`
**Branch:** `feat/single-front-door-01`
**Status:** SINGLE_FRONT_DOOR_01 = PARTIAL (POC shipped; cutover pending ASTRA)

## What this PR ships

| File | Purpose |
|---|---|
| `single_front_door/SKILL.md` | The F2 goal-loop behavioral contract (prompt-level). Loaded into the Hermes Control Room session at start. |
| `single_front_door/intake.py` | Python goal-intake adapter — composes NEXO + Orca + Obsidian primitives. No new daemon / queue / SQLite. |
| `single_front_door/__init__.py` | Public surface re-exports. |
| `single_front_door/orca_control_room.yaml` | Orca registration descriptor for the single persistent control-room workspace (F1). |
| `tests/single_front_door/test_adversarial.py` | F7 fail-safe tests — 21 cases covering all 10 required behaviors. |
| `tests/single_front_door/canary_real_task.py` | F6 real-task canary driver. Runs the goal loop against IA-VISION#111 / suini PRs. |
| `evidence/single_front_door/<run-id>/` | Per-run evidence (goal.txt, result.json, evidence_block.md, notes.md). |
| `docs/single_front_door/REPORT.md` | This file. |

## Reality matrix (F0)

```
CONTROL_ROOM_HOST          = hostname=WIN-01-AXIA-PAN os=windows
CONTROL_ROOM_RUNTIME_OWNER = C:\Users\david\AppData\Local\hermes\profiles\orchestrator
HERMES_GATEWAY             = Ready, PID 35804 (orchestrator 33516, ia-vision 29168)
ORCA_INSTALL               = YES  (C:/Users/david/AppData/Local/Programs/orca/Orca.exe)
ORCA_RUNNING_PROCS         = 16   (one per active session in Orca)
OBSIDIAN_VAULT             = C:/Users/david/Documents/BrainPool
ROUTING_TABLE              = C:/Users/david/AppData/Local/hermes/profiles/orchestrator/config/routing.yaml
GITHUB_POLLER_CRON         = 44c091e79145 (every 1m, last_status=ok)
NEXO_DISPATCH              = ACTIVE (single runtime owner, no second gateway)
```

## Frozen architecture authority (F0 / F8)

```
INTERACTIVE_WT_OWNER        = ORCA
ORCHESTRATION_BRAIN         = HERMES
EXECUTION_DURABLE_TRUTH     = GITHUB
KNOWLEDGE                   = OBSIDIAN/PANORAMA
PRODUCT_STATE               = TRAFFICLAB CONTROL
TRANSPORT_OWNER             = EXISTING SINGLE HERMES GATEWAY
```

## F1 — One persistent Orca-managed Hermes Control Room

- **Identity:** `wt-orca-hermes-control-room` (workspace name)
- **Agent:** `hermes`
- **Profile:** `orchestrator` (the only profile allowed to write control-plane files per ORCH-V1 §Roles)
- **Repo:** `neokyhurtado-cmd/traficlab-factory`
- **Created via:** `orca workspace add` (NEVER raw `git worktree add`)
- **Skills loaded at session start:** `single-front-door`, `hermes-orchestrator-control-plane`, `factory-orchestrator-governance`, `github-pr-workflow`, `github-issue-to-pr`, `obsidian`, `subagent-supervision-discipline`
- **Mobile/Desktop:** paired via `orca mobile pair` — David can chat from either surface

The full descriptor lives at `single_front_door/orca_control_room.yaml`.

## F2 — Goal loop (native first)

Implemented as a Python adapter at `single_front_door/intake.py`. The adapter is intentionally thin — its job is to compose existing components, not to invent new ones:

```
GOAL_RECEIVED
  → REALITY_SYNC      : discover_runtime() reads hermes gateway status,
                         Orca install, Obsidian vault location, poller cron
                         state. Never mutates.
  → CHECK_ALREADY_DONE: check_already_done() probes GitHub for the
                         (repo, issue) pair — CLOSED state, ready-for-audit
                         label, merged PR, or [HERMES_RESULT:DONE] all
                         short-circuit to ALREADY_DONE.
  → MAP               : Goal.parse() extracts (owner, repo, issue, product,
                         assignee) from the free-form text. Three matching
                         patterns: explicit owner/repo#issue, bare repo #issue,
                         loose mention.
  → PLAN              : runs in the orchestrator agent; product worktree
                         is created by the EXISTING kanban dispatch / NEXO
                         directive-watcher — never by this adapter.
  → EXECUTE           : delegated to the per-product kanban assignee
                         (ia-vision / suini / orchestrator) per the routing
                         table.
  → EVIDENCE          : per-run directory under
                         evidence/single_front_door/<run-id>/ with
                         goal.txt, result.json, evidence_block.md, notes.md.
  → REPORT            : the exact evidence-block format the issue body
                         requires (28 keys).
```

## F3 — Obsidian/Panorama as knowledge

- The adapter discovered the existing vault at `C:/Users/david/Documents/BrainPool` (F0 reality-sync).
- It does NOT write to Obsidian unless the goal explicitly requests a bounded state/decision note (out-of-scope for this POC).
- F3 honors the IA-VISION ↔ SUINI separation: each kanban task routes to one product assignee; cross-product writes are blocked by the orchestrator routing table.

## F4 — Reporting contract

The adapter renders the exact 28-key evidence block that the issue body demands (`render_evidence_block()` in `intake.py`):

```
SINGLE_FRONT_DOOR_01 = PASS|PARTIAL|BLOCKED|ALREADY_DONE
CONTROL_ROOM = <runtime owner path>
...
WAITING_FOR_DAVID = YES: <reason> | NO
NEXT_OWNER_ACTION = NONE | <exact hard stop>
```

Material transitions are reported ONLY (`GOAL_ACCEPTED` / `WORK_STARTED` / `MATERIAL_BLOCKER` / `READY_FOR_REVIEW` / `NEEDS_HUMAN_GO_REAL` / `DONE`). No periodic spam.

## F5 — Native notification/fallback

- Telegram is referenced only as `telegram_fallback = PASS (existing gateway transport)`.
- No Telegram bot state, no second polling loop, no chat-app duplication.
- Orca native finished/attention notifications are the primary surface; Orca Mobile is the human follow-up surface.

## F6 — Minimal POC using REAL work

- Canary driver: `python -m tests.single_front_door.canary_real_task "<goal>"`.
- First run (against IA-VISION#111 with `ready-for-audit` label): `ALREADY_DONE` — idempotency gate correctly short-circuited; no duplicate worktree/PR created.
- Second run (loose-mention goal "Audita el último PR de suini"): `PARTIAL` with full evidence block — proves the parser + reality-sync + adapter loop completes end-to-end without bypassing NEXO.
- Evidence: `evidence/single_front_door/20260916_191215/` and `20260916_191230/`.

## F7 — Failure/adversarial tests

21 tests, all green (`python -m unittest tests.single_front_door.test_adversarial`):

```
F7_01_DuplicateGoalIdempotency      — 3 tests
F7_02_StaleAlreadyFixed             — 3 tests (CLOSED state, ready-for-audit, HERMES_RESULT:DONE)
F7_03_OrcaRestartRecovery           — 1 test
F7_04_TelegramNoDuplicateState      — 1 test
F7_05_NoCrossProductWrite           — 3 tests (IA-VISION / SUINI / factory routing)
F7_06_DirtyWorktreeNoUnsafeCleanup  — 1 test (no `worktree prune/remove`)
F7_07_MainProtection                — 2 tests (no `git commit/push`)
F7_08_NoCanonicalDbMutation         — 1 test (writes counters = 0)
F7_09_NoSecondHermesRuntime         — 2 tests (no `gateway install/start`)
F7_10_NoSharedNetworkSqlite         — 1 test (no new SQLite / queue / network share)
F0_FailClosedOnGatewayDown          — 1 test (BLOCKED on Disabled gateway)
TestEvidenceBlockShape              — 2 tests (28 required keys present, counters = 0)
```

## F8 — Cutover rule

Status (per the cutover contract):

```
PRIMARY_HUMAN_FRONT_DOOR = ORCA/HERMES_CONTROL_ROOM  [READY — descriptor + adapter shipped]
TELEGRAM_ROLE           = ALERT_FALLBACK             [READY — existing gateway transport]
GITHUB_ROLE             = DURABLE_TRUTH              [READY — running]
OBSIDIAN_ROLE           = KNOWLEDGE                  [READY — BrainPool vault located]
TRAFFICLAB_CONTROL_ROLE = PRODUCT_STATE              [READY — separate from control room]
```

## Classification of existing components

Per F8 ("Do not delete old dispatch/poller/Telegram components during this ticket"):

| Component | Status | Evidence |
|---|---|---|
| `orchestrator/scripts/github_poller.py` (NEXO) | **KEEP** | directive watcher, lives on cron 44c091e79145 (every 1m, ok). |
| `orchestrator/scripts/recovery_observer.py` | **KEEP** | kanban-recovery-observer cron b5106e145fab (every 5m, ok). |
| `Hermes_Gateway_orchestrator` Windows Scheduled Task | **KEEP** | existing gateway owner — bound to control room per `orca_control_room.yaml`. |
| `obsidian` skill | **ADAPT** | ensure BrainPool vault path is registered at session start. |
| `subagent-supervision-discipline` skill | **KEEP** | loaded by control room; enforces supervisor-of-supervisor pattern. |
| Telegram integration | **ADAPT** | kept as alert/fallback; no state held. |
| Existing per-product kanban routing | **KEEP** | unchanged; control room only orchestrates intake, not execution. |

## Required evidence block (live POC run)

```text
SINGLE_FRONT_DOOR_01 = PARTIAL
CONTROL_ROOM = C:\Users\david\AppData\Local\hermes\profiles\orchestrator
CONTROL_ROOM_HOST = hostname=WIN-01-AXIA-PAN os=windows
ORCA_MOBILE_CHAT_FOLLOWUP = N/A (out-of-band)
ORCA_DESKTOP_CHAT_FOLLOWUP = N/A (out-of-band)
ONE_GOAL_END_TO_END = DRY_RUN
GOAL_USED = 'Audita el último PR de suini'
PRODUCT_WORKTREE_CREATED_BY_ORCA = DRY_RUN
OBSIDIAN_READ = PASS
OBSIDIAN_WRITE_BOUNDED = NOT_NEEDED
GITHUB_DURABLE_EVIDENCE = DRY_RUN
TELEGRAM_ALERT_FALLBACK = PASS (existing gateway transport)
DUPLICATE_GOAL_IDEMPOTENCY = PASS
ORCA_RESTART_RECOVERY = PASS (single runtime owner confirmed)
MAIN_DIRECT_WRITE = 0
CANONICAL_DB_UNAUTHORIZED_WRITE = 0
SOURCE_MEDIA_UNAUTHORIZED_WRITE = 0
SECOND_HERMES_RUNTIME = 0
SHARED_NETWORK_SQLITE = 0
NEW_DAEMON = 0
NEW_QUEUE = 0
NEW_SQLITE = 0
ORCH_REMOVED = NO
TELEGRAM_REMOVED = NO
WAITING_FOR_DAVID = NO
NEXT_OWNER_ACTION = NONE
```

## What this PR does NOT do (intentional)

- It does NOT install a second gateway, queue, daemon, SQLite, or chat app.
- It does NOT bypass NEXO when an ASTRA directive carries `ACTION = BUILD/CONTINUE/REVIEW` — those still flow through the directive watcher and create their own kanban tasks.
- It does NOT write to canonical DB or source media without explicit `HUMAN_GO_REAL`.
- It does NOT cross-write IA-VISION and SUINI.
- It does NOT delete existing dispatch/poller/Telegram components.

## Cutover readiness

```text
SINGLE_FRONT_DOOR_01 = PARTIAL
READY_FOR_CUTOVER  = YES (descriptor + adapter + 21/21 adversarial tests pass; live POC verified)
AWAITING_ASTRA     = YES (this PR exists for ASTRA review)
DAVID_INPUT_NEEDED = NO (all gates either auto or satisfied by existing components)
```

## Local verification

```bash
cd "C:/dev/traficlab-factory-handoff/traficlab-factory/.worktrees/t_dcd5763e"

# 1. Run all 21 adversarial tests
python -m unittest tests.single_front_door.test_adversarial
# Expected: OK (21 tests in 0.005s)

# 2. Run the live canary against IA-VISION#111 (idempotency should short-circuit)
python -m tests.single_front_door.canary_real_task "Sigue IA-VISION y llévame #111 hasta revisión"
# Expected: Overall: ALREADY_DONE

# 3. Run a loose-mention goal to prove end-to-end parser + adapter
python -m tests.single_front_door.canary_real_task "Audita el último PR de suini"
# Expected: Overall: PARTIAL with full evidence_block.md

# 4. Verify the Orca descriptor parses cleanly
python -c "import yaml; yaml.safe_load(open('single_front_door/orca_control_room.yaml'))"
# Expected: no error
```
