# ASTRA CONSULT LOOP V1

Hermes gets a first-class `ask_astra` tool through the `astra-consult` plugin plus a bounded system-prompt policy: before asking David an ordinary technical question or stopping on a reversible ambiguity, consult Astra first.

The tool passes an `ASTRA_CONSULT_REQUEST_V1` envelope to `scripts/astra_consult.py`, which returns exactly one machine-readable decision:

`AUTO_GO | AUTO_REPLAN | NEEDS_MORE_EVIDENCE | BLOCKED_EXTERNAL | HUMAN_GO_REAL`

The bridge can fetch the source GitHub issue, redacts common secret shapes before sending context externally, calls the OpenAI Responses API, validates the returned decision envelope and applies a deterministic HUMAN_GO guard after the model response. With an issue number, the plugin posts the decision back to the same GitHub issue as durable evidence.

## Why a Hermes plugin

Hermes officially supports general plugins that register model-facing tools and bounded system prompt sections. This keeps the consultation policy inside the agent runtime instead of depending on copy/paste or a human remembering to invoke a script.

## Runtime files

- `plugins/astra-consult/plugin.yaml` — plugin manifest; requires `OPENAI_API_KEY`.
- `plugins/astra-consult/__init__.py` — registers `ask_astra` and the zero-handoff policy.
- `scripts/consult_contract.py` — typed request/decision contract.
- `scripts/astra_consult.py` — OpenAI Responses API adapter + GitHub context/evidence.
- `context/ASTRA_CONTEXT_V1.md` — compact durable owner/product operating context.
- `scripts/test_astra_consult.py` and `scripts/test_astra_plugin.py` — deterministic regressions.

## Automatic loop

1. Hermes verifies facts directly from repo/runtime first.
2. If a technical judgment is still unresolved, the system policy tells Hermes to call `ask_astra` before asking David.
3. The request carries current project, goal, gate, repo, issue, SHAs, question, evidence, frozen decisions, forbidden scope and compact conversation/owner context.
4. `AUTO_GO`: continue.
5. `AUTO_REPLAN`: adopt the plan and continue.
6. `NEEDS_MORE_EVIDENCE`: collect only the missing evidence, then consult again.
7. `BLOCKED_EXTERNAL`: stop only that dependency.
8. `HUMAN_GO_REAL`: surface one concise owner decision to David.
9. Important decisions are persisted to GitHub.

## Safety boundary

A model response cannot override deterministic owner gates. Merge-to-main, deploy/release, secrets/tokens, provider/model/global config, public exposure, destructive actions, payments/licenses/hardware remain `HUMAN_GO_REAL` even if the model emits `AUTO_GO`.

No credential is stored in this repository. A missing API key, API outage, missing bridge script or malformed model response fails closed.

## Activation boundary

Repository implementation does not silently mutate the live Hermes profile. Physical activation requires HERMES-ORCH to:

1. sync the approved commit into its controlled `~/.hermes/profiles/orchestrator/` files;
2. install/enable the reviewed `astra-consult` plugin under the trusted user plugin directory;
3. supply `OPENAI_API_KEY` through the approved secret mechanism (never GitHub);
4. restart/reload Hermes as required by the installed version;
5. run the full orchestrator test suite;
6. prove one read-only technical consultation canary;
7. prove one owner-only adversarial canary returns `HUMAN_GO_REAL`;
8. prove result evidence returns to GitHub with `HUMAN_COPY_PASTE_REQUIRED = NO`.

Until those physical gates pass, classify `ASTRA_CONSULT_LOOP = IMPLEMENTED_NOT_ACTIVATED`, not OPERATIONAL.
