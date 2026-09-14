[INTERNAL_CONSULT_QUERY:v1]

QUERY_ID = <stable-id>
REPOSITORY = <owner/repo>
ISSUE_OR_PR = <number-or-none>
COMMIT_SHA = <exact-sha-or-none>
QUESTION = <bounded technical decision>
REVERSIBLE = YES | NO
CRITICAL_GATE = YES | NO
HUMAN_GATE = YES | NO
AUTHORITY_BOUNDARIES = <what reviewers may not decide>
EVIDENCE_POINTERS = <verified paths, commits, tests, logs>
CONSTRAINTS = <bounded constraints>

First round: launch ARCHITECT, EVIDENCE, RED_TEAM and TEST_ORACLE independently via the native Hermes delegation batch described in the `internal-consult` skill. Consultation is read-only.
