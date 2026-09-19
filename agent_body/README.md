# Agent Body — `agent_body/`

A read-only sidecar package that lets a fresh Hermes worker recover a
task's durable state (project, issue, HEAD, evidence already checked,
authority map, next safe action) from a SQLite checkpoint alone — no
manual context copy/paste.

Per directive `evolution-v1-closeout-20260914-01` (issue #27), this
package implements BODY-0 + BODY-1 + BODY-2 with the strict policy:

  - **STALE detection**: if `last_verified_head` differs from the live
    GitHub HEAD, the worker stops and demands reconciliation. Never
    silently continues.
  - **ACTOR_UNVERIFIED**: a review whose correlation fields (QUERY_ID,
    REPOSITORY, ISSUE_OR_PR, COMMIT_SHA) do not match the consultation
    bundle cannot vote.
  - **Counterexample precedence**: one reproducible counterexample
    overrides any number of optimistic GO votes.

## Layout

```
agent_body/
  __init__.py
  README.md                  <- this file
  SKILL.md                   <- bootstrap shape for fresh sessions
  manifest.py                <- BODY-0 manifest loader + frozen boundary denials
  checkpoint_store.py        <- BODY-1 durable SQLite sidecar
  audit.py                   <- BODY-1 structured audit events (no free text)
  authority.py               <- BODY-1 authority conflict resolver
  skill_discovery.py         <- /internal-consult discoverability
  internal_consult_synth.py  <- INTERNAL_CONSULT executable oracle
  worker_bootstrap.py        <- BODY-2 fresh-session bootstrap + canary
  tests/                     <- all agent_body regression tests
```

## Safety boundaries (frozen, mirrored from #27 body)

| Boundary | State |
|---|---|
| HERMES_RUNTIME_CHANGE | NO |
| MINIMAX_PROVIDER_CHANGE | NO |
| CONFIG_YAML_CHANGE | NO |
| ENV_CHANGE | NO |
| GATEWAY_CHANGE | NO |
| TELEGRAM_CHANGE | NO |
| DISCORD_CHANGE | NO |
| WHATSAPP_CHANGE | NO |
| DOCKER_REQUIRED | NO |
| KUBERNETES | NO |
| NEW_ORCHESTRATOR | NO |
| NEW_CHAT_SYSTEM | NO |
| NEW_VECTOR_DB | NO |
| NEW_KNOWLEDGE_BASE | NO |

Every one of the actions these boundaries forbid is listed in
`agent_body/manifest.py::FROZEN_BOUNDARY_DENIED_CAPABILITIES` and
verified by `tests/test_body0_contract.py::test_manifest_denies_every_frozen_boundary_action`.

## Verification

```bash
pytest agent_body/tests/ -v
```

Expected: 55 tests pass across 8 files. Coverage:

  - BODY-0 contract (5 tests): manifest denials, no free-text columns,
    no secret columns, no prompt injection surface, no out-of-scope edits.
  - BODY-1 round-trip (4 tests): fresh-session write, fresh-session read,
    authority conflict precedence, fail-closed on no precedence match.
  - EVOLUTION-E2E-001 checkpoint recovery (4 tests): full bootstrap
    round-trip, seven bootstrap fields derivable, STALE detection,
    fresh-checkpoint ACTIVE.
  - EVOLUTION-E2E-001 actor & AUTO_GO (4 tests): tampered COMMIT_SHA
    rejected, tampered QUERY_ID rejected, 4 valid GOs → AUTO_GO, one
    counterexample → AUTO_REPLAN.
  - EVOLUTION-V1 canary (2 tests): full chain directive → done with
    checkpoint, chain blocks when checkpoint goes stale.
  - INTERNAL_CONSULT executable (5 tests): correlation parser rejects
    mismatch on QUERY_ID + COMMIT_SHA, ACTOR_UNVERIFIED is a real
    branch, transitive secret scan, skill discoverability.
  - Role whitelist + enum enforcement (27 tests, added by
    `evolution-v1-role-whitelist-fix-20260914-01`): canonical role /
    decision / risk sets frozen; correlate() rejects non-canonical role
    on direct-dict and envelope paths; correlate() fails closed on every
    missing required correlation field; non-canonical decisions and risk
    levels are rejected; the headline sabotage proves three
    non-canonical roles (PROMPTER / GHOST / MINION) can never push a
    quorum of four to AUTO_GO; negative control confirms all four
    canonical roles still produce AUTO_GO.

## Rollback

`git rm -rf agent_body/` is zero-residue. No runtime, .env, config.yaml,
gateway, channel, scheduler, orchestrator, or hermes-cli mutation was
performed to install this package.
