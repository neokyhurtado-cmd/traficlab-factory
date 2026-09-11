"""B3 adapter — wire between watcher/ORCH and the human_go_gate seam.

This module provides a documented *entry point* through which a Hermes
2.0 irreversible operation (merge a PR / activate Hermes 2.0) may be
invoked from code that lives in this repo. The contract is:

  Any caller that wants to merge or activate Hermes 2.0 must:
    1. Build a `candidate` dict (action/repo/pr_number/expected_head/
       owner_text/live_pr_head/owner_event_id).
    2. Call `run_or_bite(candidate, github_merge_callable)`.
    3. Receive the gate result; if `eligible=True` the operation
       proceeded; if `eligible=False` the operation did NOT happen and
       `reason` is the gate rejection reason.

  Direct invocation of `gh pr merge` or any other GitHub merge
  callable outside this seam is **bypass** and is detected by:
    - The seam's replay store (replay_detected) if attempted twice
      with the same (repo, pr, head, action).
    - The bites file (BITES_WITHOUT_GATE) when external monitoring
      or an explicit sentinel function calls `bite_record`.

The seam itself does NOT issue any GitHub calls. It is a guard that
takes whatever merge callable the caller provides and refuses to
invoke it unless the gate is eligible.

CRITICAL STATE NOTE — PRODUCTION_MERGE_PATH_NOT_PRESENT
======================================================

As of HEAD 6f1ffea, this adapter is a **library**. There is **no
production caller** in the directive_watcher/ORCH that invokes
`hermes2_merge_pr_19`, `run_or_bite`, or `pre_merge_check_and_call`.
The watcher pipeline (handler.py + default_execution) only:
  - reads comments,
  - parses directives,
  - dispatches sub-agent work in worktrees,
  - posts ACK / RESULT comments.

The reversible operations performed by the watcher (worktree
creation, branch push, comment posting) are not irreversible in the
B3 sense — they can be rolled back via `git reset` / `gh api -X DELETE`.

**Irreversible operations in Hermes 2.0** (merge PR, activate the
runtime) are reserved for the channel reserved to the human owner
(David). They are NOT performed by the watcher/ORCH. They happen
when David runs `gh pr merge <pr>` from his workstation, OR when a
future CLI (`scripts/hermes2_release.py`, not yet written) is
authorised by the gate.

When a future production merge caller is added, it MUST be wired as:

    # Pseudocode — not yet committed
    from directive_watcher.b3_adapter import run_or_bite
    result = run_or_bite(candidate, github_merge_callable)

and `github_merge_callable` MUST be the only function that shells
out to `gh pr merge` or the GitHub merge API.

VERIFICATION HELPERS
====================

This module exposes:
  - hermes2_merge_pr_19: convenience wrapper (requires secret_key)
  - run_or_bite:          low-level seam entry
  - bite_record:          records a BITES_WITHOUT_GATE event
  - init_gate:            initialises the gate instance

NO_DIRECT_MERGE_BYPASS posture
==============================

`bite_record` is observability-by-convention. The architectural
enforcement is:
  1. The seam is the **only** function in the seam module that calls
     a merge callable. Any other code path that wants to call a
     merge callable must import `run_or_bite` explicitly.
  2. The watcher/ORCH does not currently call any merge callable at
     all (see PRODUCTION_MERGE_PATH_NOT_PRESENT above).
  3. When a future merge callable is added, the production caller
     must thread through `run_or_bite` or the seam does not see it.

To upgrade this to a true non-bypassable enforcement, the merge
callable must be moved into a class that *cannot* be instantiated
without the seam (`__new__` raises if seam not initialised), or the
subprocess invocation must be wrapped in a runtime hook that
refuses non-gated calls. That upgrade is deferred to a future PR
once a production merge path is added.
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


# Documented entry-point. Wraps the seam so caller code does not need
# to know the gate implementation details.
def hermes2_merge_pr_19(github_merge_callable: Callable,
                        candidate: dict,
                        *,
                        secret_key: str | None = None) -> dict:
    """Sanctioned gate-protected merge entry-point.

    `candidate` MUST include:
      - action: "merge"
      - repo: owner/repo (e.g. "neokyhurtado-cmd/traficlab-factory")
      - pr_number: int
      - expected_head: exact 40-char SHA from David's HUMAN_GO_REAL
      - owner_text: full text from David (must contain "merge" verb
        and reference the exact repo/PR)
      - live_pr_head: live SHA at decision time (for stale-head denial)
      - owner_event_id: id of the signed event that authorizes this

    Returns the seam dict (`merged`, `fingerprint`, `gate_result`,
    optionally `merge_result`). If the gate is not eligible, `merged`
    is False and `reason` is the gate rejection reason.

    This function never bypasses the gate. To change the gate
    behavior, modify the seam.
    """
    gate = init_gate(secret_key=secret_key)
    return run_or_bite(candidate, github_merge_callable, gate=gate)


__all__ = ["hermes2_merge_pr_19", "run_or_bite", "bite_record", "init_gate"]
