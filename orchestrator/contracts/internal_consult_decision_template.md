[CONSULT_DECISION:v1]

QUERY_ID = <same query id>
ACTION = AUTO_GO | AUTO_REPLAN | BLOCK | SECOND_ROUND | ESCALATE_ASTRA | ESCALATE_DAVID
REVIEW_ROLES = <validated independent roles>
COUNTEREXAMPLE = NONE | <role + reproducible evidence>
MAX_RISK = LOW | MEDIUM | HIGH | CRITICAL
REASON = <concise evidence-based reason>
NEXT_SAFE_ACTION = <bounded next action>

TRANSPORT_ACTOR = <technical publisher>
DECISION_ACTOR = HERMES | JUPITER | ASTRA | DAVID | MINIMAX_CONSULTANT | ACTOR_UNVERIFIED
PROVENANCE = <available verified provenance>
REPOSITORY = <owner/repo>
ISSUE_OR_PR = <number-or-none>
COMMIT_SHA = <exact sha-or-none>
