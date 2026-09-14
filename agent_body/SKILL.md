# Agent Body Bootstrap — `agent_body/SKILL.md`

This SKILL describes the minimum shape a fresh Hermes session needs to
recover a task's durable state from `agent_body/` alone, without any
prior chat transcript and without David briefing.

The seven bootstrap fields (per directive #27 body):

  1. `BODY_ID` — UUIDv4 of the body that owns the checkpoint
  2. `AGENT_ID` — identity of the current worker
  3. `ACTIVE_PROJECT` — repo:// pointer (e.g. `neokyhurtado-cmd/traficlab-factory`)
  4. `ACTIVE_TASK` — issue:// pointer (e.g. `#27`)
  5. `LAST_CHECKPOINT` — path to the checkpoint SQLite
  6. `AUTHORITY_MAP` — precedence (github_remote > mission_control > ia_vision_domain > local_checkpoint)
  7. `CAPABILITY_NAMESPACES` — the explicit list of allowed capabilities

## Procedure for a fresh session

1. Load `agent_body/manifest.py::load_manifest(<path>)` — gives you the
   `BODY_ID`, allowed/denied capabilities, and authority precedence.
2. Open `agent_body/checkpoint_store.py::CheckpointStore(<db>)`.
3. Call `.read(task_id)` — gives you `ACTIVE_PROJECT`, `ACTIVE_TASK`,
   `LAST_VERIFIED_HEAD`, `EVIDENCE_ALREADY_CHECKED`, `BLOCKERS`,
   `NEXT_SAFE_ACTION`.
4. Call `.check_freshness(task_id, current_head=<live>)` — returns
   `FreshnessVerdict`. If `state == "STALE"` → STOP, do not continue.
5. Call `.derive_bootstrap(cp)` — produces the 7-field bootstrap dict
   the worker feeds into its own prompt.

## Policy on stale

If the live HEAD has advanced past the checkpoint, the body returns
`STATE = STALE, RECONCILIATION_REQUIRED = YES, safe_action = stop_and_reconcile`.
The worker MUST NOT continue silently. Reconciliation = re-fetch the
directive's evidence comments from GitHub, decide whether the drift is
routine (e.g. a parser fix) or substantive (e.g. a scope change), and
only then resume.

## Policy on actor

A consultation review with a tampered `COMMIT_SHA` or `QUERY_ID` returns
`ACTOR = ACTOR_UNVERIFIED` from `correlate()` and is excluded from the
quorum by `synthesize()`. The vote does not count.
