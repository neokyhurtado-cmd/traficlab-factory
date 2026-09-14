# INTERNAL_CONSULT v1 acceptance gate

PASS requires all repository tests green plus evidence that:

- `.hermes/skills/internal-consult/SKILL.md` is discoverable as a trusted project-local Hermes skill;
- the skill uses native `delegate_task` parallel child execution;
- roles ARCHITECT, EVIDENCE, RED_TEAM and TEST_ORACLE are defined;
- quorum is at least three independent valid reviews;
- counterexample precedence is above consensus;
- actor correlation includes QUERY_ID, repository, issue/PR and commit SHA;
- no new provider credential or provider switch is introduced.

Runtime activation on a host remains fail-closed if that workspace is not trusted for project-local skills; trust policy must not be bypassed by this repository.
