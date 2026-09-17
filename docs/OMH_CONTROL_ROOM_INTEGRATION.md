# Oh My Hermes inside TraficLab Factory

## Status

This integration treats Oh My Hermes (OMH) as an operating layer inside the
persistent Hermes Control Room. It does not replace the factory.

Pinned upstream:

- version: v2.0.3
- commit: 47ab4e27682337c031e08b73ae6c1a42eb69b7f7
- release wheel SHA256:
  8b0eccddb0cfe38364881b0f5b3e61f8eb13cc0d761519b73958e356e87f754f

## Authority map

| Surface | Canonical owner |
|---|---|
| Human front door | Hermes Control Room in Orca |
| Interactive worktrees | Orca |
| Request/workflow routing | OMH may assist |
| Fanout/readiness/progress state | OMH may assist |
| GitHub directive wake | NEXO watcher |
| Transport | existing single Hermes gateway |
| Durable execution truth | GitHub |
| Knowledge / human decisions | Obsidian/Panorama |
| Product health | TrafficLab Control / Mission Control |
| Independent critic | Jupiter |

OMH memory is not project canon.
OMH self-review is not Jupiter.
OMH route hints are not authorization.

## Phase A — isolated compatibility canary

Run from a clean worktree of this branch:

    python scripts/omh_canary.py

The canary:

1. resolves upstream tag v2.0.3 and requires its exact pinned commit;
2. downloads the official release wheel;
3. verifies the published wheel SHA256;
4. installs into a temporary Python venv;
5. creates temporary OMH_HOME and HERMES_HOME;
6. runs OMH setup dry-run;
7. runs setup against the isolated Hermes home;
8. runs doctor;
9. runs upstream Hermes smoke when the Hermes CLI is available;
10. hashes ambient ~/.hermes/config.yaml and sibling profile configs before
    and after;
11. writes evidence/omh_canary/omh_canary_latest.json;
12. deletes the sandbox unless --keep-sandbox was requested.

PASS requires that the ambient Hermes configuration is unchanged.

This phase creates no scheduler, listener, transport owner, product DB write
or source-media write.

## Phase B — live Control Room activation

Only after Phase A PASS.

Before mutation, discover and record:

- exact persistent Control Room Hermes home;
- exact Control Room session/workspace;
- current config hash;
- sibling profile config hashes;
- existing transport owner count/identity;
- NEXO watcher owner;
- current Orca worktrees.

Create a rollback copy of the exact target config.

Install the same pinned OMH generation and apply OMH setup only to the exact
Control Room Hermes home. Do not run model-setup or model-chain alias changes.
Do not enable MCP.

After setup:

- target Control Room may contain OMH managed skill/plugin registration;
- Ashley/SUINI and all sibling Hermes profile hashes must remain unchanged;
- transport owner count must remain unchanged;
- NEXO remains the only GitHub directive wake owner;
- no new scheduler/listener/queue/state DB is allowed;
- Orca remains worktree owner.

If OMH setup attempts sibling-profile sync, revert immediately and classify
AUTHORITY_COLLISION_PROFILE_SYNC.

## Phase C — real reversible task

Use one existing safe factory task, not a synthetic product mutation.

Required evidence:

1. Control Room stays responsive.
2. OMH route is recorded.
3. At least three independent units are materialized when the task genuinely
   supports parallelism.
4. Fresh unit activity is required for RUNNING_CONFIRMED.
5. A deliberately stalled unit becomes PROGRESS_STALLED.
6. PASS is impossible until a validated result record exists.
7. Jupiter independently reviews the final result.
8. GitHub receives durable evidence.
9. No canonical DB/source-media write occurs.

## Rollback

Rollback means:

1. stop/restart only the Control Room Hermes session as needed;
2. restore the exact pre-activation target config;
3. remove only OMH-managed artifacts from the Control Room target home;
4. do not touch NEXO, gateway, other profiles, Orca worktrees or product DBs;
5. run the same hashes/owner-count checks after rollback.

## Promotion decision

OMH may become the default internal routing/fanout layer only when all three
phases pass.

Even after promotion, these invariants remain permanent:

    OMH != transport owner
    OMH != scheduler owner
    OMH != worktree owner
    OMH != project-memory authority
    OMH != durable execution truth
    OMH != independent critic
