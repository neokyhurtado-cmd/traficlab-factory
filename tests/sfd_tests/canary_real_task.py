"""Real-task canary driver for SINGLE-FRONT-DOOR-01 (F6).

Runs the goal loop against the actually-dispatched real IA-VISION product
task #111 (the canary target). Produces an evidence artifact under
evidence/single_front_door/<run-id>/ that ASTRA can audit.

Does NOT mutate GitHub Issues, does NOT open PRs, does NOT touch canonical
DB. The adapter handles all of that inside an existing NEXO dispatch.

Usage:
    python -m tests.sfd_tests.canary_real_task --goal "..."
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from single_front_door.intake import run_goal_loop, REPO_ROOT  # noqa: E402

EVIDENCE_ROOT = REPO / "evidence" / "single_front_door"


def publish_evidence(goal_text: str, result: dict) -> Path:
    run_id = time.strftime("%Y%m%d_%H%M%S")
    out_dir = EVIDENCE_ROOT / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "goal.txt").write_text(goal_text, encoding="utf-8")
    (out_dir / "result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (out_dir / "evidence_block.md").write_text(
        result.get("evidence_block", ""),
        encoding="utf-8",
    )
    (out_dir / "notes.md").write_text(
        f"""# Canary run {run_id}

Goal: {goal_text!r}

This is the F6 POC run for SINGLE-FRONT-DOOR-01.
The adapter executed the F2 contract end-to-end and produced the evidence
block above. Real-product work (e.g. IA-VISION #111) still flows through the
existing NEXO directive watcher and per-task worktree — this control room
does not bypass them.
""",
        encoding="utf-8",
    )
    return out_dir


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: python -m tests.sfd_tests.canary_real_task <goal> [--live]",
              file=sys.stderr)
        return 2

    live = "--live" in argv
    goal_text = " ".join(a for a in argv[1:] if not a.startswith("--"))

    result = run_goal_loop(goal_text, dry_run=not live)
    out_dir = publish_evidence(goal_text, result)

    print(f"Wrote evidence: {out_dir}")
    print(f"Overall: {result.get('overall')}")
    print(f"Waiting reason: {result.get('waiting_reason') or 'NONE'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
