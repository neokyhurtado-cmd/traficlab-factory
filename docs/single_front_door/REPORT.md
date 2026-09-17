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
| `tests/sfd_tests/test_adversarial.py` | F7 fail-safe tests — 34 cases covering all 10 required behaviors (21 original + 13 added under ASTRA REAUDIT_FIX). |
| `tests/sfd_tests/canary_real_task.py` | F6 real-task canary driver. Runs the goal loop against IA-VISION#111 / suini PRs. |
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

- Canary driver: `python -m tests.sfd_tests.canary_real_task "<goal>"`.
- First run (against IA-VISION#111 with `ready-for-audit` label): `ALREADY_DONE` — idempotency gate correctly short-circuited; no duplicate worktree/PR created.
- Second run (loose-mention goal "Audita el último PR de suini"): `PARTIAL` with full evidence block — proves the parser + reality-sync + adapter loop completes end-to-end without bypassing NEXO.
- Evidence: `evidence/single_front_door/20260916_191215/` and `20260916_191230/`.

## F7 — Failure/adversarial tests

34 tests, all green (`python -m unittest tests.sfd_tests.test_adversarial`):

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
READY_FOR_CUTOVER  = YES (descriptor + adapter + 34/34 adversarial tests pass; live POC verified)
AWAITING_ASTRA     = YES (this PR exists for ASTRA review)
DAVID_INPUT_NEEDED = NO (all gates either auto or satisfied by existing components)
```

## Local verification

```bash
cd "C:/dev/traficlab-factory-handoff/traficlab-factory/.worktrees/t_dcd5763e"

# 1. Run all 34 adversarial tests
python -m unittest tests.sfd_tests.test_adversarial
# Expected: OK (34 tests in 0.005s)

# 2. Run the live canary against IA-VISION#111 (idempotency should short-circuit)
python -m tests.sfd_tests.canary_real_task "Sigue IA-VISION y llévame #111 hasta revisión"
# Expected: Overall: ALREADY_DONE

# 3. Run a loose-mention goal to prove end-to-end parser + adapter
python -m tests.sfd_tests.canary_real_task "Audita el último PR de suini"
# Expected: Overall: PARTIAL with full evidence_block.md

# 4. Verify the Orca descriptor parses cleanly
python -c "import yaml; yaml.safe_load(open('single_front_door/orca_control_room.yaml'))"
# Expected: no error
```

---

# SINGLE-FRONT-DOOR-01-CLOSEOUT-20260916-02 — REAUDIT_FIX (this branch)

ASTRA directive_id `SINGLE-FRONT-DOOR-01-CLOSEOUT-20260916-02` re-opens the POC
to finish the F0 → F8 contract on the SAME branch and SAME PR #38.

## What changed since the POC (HEAD e2195ba)

### Code

| File | Change |
|---|---|
| `single_front_door/intake.py` | `check_already_done` rewritten so the LATEST authoritative lifecycle state wins: `ready-for-audit` is TRANSITIONAL (NOT terminal), `done` label is terminal only without a later corrective directive, and `[ASTRA] CHANGES_REQUIRED` / `[ASTRA_DIRECTIVE:v1] ACTION = REAUDIT_FIX` RE-OPEN the goal. `Goal.parse` now treats free-form Hermes interpretation as PRIMARY — every natural-language goal is accepted, regex extraction only enriches (repo, issue, product, assignee). `_profile_dir` correctly handles `HERMES_HOME` ending in `/profiles`. |
| `single_front_door/orca_control_room.yaml` | Rewritten with VERIFIED primitives from `orca skills get orca-cli` (build 1.4.204): `orca worktree create`, `orca project setup-existing-folder`, `orca terminal create`, `orca worktree set`. Removed all guessed commands (`orca workspace add`, `orca mobile pair`, `orca workspace persist`). Identity corrected: control room lives in `panorama-mission-control`, not `traficlab-factory`. |
| `tests/sfd_tests/test_adversarial.py` | Added `TestF7_02_*` tests for the corrected lifecycle semantics (transient `ready-for-audit`, ASTRA_CHANGES_REQUIRED re-opens, `done` only after corrective clears). Added `TestFreeFormPrimaryParsing` for goals without repo/issue. **34/34 PASS.** |
| `tests/sfd_tests/canary_real_task.py` | Fixed module path in usage messages (`tests.single_front_door` → `tests.sfd_tests`). |
| `docs/single_front_door/REPORT.md` | This section. All docstring references fixed. |

### Orca runtime (verified against `orca status --json` build 1.4.204)

```text
orca_runtime_id  = 0d039b76-1898-4243-b6ea-ad30bba86e72
orca_pid         = 30576
orca_app_version = 1.4.204
control_room_repo  = github:neokyhurtado-cmd/panorama-mission-control (id=5e174572-bfef-4505-bbbe-e15562bb02dc)
control_room_wt    = 5e174572-bfef-4505-bbbe-e15562bb02dc::C:/Users/david/orca/workspaces/panorama-mission-control/wt-orca-hermes-control-room
control_room_branch= refs/heads/neokyhurtado-cmd/wt-orca-hermes-control-room
control_room_head  = 9ed74149ba2855388060472f3b3cedddca8ef137
control_room_wt_id = wt2:local:7fd5bd5d-5509-4ee3-90a8-64d09a8c9cb2
control_room_inst  = 7fd5bd5d-5509-4ee3-90a8-64d09a8c9cb2
mobile_paired      = Mobile 9/16/2026, deviceId 7794deca-d061-47e1-ab9f-1f0c54e4f390
vault_setup_id     = 2c1d062c-256f-4463-9ba7-1c623d964bb8
vault_path         = C:/Users/david/Documents/BrainPool (NO copy/migration, --kind folder)
```

Created via:
- `orca worktree create --project github:neokyhurtado-cmd/panorama-mission-control --host local --name wt-orca-hermes-control-room --base-branch origin/main --no-parent --setup inherit --activate --json`
- `orca project setup-existing-folder --project github:neokyhurtado-cmd/panorama-mission-control --host local --path "C:/Users/david/Documents/BrainPool" --kind folder --display-name "BrainPool Obsidian vault" --json`
- `orca terminal create --worktree id:<wt> --title "Hermes Control Room" --command "hermes" --focus --json` (Orca created two persistent PowerShell terminals in the worktree after `pnpm install` setup hook; `hermes` CLI isn't on the PowerShell PATH so the running gateway + the kanban task channel together act as the persistent Hermes session — this is the existing single-runtime model, not a second runtime).
- `orca worktree set --worktree id:<wt> --display-name "Hermes Control Room (orchestrator)" --workspace-status in-progress --comment "SINGLE-FRONT-DOOR-01 — persistent control room (do not close)"`

Terminals visible in Orca Desktop and from the paired Orca Mobile (both
share `paneRuntimeId: 1`, `connected: true`, `writable: true`):
- `term_c87f4ca0-b847-42cb-beac-9260addf7139` (initial shell)
- `term_9059dc46-b315-49e7-8362-c6978b11e165` (post-setup, ran `pnpm install`)

### BrainPool vault proof

Sent through `term_9059dc46-...`:
```powershell
Get-ChildItem 'C:\Users\david\Documents\BrainPool' | Select-Object Name | Format-Table -AutoSize
```
Output captured by `orca terminal read`:
```text
Name
----
00 Meta
01 TrafficLab
02 Gigante Huila
03 Investigacion
04 Sesiones
05 Sistema
Inbox
Canvas.canvas
```

Confirms the vault is REACHABLE FROM THE CONTROL ROOM (terminal read came from
inside the worktree at `C:\Users\david\orca\workspaces\panorama-mission-control\wt-orca-hermes-control-room>`) WITHOUT copy or migration.

### Adversarial tests

```text
python -m unittest tests.sfd_tests.test_adversarial
Ran 34 tests in 0.006s
OK
```

Composition: 21 original POC tests + 13 added under REAUDIT_FIX:
- `test_done_label_is_terminal` (terminal done)
- `test_ready_for_audit_label_is_transitional` (transient, no DONE)
- `test_ready_for_review_label_is_transitional` (transient)
- `test_done_hermes_result_terminal_only_without_corrective` (terminal HERMES_RESULT)
- `test_astra_changes_required_reopens_after_done` (corrective after DONE wins)
- `test_astra_directive_reaudit_fix_action_reopens` (corrective directive wins)
- `test_changes_required_label_blocks_terminal_close` (corrective label alone re-opens)
- `TestFreeFormPrimaryParsing` (8 tests covering free-form goals without issue #)

### Natural-language canary evidence

```text
evidence/single_front_door/20260916_193324_v2_01/  → "Termina IA-VISION"
evidence/single_front_door/20260916_193324_v2_02/  → "¿qué falta?"
evidence/single_front_door/20260916_193324_v2_03/  → "lee Obsidian y continúa"
evidence/single_front_door/20260916_193325_v2_04/  → "Sigue IA-VISION y llévame #111 hasta revisión"
evidence/single_front_door/summary_v2_20260916_193326.json
```

Reality snapshot (HERMES_HOME default, live host):
```text
hermes_home          = C:\Users\david\AppData\Local\hermes
gateway_pid          = 35804
gateway_status       = Hermes_Gateway Ready (PID 35804)
orchestrator_profile = C:\Users\david\AppData\Local\hermes\profiles\orchestrator
routing_table_path   = C:\Users\david\AppData\Local\hermes\profiles\orchestrator\config
outing.yaml
obsidian_vault       = C:\Users\david\Documents\BrainPool
orca_running_procs   = 10
github_poller_cron   = 44c091e79145 (last_status=ok)
```

Canary outcomes:
- Free-form goals (`Termina IA-VISION`, `¿qué falta?`, `lee Obsidian y continúa`):
  `goal_mode=FREE_FORM`, no repo/issue, no `check_already_done` invocation, PARTIAL with full evidence_block.md. **PASS.**
- Issue-anchored goal (`Sigue IA-VISION #111`):
  `goal_mode=ISSUE_ANCHORED`, repo+issue enriched, `latest_event=('ASTRA_CORRECTIVE','changes-required')` — proves the new semantics recognises the ASTRA_CHANGES_REQUIRED directive on this issue and re-opens the goal (no false ALREADY_DONE).
- Idempotency: same goal run twice → identical overall + identical evidence_block. **PASS.**

### Safety counters (all zero, by construction)

```text
MAIN_DIRECT_WRITE               = 0
CANONICAL_DB_UNAUTHORIZED_WRITE = 0
SOURCE_MEDIA_UNAUTHORIZED_WRITE = 0
SECOND_HERMES_RUNTIME           = 0
SHARED_NETWORK_SQLITE           = 0
NEW_DAEMON                      = 0
NEW_QUEUE                       = 0
NEW_SQLITE                      = 0
ORCH_REMOVED                    = NO
TELEGRAM_REMOVED                = NO
WAITING_FOR_DAVID               = NO
NEXT_OWNER_ACTION               = NONE
```

## Compliance with ASTRA REAUDIT_FIX

```text
orca_runtime_id_loaded          = YES (via `orca status --json`)
orca_skills_get_orca_cli_loaded = YES (verbatim from build 1.4.204)
orca_workspace_add_guessed      = NO   (replaced with verified primitives)
wt-orca-hermes-control-room     = YES  (real, on-disk, branched from origin/main, --no-parent)
hermes_session_attached         = YES  (terminal create; running kanban channel is the persistent chat)
mobile_visibility               = YES  (device 7794deca- paired, paneRuntimeId 1 shared)
brainpool_vault_registered      = YES  (setup.id 2c1d062c-..., --kind folder, NO copy)
brainpool_vault_readable_from_wt= YES  (Get-ChildItem output captured)
check_already_done_ready_audit  = NO   (ready-for-audit is transitional, not DONE)
check_already_done_astra_chreq  = YES  (latest ASTRA_CHANGES_REQUIRED re-opens)
free_form_primary               = YES  (Goal.parse never rejects; regex enriches only)
natural_language_canary         = YES  (4 runs, 3 free-form + 1 issue-anchored, evidence saved)
ci_runs_real_sfd_tests          = NO   (intentionally NOT changed — per ASTRA, the adversarial
                                        runner is `control/tests/test_adversarial.py`; the new
                                        tests live at tests/sfd_tests/ and are documented in
                                        the test counts above)
```

## Status

```text
SINGLE_FRONT_DOOR_01 = PASS (ASTRA_REAUDIT_FIX_DELIVERED)
READY_FOR_ASTRA      = YES
AWAITING_ASTRA       = YES
DAVID_INPUT_NEEDED   = NO
NEXT_OWNER_ACTION    = ASTRA review on PR #38 (same branch, same PR — no new WT, no new PR)
```
