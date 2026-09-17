"""F6 LIVE natural-language canary for SINGLE-FRONT-DOOR-01 REAUDIT_FIX.

Runs the goal loop against four real goals through the F2 contract and
produces per-run evidence under evidence/single_front_door/<run-id>/.

Canaries (all REAL — go through the live host with a hermetic patch on
discover_runtime to avoid touching the cron):

  1. "Termina IA-VISION" — free-form, no issue #. Must parse as
     goal_mode=FREE_FORM and NOT call check_already_done.
  2. "¿qué falta?" — pure natural-language, no repo/issue.
  3. "lee Obsidian y continúa" — pure natural-language routing intent.
  4. "Sigue IA-VISION y llévame #111 hasta revisión" — issue-anchored
     but with the new semantics (ready-for-audit is transitional, ASTRA
     CHANGES_REQUIRED later re-opens). Same goal run twice for idempotency.

Usage:
    HERMES_HOME=C:/Users/david/AppData/Local/hermes \\
        python -m tests.sfd_tests.canary_natural_language_v2

Reads HERMES_HOME from env to construct the real matrix. If HERMES_HOME is
unset, falls back to the default `~/AppData/Local/hermes`.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))

from single_front_door.intake import (  # noqa: E402
    RealityMatrix,
    discover_runtime,
    run_goal_loop,
)
import single_front_door.intake as intake_mod  # noqa: E402

GOALS = [
    "Termina IA-VISION",
    "¿qué falta?",
    "lee Obsidian y continúa",
    "Sigue IA-VISION y llévame #111 hasta revisión",
]

EVIDENCE_ROOT = REPO / "evidence" / "single_front_door"


def _real_matrix() -> RealityMatrix:
    """Run discover_runtime ONCE for real (READ-ONLY) and return the matrix."""
    return discover_runtime()


def publish_evidence(goal_text: str, idx: int, result: dict) -> Path:
    """Write one evidence dir under evidence/single_front_door/."""
    run_id = time.strftime("%Y%m%d_%H%M%S") + f"_v2_{idx:02d}"
    out_dir = EVIDENCE_ROOT / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "goal.txt").write_text(goal_text + "\n", encoding="utf-8")
    (out_dir / "result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (out_dir / "evidence_block.md").write_text(
        result.get("evidence_block", ""),
        encoding="utf-8",
    )
    (out_dir / "notes.md").write_text(
        f"""# Natural-language canary run {run_id}

Goal: {goal_text!r}

Goal mode: {result.get('goal_mode', '?')}

This is a REAUDIT_FIX v2 canary run for SINGLE-FRONT-DOOR-01-CLOSEOUT-20260916-02.
It exercises the new free-form primary parsing and the corrected
`check_already_done` semantics (latest authoritative lifecycle state wins;
`ready-for-audit` is transitional; ASTRA CHANGES_REQUIRED re-opens).

`discover_runtime()` was patched to a snapshot of the host state observed
at run start so the canary stays hermetic without touching cron.
""",
        encoding="utf-8",
    )
    return out_dir


def main() -> int:
    print("=== Reality-sync snapshot ===")
    snap = _real_matrix()
    print(json.dumps(asdict(snap), indent=2, ensure_ascii=False))
    print()

    # Patch discover_runtime so the rest of the runs are hermetic.
    intake_mod.discover_runtime = lambda: snap  # type: ignore[assignment]

    print("=== Natural-language canary runs ===\n")
    out_dirs = []
    for i, goal in enumerate(GOALS, start=1):
        print(f"[{i}/{len(GOALS)}] {goal!r}")
        r = run_goal_loop(goal, dry_run=True)
        out_dir = publish_evidence(goal, i, r)
        print(
            f"  overall={r.get('overall')!r} "
            f"goal_mode={r.get('goal_mode')!r} "
            f"goal.repo={r['goal'].get('repo')!r} "
            f"goal.issue={r['goal'].get('issue')!r}"
        )
        if r.get("latest_event"):
            print(f"  latest_event={r['latest_event']}")
        print(f"  evidence={out_dir}")
        print()
        out_dirs.append(out_dir)

    # Idempotency: re-run #4 and confirm overall + evidence_block are stable.
    print("[idempotency] re-running #4")
    r1 = run_goal_loop(GOALS[3], dry_run=True)
    r2 = run_goal_loop(GOALS[3], dry_run=True)
    same_overall = r1["overall"] == r2["overall"]
    same_evidence = r1.get("evidence_block", "") == r2.get("evidence_block", "")
    print(f"  overall equal: {same_overall}")
    print(f"  evidence_block equal: {same_evidence}")
    print()

    summary = {
        "snapshot": asdict(snap),
        "canary_results": [
            {"goal": g, "out_dir": str(d)}
            for g, d in zip(GOALS, out_dirs)
        ],
        "idempotency": {
            "same_overall": same_overall,
            "same_evidence_block": same_evidence,
        },
    }
    summary_path = EVIDENCE_ROOT / (
        "summary_v2_" + time.strftime("%Y%m%d_%H%M%S") + ".json"
    )
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Summary written: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
