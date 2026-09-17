# CARRIER.md — HERMES-RESEARCH-G5

```text
ROLE                 = HERMES-RESEARCH-G5
WORKTREE             = .worktrees/wt-orca-g5-research
BRANCH               = feat/g5-research-sha37
DIRECTIVE_ID         = ORCA-G5-FANOUT-PHYSICAL-ENFORCE-20260917-01
PARENT_EXEC_ID       = exec-5720239178-2cd2c58e
PARENT_SESSION_ID    = sess-9587bdf9c864
DIRECTOR_SESSION_ID  = sess-f5d14f11ed3e
DIRECTOR_EXEC_ID     = exec-5720351179-9a445c07
SOURCE_COMMENT_ID    = 5720351179
ISSUE                = neokyhurtado-cmd/traficlab-factory#37
MAIN_BASE            = 6b4c643780221c48c825bd336d7ffe9b463c882a
CONTROL_ROOM_ROLE    = DIRECTOR_ONLY
RUNNING_CONFIRMED    = YES (carrier commit pushed to origin)
```

## SCOPE

READ-ONLY hash & provenance reconciliation across P2/P4/P5/P6/P7 datasets. Produce SHA256 manifest of canonical inputs (videos, labels, model weights, SoT tables) and reconcile against any prior IA-VISION G5 outputs (PRs #144, #149, #91, #88, #112). No GPU, no reruns, no file mutation.

## HARD STOPS

NO GPU, NO model reruns, NO dataset mutation, NO source media write, NO canonical DB write. READ-ONLY filesystem access.

## HANDOFF

HERMES-PROCESS-G5 (SHA-matched rerun list) and HERMES-REVIEW-G5 (provenance verdict).

## DELIVERABLE

swarm/SHA_MANIFEST.json + swarm/PROVENANCE_REPORT.md (both inside this worktree, committed).

## Director binding

This worker lane was materialized by the orchestrator session (sess-f5d14f11ed3e) acting as DIRECTOR_ONLY. The orchestrator does NOT perform bulk research, code edits, tests, browser verification, dataset processing, or long-running product operations while this lane is eligible.

## Cross-agent reconciliation

Each lane commits its deliverable inside this worktree. The director runs a reconciliation pass BEFORE publishing ASTRA_QUERY durable: cross-references between lanes (SHAs, video IDs, endpoint shapes, class names, JS state fields) are verified against the actual working tree. HERMES-REVIEW-G5 carries the adversarial review lane and produces the final JUPITER_REVIEW_NOTE:v1.