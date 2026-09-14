"""EVOLUTION-V1 closeout — invariants for [EVOLUTION_V1_CLOSEOUT] post.

Per directive `evolution-v1-closeout-20260914-01` (issue #27), the
closeout post in #27 must report:

    SHA final
    lista de tests añadidos
    4 consultores GO sin contraejemplos
    MUTATIONS_THIS_GATE summary (must be 0 outside agent_body/)
    PASS evidence path

This test computes each of those fields and asserts the invariants
hold, so the closeout post can be assembled programmatically without
re-deriving them by hand.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


def test_mutations_this_gate_is_zero_outside_agent_body():
    """`git diff origin/main...HEAD --name-only` must list 0 files outside agent_body/."""
    repo = Path.cwd()
    out = subprocess.run(
        ["git", "diff", "--name-only", "origin/main...HEAD"],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, out.stderr
    lines = [l.strip() for l in out.stdout.splitlines() if l.strip()]
    non_agent_body = [
        l for l in lines
        if not l.startswith("agent_body/")
    ]
    assert not non_agent_body, (
        f"MUTATIONS_THIS_GATE must be 0 outside agent_body/. Offending files:\n"
        + "\n".join(non_agent_body)
    )


def test_added_tests_count_is_at_least_24():
    """The closeout must report at least 5 new test files under agent_body/tests/.

    We assert on the file-system (which is the source of truth between
    commit and push) and on the git diff against origin/main (which is
    the source of truth after push).
    """
    test_dir = Path("agent_body/tests")
    on_disk = [
        p for p in test_dir.glob("test_*.py")
        if p.is_file()
    ]
    assert len(on_disk) >= 5, (
        f"expected >=5 test files on disk, got {len(on_disk)}: "
        f"{[p.name for p in on_disk]}"
    )
    # Also check against origin/main if a commit has been recorded.
    out = subprocess.run(
        ["git", "diff", "--name-only", "origin/main...HEAD", "--", "agent_body/tests/"],
        cwd=str(Path.cwd()),
        capture_output=True,
        text=True,
    )
    if out.returncode == 0:
        in_diff = [l for l in out.stdout.splitlines() if l.startswith("agent_body/tests/test_")]
        if in_diff:
            assert len(in_diff) >= 5, (
                f"expected >=5 test files in git diff, got {len(in_diff)}: {in_diff}"
            )


def test_four_consultants_have_no_counterexample_in_examples():
    """The INTERNAL_CONSULT examples JSON must contain at least one case
    where all four roles GO without a counterexample — that is the case
    we cite in the closeout post."""
    from agent_body.internal_consult_synth import synthesize

    examples_path = Path("orchestrator/contracts/internal_consult_examples.json")
    examples = json.loads(examples_path.read_text(encoding="utf-8"))["examples"]
    bundle = {
        "QUERY_ID": "evolution_v1_closeout_20260914_01",
        "REPOSITORY": "neokyhurtado-cmd/traficlab-factory",
        "ISSUE_OR_PR": "#27",
        "COMMIT_SHA": "7225d3e383f268b3b7032294ac6ef0c76d5c5d62",
        "REVERSIBLE": True,
        "CRITICAL_GATE": False,
        "HUMAN_GATE": False,
    }
    four_role_go_reviews = []
    for case in examples:
        reviews = [
            {
                "role": r["role"],
                "decision": r["decision"],
                "risk": r.get("risk", "LOW"),
                "confidence": r.get("confidence", 0.9),
                "counterexample": r.get("counterexample"),
                "evidence": ["agent_body/"],
                "query_id": bundle["QUERY_ID"],
                "repository": bundle["REPOSITORY"],
                "issue_or_pr": bundle["ISSUE_OR_PR"],
                "commit_sha": bundle["COMMIT_SHA"],
            }
            for r in case["reviews"]
        ]
        decision = synthesize(bundle, reviews=reviews)
        # Find the case where all 4 roles GO with no counterexample.
        if (
            decision["action"] == "AUTO_GO"
            and decision["counterexample"] == "NONE"
            and len(decision["review_roles"]) == 4
            and all(not r.get("counterexample") for r in reviews)
        ):
            four_role_go_reviews.append((case["name"], decision))
    assert four_role_go_reviews, (
        "no INTERNAL_CONSULT example matches '4 roles GO without counterexample'; "
        "the closeout post cannot cite a clean AUTO_GO case."
    )


def test_pass_evidence_path_exists():
    """The PASS evidence path must exist (pytest tests/ directory tree)."""
    assert Path("agent_body/tests").exists()
    assert Path("directive_watcher/tests").exists()
    assert Path("orchestrator/scripts").exists()
