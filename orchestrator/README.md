# Orchestration-only control-plane (HERMES-ORCH)

This directory owns the **single source of truth** for routing, polling, and
the narrow ORCH inbound Work-Order action. Per `ORCH-V1 §Roles`, only the
**HERMES-ORCH** profile (`~/.hermes/profiles/orchestrator/`) may write files
under `config/` and `scripts/` here. Every other profile and every other
operator must read from here.

This is part of `WO-ORCH-AUTODISPATCH-02` (SUINI issue #36).

## What's here

```
config/routing.yaml              # repo → product → assignee (single source of truth)
scripts/
  routing_resolver.py            # reads routing.yaml; resolver used by everything
  eligibility.py                 # E1..E6 pre-spawn gate logic
  eligibility_hook.py            # one-liner hook that emits WO_ROUTING_DENIED events
  github_poller.py               # 60s cron: gh → kanban task per labelled WO
  orch_inbound_wo.py             # narrow Telegram/Discord → GitHub WO action
  recovery_observer.py           # marks stuck tasks as RECOVERY_REQUIRED
  test_*.py                      # pytest unit tests for each module
```

## Decision precedence (locked in SUINI#35.AD-1)

1. **routing.yaml is the routing authority.** `route.repo == incoming.repo` →
   use that route. First match wins.
2. **task.assignee mismatch → deny** with
   `PRODUCT_OWNERSHIP_MISMATCH: assignee=<X> product=<Y> expected=<Z>`.
3. **Unknown repo → deny** with `PRODUCT_OWNERSHIP_MISMATCH: repo=<X>`.
   NEVER silently fall back to `kanban.default_assignee`.

## Path resolution (locked in WO-ORCH-AUTODISPATCH-02 step 3)

`routing_resolver.py` reads `routing.yaml` in this order:

1. `$HERMES_ROUTING_PATH` (explicit override; for tests / one-offs).
2. `$HERMES_HOME/config/routing.yaml` (normal cron path).
3. `<script-dir>/../config/routing.yaml` (default fallback when no env).

Tests for each tier live in `scripts/test_routing_resolver.py::TestPathResolution`.

## Fail-closed contract (locked in step 4)

`github_poller.watched_repos()` filters the routing table by:

- Skipping repo-less entries (e.g. ASHLEY fallback).
- Skipping routes whose `assignee:` is missing.
- Skipping routes whose `assignee:` profile is not on disk
  (looks under the hermes profiles root via
  `hermes_cli.profiles.list_profile_names()`).

`created_kanban_task()` re-validates the resolved assignee against the routing
table right before spawning `hermes kanban create`. If the table mutates
mid-tick, the issue is dropped rather than claimed under a stale assignee.

## ORCH inbound WO action (locked in step 6)

`orch_inbound_wo.py` is the only Telegram/Discord → GitHub WO entry point.

Allowed actions: `create_wo`, `update_wo`, `add_label`, `remove_label`,
`transition_status`. Anything outside this list (including shell-style verbs)
is rejected before any external call.

Allowed requesters: `david-telegram`, `david-discord`. The chat_id must
also appear in `$ORCH_INBOUND_DAVID_CHAT_IDS` (comma-separated).

Allowed products / repos: derived from `config/routing.yaml`.

Allowed labels: `hermes-work-order`, `orchestration`.

Allowed statuses (transition_status): `open`, `reopen`, `closed`.

Every accepted action writes an `ORCH_INBOUND_WO` audit row into the kanban
DB. The audit row's `task_id` is the payload's `idempotency_key` when present.

NO raw shell text is accepted; NO arbitrary command execution is possible.

## Cron job lifecycle (locked in step 7)

`hermes cron list` against the orchestrator profile shows two jobs:

```
44c091e79145  github-poller          every 1m   (no_agent)
b5106e145fab  kanban-recovery-observer every 5m  (no_agent)
```

Both jobs read their config from this profile's `cron/jobs.json`. The
`hermes cron list` output is anchored to `$HERMES_HOME/cron/jobs.json` —
the same file the orchestrator scheduler ticks. If they ever diverge
(e.g. a migration wrote to the global root), the diagnosis script is
`scripts/diagnose_cron_truth.sh`.

## Tests

Run all tests with:

```bash
cd ~/.hermes/profiles/orchestrator/scripts
python -m pytest
```

You should see ~77 tests pass (paths vary slightly with profile growth).

## Install / sync

This is a controlled file under `~/.hermes/profiles/orchestrator/`. To
introduce a new router entry, edit `config/routing.yaml` and (if needed)
the destination profile directory under `~/.hermes/profiles/`. To add a
new control-plane script, drop it under `scripts/` next to the others;
make sure it imports `routing_resolver` rather than duplicating route
logic.

DO NOT:

- Hand-edit `~/.hermes/profiles/<other>/**` from this profile.
- Put a `routing.yaml` somewhere other than `config/`.
- Add a hardcoded `WATCHED_REPOS` tuple to `github_poller.py`.
- Run shell-style actions through `orch_inbound_wo.py`.

## Restart-safe recovery (locked in step 9)

`github_poller.py` is `no_agent` and reads its config fresh every tick.
After a gateway restart:

1. The next cron tick reads `config/routing.yaml` from disk.
2. The resolver finds the live profiles.
3. No state lives in the poller process beyond the `TEMP/github_poller_seen.json`
   dedup log (and that is best-effort — its loss only re-announces already-known
   WOs, which the kanban CLI's `--idempotency-key` dedupes).

To prove restart-safety:

```bash
# 1. confirm cron list shows the jobs
hermes -p orchestrator cron list | head -20

# 2. trigger the poller manually
python ~/.hermes/profiles/orchestrator/scripts/github_poller.py

# 3. confirm no duplicate task was created (compare to existing kanban tasks)
hermes kanban list | grep -i hermes-work-order
```
