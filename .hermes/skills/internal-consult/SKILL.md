---
name: internal-consult
description: Parallel independent review before external escalation
version: 1.0.0
metadata:
  hermes:
    tags: [delegation, review, autonomy]
---

# Internal Consult

## When to Use
Use this skill when Hermes has a material technical uncertainty, proposed integration decision, architecture choice, evidence dispute, or merge recommendation that does not yet require human authority.

Do not use it for a deterministic single-tool lookup or a trivial reversible edit whose answer is already mechanically verified.

## Procedure

### 1. Build one factual consultation bundle
Create a compact bundle containing only facts needed by every reviewer:

- `QUERY_ID`
- repository and issue/PR when applicable
- exact commit SHA or state being reviewed
- question to decide
- constraints and authority boundaries
- evidence pointers already verified
- whether the proposed action is reversible
- whether the gate is critical
- whether genuine human authority is required

Never include another reviewer's answer in the first-round bundle.

### 2. Spawn independent reviewers in one native delegation batch
Use Hermes `delegate_task(tasks=[...])` so the reviews run in isolated child contexts. Reuse the parent's existing provider configuration; never copy, print, request, or create API credentials for consultation.

Launch these four roles when capacity permits:

1. `ARCHITECT` — checks architecture, boundaries, coupling, reversibility and simpler alternatives.
2. `EVIDENCE` — checks whether claims are actually supported by tests, commits, logs and authoritative sources.
3. `RED_TEAM` — actively searches for a concrete counterexample or failure mode. A reproducible counterexample is evidence, not a vote.
4. `TEST_ORACLE` — designs or inspects the smallest decisive test that can falsify the proposed conclusion.

Each child is `READ_ONLY` for the consultation. It may inspect files, commits, tests and public information but must not mutate repositories, configuration, runtime, channels or external state.

Every child receives the same factual bundle plus only its own role instruction. First-round children must not see each other's conclusions.

### 3. Require structured child output
Each reviewer returns exactly this semantic envelope:

```text
[MINIMAX_REVIEW:<ROLE>:v1]
QUERY_ID = <same query id>
DECISION = GO | REPLAN | BLOCK | ESCALATE
RISK = LOW | MEDIUM | HIGH | CRITICAL
CONFIDENCE = <0.0..1.0>
COUNTEREXAMPLE = <none or concise reproducible counterexample>
EVIDENCE = <pointers, tests, SHAs or observations>
NOTES = <concise explanation>
```

Reject a review whose `QUERY_ID`, repository, issue/PR or SHA does not match the consultation bundle.

### 4. Synthesize by evidence, not majority
Apply these rules in order:

1. `HUMAN_GATE = YES` -> `ESCALATE_DAVID`.
2. Any reproducible counterexample -> `AUTO_REPLAN` if reversible; otherwise `ESCALATE_ASTRA`.
3. Critical gate, irreversible action, or HIGH/CRITICAL risk -> `ESCALATE_ASTRA`.
4. Any verified material blocker -> `BLOCK`.
5. Fewer than three independent valid roles -> `SECOND_ROUND`.
6. Material disagreement between valid reviewers -> one targeted `SECOND_ROUND` with fresh children.
7. At least three valid independent reviews, no counterexample, all agree `GO`, risk <= MEDIUM, and action reversible -> `AUTO_GO`.
8. At least three valid independent reviews all agree `REPLAN`, reversible -> `AUTO_REPLAN`.
9. Persistent ambiguity after the second round -> `ESCALATE_ASTRA`.

Never let three optimistic votes overrule one reproducible counterexample.

### 5. Separate transport identity from decision identity
A GitHub username is not sufficient proof of who made a decision.

Maintain these distinct fields:

```text
TRANSPORT_ACTOR
DECISION_ACTOR
PROVENANCE
QUERY_ID
REPOSITORY
ISSUE_OR_PR
COMMIT_SHA
```

`DECISION_ACTOR` may be `DAVID`, `ASTRA`, `HERMES`, `JUPITER`, or `MINIMAX_CONSULTANT`.

Recognized message families are:

```text
[INTERNAL_CONSULT_QUERY:v1]
[MINIMAX_REVIEW:ARCHITECT:v1]
[MINIMAX_REVIEW:EVIDENCE:v1]
[MINIMAX_REVIEW:RED_TEAM:v1]
[MINIMAX_REVIEW:TEST_ORACLE:v1]
[CONSULT_DECISION:v1]
[ASTRA_QUERY:v1]
[ASTRA_DECISION:v1]
[DAVID_DECISION:v1]
```

A marker alone is not authentication. Verify it against the expected query correlation, repository/issue/PR/SHA and available transport provenance. If provenance is insufficient or inconsistent, set `DECISION_ACTOR = ACTOR_UNVERIFIED` and do not grant privileged authority.

### 6. Emit the parent decision
The parent emits:

```text
[CONSULT_DECISION:v1]
QUERY_ID =
ACTION = AUTO_GO | AUTO_REPLAN | BLOCK | SECOND_ROUND | ESCALATE_ASTRA | ESCALATE_DAVID
REVIEW_ROLES =
COUNTEREXAMPLE = NONE | <role + evidence>
MAX_RISK =
REASON =
NEXT_SAFE_ACTION =
```

For `ESCALATE_ASTRA`, publish or route an `[ASTRA_QUERY:v1]` carrying the verified evidence bundle, not the agents' hidden reasoning.

For `ESCALATE_DAVID`, ask David only for the concrete human-authority decision; do not send routine technical uncertainty to him.

## Pitfalls

- Same-model reviewers can share the same blind spot; independence of context does not create model diversity.
- Do not expose one review to another before first-round completion.
- Do not infer `DECISION_ACTOR` only from the GitHub account that transported a message.
- Do not ask subagents to mutate the same files during consultation.
- Do not treat confidence scores as evidence.
- Do not create a second scheduler, provider configuration, secret store or model-routing system for this skill.

## Verification

A valid implementation demonstrates all of these cases:

- three or more independent GO reviews + LOW/MEDIUM + reversible -> `AUTO_GO`;
- one reproducible counterexample overrides GO consensus;
- HIGH/CRITICAL or irreversible -> `ESCALATE_ASTRA`;
- explicit human gate -> `ESCALATE_DAVID`;
- insufficient quorum or disagreement -> `SECOND_ROUND`;
- mismatched query/SHA/provenance -> rejected or `ACTOR_UNVERIFIED`;
- no provider/API credential is added to repository content.
