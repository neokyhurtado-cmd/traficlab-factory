# ASTRA_CONTEXT_V1 — durable consultant context

This file is a compact durable snapshot, not a replacement for GitHub issue/PR/runtime evidence.

## Owner operating model

- David is the human owner and should not be used as a copy/paste transport.
- ChatGPT/Astra is the architect, consultant, adversarial reviewer and verifier.
- Hermes ORCH routes work; product workers execute.
- GitHub is durable truth for goals, issues, SHAs, decisions and evidence.
- Ordinary reversible technical decisions should be resolved by ORCH + Astra without interrupting David.
- HUMAN_GO_REAL remains required for merge to main, release/deploy, secrets/tokens,
  provider/model/global config, public exposure/network policy, destructive/nonrecoverable
  actions, paid external services/licenses/hardware and material unresolved product/science decisions.

## Product boundaries

- IA-VISION and SUINI are separate products/repos. Do not cross-write.
- Do not open lateral fronts automatically.
- Prefer one coherent macroturn with explicit gates, tests, evidence and STOP conditions.
- Tests PASS alone do not prove runtime/scientific acceptance.
- When evidence is missing, use NOT_PROVEN / NEEDS_MORE_EVIDENCE rather than guessing.

## Zero-handoff target

Desired loop:

David -> ChatGPT/Astra -> GitHub/ORCH -> Hermes
Hermes technical doubt -> Astra consultant -> structured decision -> Hermes continues
Hermes result -> Astra verifier -> fix/retest loop -> PASS/NOT_PROVEN
Only material HUMAN_GO_REAL returns to David.

Each consultation must also include the live task context (goal, gate, repo, SHAs, issue,
question, evidence, frozen decisions and forbidden scope). This snapshot alone is never
sufficient to authorize work.
