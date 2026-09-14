# INTERNAL_CONSULT v1

`INTERNAL_CONSULT` is a Hermes-native consultation protocol, not a second agent runtime.

Hermes already owns parallel child execution through `delegate_task`. The project-local skill at `.hermes/skills/internal-consult/SKILL.md` tells the parent how to launch four isolated reviewers, how to structure their outputs, and when to escalate. The machine-readable policy is `orchestrator/contracts/internal_consult_v1.yaml`.

## Execution shape

```text
Hermes parent
  -> delegate_task batch
     -> ARCHITECT
     -> EVIDENCE
     -> RED_TEAM
     -> TEST_ORACLE
  -> CONSULT_DECISION
     -> AUTO_GO / AUTO_REPLAN / BLOCK
     -> SECOND_ROUND when evidence disagrees
     -> ASTRA only for critical/ambiguous gates
     -> DAVID only for genuine human-authority gates
```

First-round reviewers receive the same factual bundle but not each other's conclusions. Consultation is read-only. The parent reuses its existing provider configuration; this contract adds no API credential and changes no provider.

## Non-negotiable rule

A reproducible counterexample is evidence, not a vote. It cannot be overruled by a majority of `GO` reviews.

## Identity rule

The account that transports a GitHub message is not automatically the decision actor. Decision envelopes correlate actor claims with `QUERY_ID`, repository, issue/PR, commit SHA and available provenance. Unverified provenance produces `ACTOR_UNVERIFIED` and no privileged authority.

## Activation

Hermes supports trusted project-local skills under `.hermes/skills`. In a trusted workspace this exposes `/internal-consult`; natural-language requests can load the same skill. No `config.yaml`, `.env`, gateway, channel or provider edit is part of this implementation.

## Acceptance

The contract is accepted only if repository tests prove:

- four independent role definitions exist;
- quorum is at least three;
- counterexample precedence is above consensus;
- reversible LOW/MEDIUM consensus can `AUTO_GO`;
- HIGH/CRITICAL and irreversible gates escalate to ASTRA;
- explicit human gates escalate to DAVID;
- transport identity is not treated as decision identity;
- consultation adds no provider secret or new provider configuration.
