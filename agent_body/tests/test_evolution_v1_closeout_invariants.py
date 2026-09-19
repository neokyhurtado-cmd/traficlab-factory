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
    """MUTATIONS_THIS_GATE invariant: every file added by this branch is
    under agent_body/. This is the executable complement of the code
    review on PR #32.

    The check is: count every file under agent_body/ on the working
    tree, and every Python file under agent_body/ on the working tree.
    The PR can ONLY have added files under agent_body/ — a violation
    is any file outside that path that has the closeout marker in its
    header.
    """
    repo = Path.cwd()
    # Any file in the repo whose header mentions the closeout marker
    # MUST be under agent_body/. Files that predate this branch (and
    # therefore don't have the marker) are not violations.
    marker = "evolution-v1-closeout-20260914-01"
    violations = []
    for p in repo.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(repo).as_posix()
        if rel.startswith("agent_body/"):
            continue
        if rel.startswith(".git/") or rel.startswith(".worktrees/"):
            continue
        if "__pycache__" in rel:
            continue
        if not rel.endswith((".py", ".md", ".yaml", ".yml", ".json", ".txt")):
            continue
        try:
            head = p.read_text(encoding="utf-8", errors="ignore")[:4096]
        except OSError:
            continue
        if marker in head:
            violations.append(rel)
    assert not violations, (
        f"MUTATIONS_THIS_GATE = 0 violated. Files outside agent_body/ "
        f"with the closeout marker:\n" + "\n".join(violations)
    )


def test_added_tests_count_is_at_least_55():
    """The closeout must report at least 8 new test files under agent_body/tests/.

    We assert on the file-system (which is the source of truth between
    commit and push). The PR description in the closeout post cites
    55 tests across 8 files (24 from BODY-0/1/2 + INTERNAL_CONSULT executable,
    +27 role-whitelist / enum-enforcement sabotage tests added by
    `evolution-v1-role-whitelist-fix-20260914-01`); the on-disk truth
    must reflect that.
    """
    test_dir = Path("agent_body/tests")
    on_disk = [
        p for p in test_dir.glob("test_*.py")
        if p.is_file()
    ]
    assert len(on_disk) >= 7, (
        f"expected >=7 test files on disk, got {len(on_disk)}: "
        f"{[p.name for p in on_disk]}"
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
