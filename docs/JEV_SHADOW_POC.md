# Jev Shadow Decision Plane POC

Status: SHADOW ONLY
Owner-facing agent: HERMES
Owner-facing visual surface: PANORAMA

## Purpose

Test whether TypeSafe AI Jev can replace ad-hoc probabilistic routing/gating
inside HERMES without becoming another agent or control plane.

Jev is not an executor, reviewer-of-record, scheduler, truth source or
protected-action authority.

## Five decisions

One shared minimal state is evaluated against:

1. route: code / research / review / ops / other
2. needs_review: boolean probability
3. blocker: none / missing_data / permission / provider / scientific / runtime / other
4. continuation: continue / retry / review / stop / escalate
5. risk: ordered score from low to critical

## Data minimization

Only a fixed metadata allowlist is sent. The POC never forwards arbitrary
fields such as raw code, prompts, credentials, environment values, client
documents, media, DB rows or file contents.

The live Vercel bridge requests Zero Data Retention per evaluation.

## Protected gates stay deterministic

Jev cannot authorize:

- merge to main
- destructive mutation
- canonical DB writes
- source-media writes
- secrets/credentials changes
- provider/license changes
- payment/spend
- production promotion
- irreversible external actions

If a protected flag is present, hard_gate_override=true regardless of Jev.

## Running with no provider

Default mode makes no network call:

    python scripts/jev_shadow_eval.py task.json

This returns provider_status=DISABLED and never blocks Hermes.

## Optional live shadow via Vercel AI Gateway

Prerequisites are intentionally not auto-installed or auto-configured:

- explicit operator/provider authorization
- AI_GATEWAY_API_KEY in environment only
- Node available
- install the pinned optional bridge dependency in jev_shadow/node

Then:

    python scripts/jev_shadow_eval.py task.json --provider jev

The API key is inherited by the bridge process and is not serialized into the
task state or evidence by this implementation.

## Promotion criteria

Do not grant Jev authority from anecdotes.

Collect labeled observations and compare with actual HERMES/reviewer outcomes.
At minimum inspect:

- route accuracy
- blocker accuracy
- continuation accuracy
- needs-review Brier score
- needs-review false-negative rate
- risk MAE
- latency and cost

First possible promotion, after evidence, is safe reversible routing only.
Protected gates remain deterministic permanently.
