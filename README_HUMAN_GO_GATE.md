# HUMAN_GO_GATE_V2

Deterministic guard that prevents false-positive "GO" instructions from triggering
irreversible actions (merges to main, releases, deploys, secret writes).

## Why

During the P0 program (traficlab-factory #14), the agent received 3 false positives:
"go", "a", "si contina que mamon". None caused damage only because the agent
repeatedly asked for clarification. HUMAN_GO_GATE_V2 turns that clarification
into a deterministic policy that future agents cannot bypass.

## Contract

`evaluate(candidate, current_owner_text=None) -> dict`

`candidate` requires:
- `action`: one of `merge`, `release`, `deploy`, `secret_write`
- `repo`: `owner/name`
- `pr_number`: int
- `expected_head`: 40-char hex SHA
- `owner_text`: full text from owner where the authorization was given
- `live_pr_head`: optional, live SHA at decision time (enables stale-head denial)
- `current_owner_text`: optional, latest message from owner (defense-in-depth)

`current_owner_text` (if provided) must ALSO authorize the same target — protects
against carrying forward instructions from past tickets.

## Rejection reasons

- `action_not_authorized_for_gate`
- `repo_format_invalid`
- `expected_head_not_sha256_40hex`
- `owner_text_empty`
- `owner_text_target_mismatch` — owner_text does not name the same repo + PR number
- `no_authorization_verb` — target line lacks an authorization verb
- `current_owner_text_unrelated_or_stale` — latest owner message doesn't authorize this target
- `replay_detected` — same (repo, pr_number, expected_head) used twice
- `stale_head_detected` — live_pr_head ≠ expected_head

## Usage

```python
from human_go_gate_v2 import HUMAN_GO_GATE_V2

gate = HUMAN_GO_GATE_V2()
result = gate.evaluate(
    candidate={
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "75cd4f085a010a2114daee5e498afc3fcc86837d",
        "owner_text": "apruebo PR#5 merge de traficlab-factory#5",
        "live_pr_head": "75cd4f085a010a2114daee5e498afc3fcc86837d",
    },
    current_owner_text="apruebo los dos por fa",  # latest message
)
assert result["eligible"] is True
```

## Tests

`python tests/test_human_go_gate_v2.py`

14 adversarial tests covering: informal verbs, missing target, replay, stale head,
bad SHA, bad action, empty owner_text, current_owner_text unrelated, etc.

## Out of scope (deliberate)

This gate does NOT execute merges. It only returns `eligible: bool`. The actual
merge call is the caller's responsibility and must remain gated by a separate
HUMAN_GO_REAL_V2 confirm from David.
