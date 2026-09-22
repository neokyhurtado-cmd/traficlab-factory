# JEV Decision Plane V1

Status: LIVE PROVIDER CAPABLE / ADVISORY AUTHORITY

Jev is TypeSafe AI's System One model. In TrafficLab Factory it is used as a
fast typed decision layer for Hermes, not as an executor or protected-action
authority.

## Runtime path

Every directive reaching `default_execution()` gets a Jev advisory evaluation
before dispatch. The result is written to the execution evidence directory as:

`jev_shadow.json`

The watcher remains fail-soft:
- no `TYPESAFE_API_KEY` -> provider_status=UNAVAILABLE; dispatch continues
- TypeSafe/API failure -> provider_status=ERROR; dispatch continues
- protected directive -> hard_gate_override=true; normal HUMAN_GO logic wins

## Decisions

A single request asks five typed questions:
1. route: code / research / review / ops / other
2. needs_review: Noul probability
3. blocker: none / missing_data / permission / provider / scientific / runtime / other
4. continuation: continue / retry / review / stop / escalate
5. risk: low / medium / high / critical score

## Security and minimization

Only an explicit metadata allowlist is sent. Raw source code, prompts,
credentials, environment values, documents, media, database rows and arbitrary
comment fields are excluded.

Jev cannot authorize:
- merge to main
- destructive mutation
- canonical DB writes
- source-media writes
- credential/provider changes
- payment/spend
- production promotion
- irreversible external actions

Those boundaries stay deterministic in TrafficLab Factory.

## Install

The project declares the official TypeSafe Python SDK:

`typesafe-sdk>=0.7.1,<0.8`

Install the repository environment normally:

`python -m pip install -e .`

Create a TypeSafe API key in the TypeSafe console and set it on the runtime
host as `TYPESAFE_API_KEY`. Never commit the key.

Once the environment variable is present, the normal watcher path begins live
Jev shadow evaluations automatically. No second feature flag is required.

## Manual smoke

`python scripts/jev_shadow_eval.py task.json --provider jev`

Expected live evidence:
- provider_status = OK
- model resolves to a Jev model
- typed route/review/blocker/continuation/risk values
- provider_metadata includes latency and token usage
- may_control_execution = false

## Promotion rule

Do not promote JEV from advisory into execution control from anecdotes.
Collect labeled outcomes and evaluate route accuracy, blocker accuracy,
continuation accuracy, needs-review Brier/FNR, and risk MAE. The first possible
promotion is reversible routing only. Protected gates remain deterministic.
