---
name: single-front-door
description: Use when the user sends a free-form goal to a single Hermes Control Room session. Implements the GOAL_RECEIVED contract from traf ic lab-factory #37 — reality-sync, plan, execute, report. Do NOT create new daemons, queues, or SQLite; reuse NEXO, ORCH, and existing routing.
---

# SINGLE-FRONT-DOOR-01 — Goal-loop behavioral contract

This skill encodes the F2 contract from traf ic lab-factory #37. When loaded, the Hermes Control Room session MUST walk the goal loop end-to-end, preferring native primitives and existing components (NEXO, ORCH, Obsidian adapter, existing routing) over any new service.

## Trigger
A user message that contains a single, free-form goal in natural language — not a directive, not a `[HERMES_ACK]` reply. Examples:

- "Sigue IA-VISION y llévame #111 hasta revisión"
- "Audita el último PR de suini y dime si hay que tocarlo"
- "Cierra traf ic lab-factory #18 si pasa los tests"

## The contract

```
GOAL_RECEIVED
  → REALITY_SYNC
  → CHECK_ALREADY_DONE_OR_STALE
  → MAP_TO_EXISTING_PROJECT/ISSUE/GOAL
  → CONSULT_OBSIDIAN/PANORAMA_CONTEXT
  → PLAN
  → EXECUTE_SAFE_NEXT_GATE
  → CREATE_OR_REUSE_ORCA_WORKTREE_IF_NEEDED
  → DELEGATE_TO_AGENT/TOOLS
  → TEST/VERIFY
  → UPDATE_GITHUB_EVIDENCE
  → UPDATE_OBSIDIAN_DECISION/STATE WHEN MATERIAL
  → AUTO_CONTINUE
  → REPORT_MATERIAL_PROGRESS
  → DONE | HUMAN_STOP | EXTERNAL_BLOCKER
```

## Anti-proliferation (F2 §Anti-proliferation)

- **Prefer existing issue/master goal.** Do not create a new GitHub issue per subtask unless no durable carrier exists.
- **One active writer per scope.** Never two profiles writing the same repo in parallel.
- **Reality-sync before worktree creation.** F0 must be runnable before F1.
- **If work already exists or is merged, classify and do not duplicate.** Check `gh issue list --state all` and the relevant PR/branch.

## Autonomous safe gates (AUTO_CONTINUE — F2 §Autonomous safe gates)

| Action | Auto? |
|---|---|
| Read / audit / research | YES |
| Plan / replan | YES |
| Orca worktree create/remove via Orca CLI | YES |
| Reversible code/docs/tests in feature branches | YES |
| Browser/Design Mode verification | YES |
| Test / CI / debug loops | YES |
| Commits / push to feature branch | YES |
| Opening / updating PR | YES |
| GitHub evidence comments | YES |
| Bounded Obsidian state/decision notes | YES |
| Status reports / notifications | YES |

## Human hard stops ONLY (F2 §Human hard stops)

Escalate to David ONLY for:

1. Merge to `main` / release / production promotion
2. Secret / token / provider / license / payment / credential changes
3. Destructive or irreversible canonical data mutation
4. Physical pairing / device / permission action
5. Material product / scientific decision not deterministically resolvable from evidence
6. External hardware / data / credential blocker

**Technical implementation choices are NOT human stops.** Pick, document, move on.

## Reporting contract (F4)

Report ONLY material transitions — not every command or test:

```
GOAL_ACCEPTED
WORK_STARTED
MATERIAL_BLOCKER
READY_FOR_REVIEW
NEEDS_HUMAN_GO_REAL
DONE
```

Minimal human-facing report shape:

```
GOAL =
CURRENT_PROJECT =
CURRENT_GATE =
WHAT_CHANGED =
TESTS/EVIDENCE =
BLOCKER = NONE | ...
NEXT = AUTO_CONTINUE | HUMAN_GO_REAL | DONE
```

No periodic spam if nothing material changed.

## Native notification/fallback (F5)

Use Orca native finished/attention notifications where available. Telegram is for `DONE`, `HUMAN_GO_REAL`, material blocker, or Orca/runtime unavailable. Telegram is **NOT** a second orchestration state machine and **does NOT** hold session state.

## Architecture authority (F0 — frozen)

```
INTERACTIVE_WT_OWNER = ORCA
ORCHESTRATION_BRAIN = HERMES
EXECUTION_DURABLE_TRUTH = GITHUB
KNOWLEDGE = OBSIDIAN/PANORAMA
PRODUCT_STATE = TRAFFICLAB CONTROL
TRANSPORT_OWNER = EXISTING SINGLE HERMES GATEWAY
```

If any step in the goal loop would violate this authority map, STOP and report.

## Idempotency (F7 §1)

Before claiming work:

1. Check if the same goal already produced a kanban task (`hermes kanban list --assignee=<self>` and grep).
2. Check if the issue/PR is already in `READY_FOR_REVIEW` or `DONE` state.
3. If yes — report `ALREADY_DONE` and exit; do not duplicate worktree/PR/session.

## Required terminal evidence (from issue body)

The skill MUST produce, at end of run, a markdown block of this exact shape so ASTRA can validate without re-querying:

```
SINGLE_FRONT_DOOR_01 = PASS|PARTIAL|BLOCKED
CONTROL_ROOM =
CONTROL_ROOM_HOST =
CONTROL_ROOM_ORCA_WORKSPACE =
ORCA_MOBILE_CHAT_FOLLOWUP = PASS|FAIL
ORCA_DESKTOP_CHAT_FOLLOWUP = PASS|FAIL
ONE_GOAL_END_TO_END = PASS|FAIL
GOAL_USED =
PRODUCT_WORKTREE_CREATED_BY_ORCA =
OBSIDIAN_READ = PASS|PARTIAL|BLOCKED
OBSIDIAN_WRITE_BOUNDED = PASS|PARTIAL|NOT_NEEDED
GITHUB_DURABLE_EVIDENCE = PASS|FAIL
TELEGRAM_ALERT_FALLBACK = PASS|PARTIAL|FAIL
DUPLICATE_GOAL_IDEMPOTENCY = PASS|FAIL
ORCA_RESTART_RECOVERY = PASS|FAIL
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
WAITING_FOR_DAVID = NO unless physical pairing/secret/HUMAN_GO_REAL
NEXT_OWNER_ACTION = NONE | <exact hard stop>
```

## What this skill does NOT do

- It does NOT install a second gateway, queue, daemon, SQLite, or chat app.
- It does NOT bypass NEXO when a directive carries an ASTRA `ACTION = BUILD/CONTINUE/REVIEW`.
- It does NOT write to canonical DB or source media without explicit `HUMAN_GO_REAL`.
- It does NOT cross-write IA-VISION and SUINI — read the authority map.
- It does NOT delete existing dispatch/poller/Telegram components. F8 says classify as KEEP / ADAPT / RETIRE_CANDIDATE only.
