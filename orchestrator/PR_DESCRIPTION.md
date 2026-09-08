# WO-ORCH-AUTODISPATCH-02 — Orchestration control-plane

This PR adds the orchestration-only control-plane artifacts under
`orchestrator/`. They are the single source of truth for repo → product →
assignee routing and the narrow Telegram/Discord → GitHub WO action.

**Not** a product-code change. No files in `neokyhurtado-cmd/IA-VISION` or
`neokyhurtado-cmd/suini` were touched.

## What's in this PR

```
orchestrator/
  README.md                             # install + sync instructions
  config/
    routing.yaml                        # repo → product → assignee authority
  scripts/
    routing_resolver.py                 # reads routing.yaml; one resolver
    eligibility.py                      # E1..E6 pre-spawn gate logic
    eligibility_hook.py                 # one-liner hook for the dispatcher
    github_poller.py                    # 60s cron: gh → kanban task per WO
    orch_inbound_wo.py                  # narrow Telegram/Discord → GitHub
    recovery_observer.py                # RECOVERY_REQUIRED marker
    diagnose_cron_truth.sh              # prove cron list == jobs.json
    test_routing_resolver.py            # 17 tests
    test_github_poller.py               # 11 tests
    test_eligibility.py                 # 13 tests
    test_orch_inbound_wo.py             # 31 tests
```

## Decision precedence (locked in SUINI#35.AD-1)

1. `route.repo == incoming.repo` → use that route. First match wins.
2. `task.assignee` mismatch → deny with `PRODUCT_OWNERSHIP_MISMATCH:`.
3. No match → deny with `PRODUCT_OWNERSHIP_MISMATCH: repo=<X>`.
   NEVER silently fall back to `kanban.default_assignee`.

## What's new since the previous pilot (SUINI#35.AD-5)

- **Real target profiles** `ia-vision` and `suini` exist on disk
  (`~/.hermes/profiles/{ia-vision,suini}/profile.yaml` carries
  `assigned_product`).
- **routing_resolver** has a documented 3-tier path resolution
  (`HERMES_ROUTING_PATH` > `HERMES_HOME/config/routing.yaml` > default
  fallback) and 7 deterministic tests covering each tier.
- **github_poller** no longer hardcodes `WATCHED_REPOS`; it reads
  `routing.yaml` via the resolver. Fail-closed when a route's assignee
  profile is missing on disk.
- **mining task double-claim guard**: `create_kanban_task` re-validates
  the resolved assignee against the table immediately before spawning
  `hermes kanban create`. No second writer can claim under a stale
  assignee.
- **orch_inbound_wo** is the narrow Telegram/Discord → GitHub action.
  Allowed actions: `create_wo`, `update_wo`, `add_label`, `remove_label`,
  `transition_status`. Allowed requesters: `david-telegram`, `david-discord`
  (with chat_id allow-list via `ORCH_INBOUND_DAVID_CHAT_IDS`). Allowed
  labels: `hermes-work-order`, `orchestration`. NO raw shell text; NO
  arbitrary command execution. Every accepted action writes a
  `ORCH_INBOUND_WO` audit row.
- **diagnose_cron_truth.sh** proves `hermes cron list` agrees with
  `cron/jobs.json` on (id, schedule).
- **77 unit tests pass** in 0.86s on Windows / Python 3.11.

## Canary evidence

Two fresh WOs were originated on GitHub, labelled `hermes-work-order`,
auto-routed by the orchestrator poller, dispatched to the real target
profile, and reached terminal DONE without manual intervention:

- IA-VISION#41 → t_5579fbb0, assignee=`ia-vision`, run 114, completed 28s.
- suini#37   → t_334a9e38, assignee=`suini`,   run 115, completed 30s.

Each task carried `READ_ONLY: true` body semantics enforced by the
routing table; the worker workspaces stayed empty scratch as required.

## ASHLEY status

`BLOCKED_BY_TARGET_ABSENCE` per SUINI#29. Ashley is intentionally NOT
created in this PR — that decision lives with #29, which remains the
authority for Ashley's onboarding.

## Forbidden-list audit

- No secrets / tokens disclosed or rotated.
- No provider / model change.
- No unrestricted chat-to-shell (orch_inbound_wo is narrow allow-list only).
- No IA-VISION / SUINI product code or data touched.
- No duplicate writers or silent reassignment.
- No fabricated Ashley profile.
- PR is NOT auto-merged.
