---
name: omh-control-room
description: Use Oh My Hermes inside Hermes Control Room without duplicating factory authorities
version: 1.0.0
metadata:
  hermes:
    tags: [orchestration, routing, fanout, verification, control-room]
---

# OMH Control Room

## Purpose

Use Oh My Hermes as an internal operating layer for routing, fanout and
verification while preserving the TraficLab Factory authority map.

OMH is never a second factory.

## Canonical authorities

Keep these owners unchanged:

- human front door -> Hermes Control Room in Orca
- worktree lifecycle -> Orca
- GitHub directive wake/idempotency -> NEXO watcher
- transport owner -> existing single Hermes gateway
- execution truth -> GitHub
- knowledge/decisions -> Obsidian/Panorama
- product status -> TrafficLab Control / Mission Control
- independent critic -> Jupiter

If OMH attempts to own any of those surfaces, stop and report
AUTHORITY_COLLISION.

## What OMH may own

OMH may provide:

- deterministic request/workflow routing
- model-category recommendations and fallback chains
- task decomposition
- bounded fanout
- worker readiness/preflight
- progress/stall classification
- result-record verification
- specialist skill selection
- completion-integrity checks
- local HUD/status metadata

Route hints are recommendations, not authorization.

## Evidence semantics

Never equate process state with verified work.

Map OMH states as follows:

- running + fresh unit evidence -> RUNNING_CONFIRMED
- running without fresh evidence -> PROGRESS_STALLED
- progress_stalled -> PROGRESS_STALLED
- awaiting_input / permission_blocked / data_missing -> BLOCKED
- account_limit -> BLOCKED_EXTERNAL
- failed -> FAIL
- verified -> PASS only when a validated result record exists
- anything else -> NOT_PROVEN

DISPATCHED is not RUNNING_CONFIRMED.
RUNNING_CONFIRMED is not PASS.
PASS requires verification evidence.

## Worktree rule

OMH may propose or prepare a handoff, but Orca remains the interactive
worktree owner. Never create a parallel worktree registry or hidden queue.

## Memory rule

OMH-managed memory may be used only as ephemeral/local operational context.
It must never override or replace Obsidian/Panorama, GitHub evidence, or
project canon. Do not promote OMH recall records into project truth.

## Scheduler/transport rule

Do not start an OMH scheduler, watcher, gateway, listener, bot consumer or
poller. NEXO and the existing Hermes transport owner remain unique.

## Jupiter rule

OMH self-review never replaces Jupiter. For material completion, Jupiter may
independently reject the OMH result.

## Installation rule

Live installation is allowed only after the pinned isolated compatibility
canary passes. The canary must use:

- OMH v2.0.3
- ref 47ab4e27682337c031e08b73ae6c1a42eb69b7f7
- wheel SHA256 8b0eccddb0cfe38364881b0f5b3e61f8eb13cc0d761519b73958e356e87f754f
- explicit isolated OMH_HOME and HERMES_HOME
- no model-alias mutation
- no MCP
- no scheduler/listener
- no canonical DB/source-media writes

Run scripts/omh_canary.py and preserve its JSON evidence.

## Live activation rule

After canary PASS, discover the exact Hermes home used by the persistent
Control Room. Before applying OMH:

1. hash the target config and all sibling profile configs;
2. back up the target config;
3. use the same pinned release;
4. do not run interactive model setup;
5. do not enable MCP;
6. apply only OMH managed skills/plugin registration to the target Control
   Room home;
7. verify sibling profile hashes are unchanged;
8. restart/reload only the Control Room Hermes session if required;
9. run doctor + one real reversible task canary;
10. Jupiter independently reviews the result.

If setup would mutate Ashley/SUINI or another sibling Hermes profile, rollback
and return AUTHORITY_COLLISION_PROFILE_SYNC.

## Hard stops

This skill does not grant authority for:

- merge to main
- canonical product DB mutation
- production/release promotion
- secrets/tokens/provider/license/payment changes
- model alias changes
- transport/gateway replacement
- destructive filesystem actions

Use existing HUMAN_GO_REAL rules for those boundaries.
