"""B3 adapter — wire between watcher/ORCH and the human_go_gate seam.

This module is the documented **only** path through which a Hermes 2.0
irreversible operation (merge PR #19 / activate Hermes 2.0) may be
invoked from the watcher/ORCH side. The contract is:

  Any caller that wants to merge or activate Hermes 2.0 must:
    1. Build a `candidate` dict (action/repo/pr_number/expected_head/
       owner_text/live_pr_head/owner_event_id).
    2. Call `run_or_bite(candidate, github_merge_callable)`.
    3. Receive the gate result; if `merged=True` the operation succeeded;
       if `eligible=False` or `merged=False`, the operation did NOT
       happen and the gate reason is in `reason`.

  Direct invocation of `gh pr merge` or any other GitHub merge callable
  outside this seam is **bypass** and will be detected by:
    - The seam's own replay store (replay_detected) if attempted
      twice with the same (repo, pr, head, action).
    - The bites file (BITES_WITHOUT_GATE) if external monitoring
      detects an unsanctioned call.

The seam itself does NOT issue any GitHub calls. The actual GitHub
client is `directive_watcher.gh_client.GHClient.merge_pr`, which is
passed as the `github_merge_callable` to the seam.
"""
from __future__ import annotations

import os
import sys
from typing import Any, Callable

# Make the gate importable
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))  # repo root
_GATE = os.path.join(_REPO, "p1_human_go_gate")
_SRC = os.path.join(_GATE, "src")
for p in (_SRC, _GATE):
    if p not in sys.path:
        sys.path.insert(0, p)

from seam import run_or_bite, bite_record, init_gate  # noqa: E402


# Documented entry-point. Wraps the seam so watcher code does not need
# to know the gate implementation details.
def hermes2_merge_pr_19(github_merge_callable: Callable,
                        candidate: dict,
                        *,
                        secret_key: str | None = None) -> dict:
    """The ONLY sanctioned way to merge PR #19 from the watcher.

    `candidate` MUST include:
      - action: "merge"
      - repo: "neokyhurtado-cmd/traficlab-factory"
      - pr_number: 19
      - expected_head: exact 40-char SHA from David's HUMAN_GO_REAL
      - owner_text: full text from David (must contain "merge" verb
        and reference the exact repo/PR)
      - live_pr_head: live SHA at decision time (for stale-head denial)
      - owner_event_id: id of the signed event that authorizes this

    Returns a dict with `merged`, `fingerprint`, `gate_result`,
    optionally `merge_result`. If the gate is not eligible, `merged`
    is False and `reason` is the gate rejection reason.

    This function never bypasses the gate. If you need a different
    gate behavior, change the seam, not this function.
    """
    gate = init_gate(secret_key=secret_key)
    return run_or_bite(candidate, github_merge_callable, gate=gate)


__all__ = ["hermes2_merge_pr_19", "run_or_bite", "bite_record", "init_gate"]
