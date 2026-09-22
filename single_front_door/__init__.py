"""single_front_door — Goal-intake adapter for SINGLE-FRONT-DOOR-01.

Public surface:
    - discover_runtime() → RealityMatrix   (F0 read-only inventory)
    - Goal.parse(text)  → Goal             (free-form goal parser)
    - check_already_done(repo, issue)      (F2 idempotency gate)
    - run_goal_loop(text, dry_run=...)     (F2 end-to-end driver)
    - render_evidence_block(...)          (F4/F6 required evidence)
"""

from .intake import (  # noqa: F401
    RealityMatrix,
    Goal,
    discover_runtime,
    check_already_done,
    render_evidence_block,
    run_goal_loop,
    REPO_ROOT,
)
