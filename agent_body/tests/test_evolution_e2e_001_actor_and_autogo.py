"""EVOLUTION-E2E-001 (cont.): ACTOR_UNVERIFIED detection + AUTO_GO synthesis.

Per directive `evolution-v1-closeout-20260914-01`:

  - A review with a tampered COMMIT_SHA that does not match the consultation
    bundle must produce TEST_ORACLE=REJECTED and DECISION_ACTOR=ACTOR_UNVERIFIED.
    Such a review MUST NOT count as a valid vote.
  - Four independent valid reviews with no counterexample and all GO on a
    reversible action MUST yield AUTO_GO.

These tests are executable (not source-text grep) — they exercise the
synthesis oracle directly, so the test is the spec.
"""
from __future__ import annotations

import pytest


# ACTOR_UNVERIFIED -----------------------------------------------------------


def _bundle():
    """Canonical consultation bundle for these tests."""
    return {
        "QUERY_ID": "evolution_v1_closeout_20260914_01",
        "REPOSITORY": "neokyhurtado-cmd/traficlab-factory",
        "ISSUE_OR_PR": "#27",
        "COMMIT_SHA": "7225d3e383f268b3b7032294ac6ef0c76d5c5d62",
        "REVERSIBLE": True,
        "CRITICAL_GATE": False,
        "HUMAN_GATE": False,
    }


def test_tampered_commit_sha_review_is_rejected_as_actor_unverified():
    """A review whose COMMIT_SHA does not match the bundle MUST be rejected.

    Per orchestrator/contracts/internal_consult_v1.yaml#identity.required_correlation_fields,
    COMMIT_SHA is one of the four mandatory correlation fields. Mismatch
    implies the reviewer's marker cannot be tied to the actual consultation
    bundle → DECISION_ACTOR = ACTOR_UNVERIFIED → the review cannot vote.
    """
    from agent_body.internal_consult_synth import synthesize

    bundle = _bundle()
    tampered_review = {
        "role": "TEST_ORACLE",
        "decision": "GO",
        "risk": "LOW",
        "confidence": 0.99,
        "counterexample": None,
        "evidence": ["tests/agent_body/checkpoint_store.py:1-200"],
        "query_id": bundle["QUERY_ID"],
        "repository": bundle["REPOSITORY"],
        "issue_or_pr": bundle["ISSUE_OR_PR"],
        "commit_sha": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",  # tampered
    }

    decision = synthesize(bundle, reviews=[tampered_review])
    assert decision["action"] != "AUTO_GO"
    # The synthesized decision must surface the rejection reason.
    assert decision["rejected_reviews"] == ["TEST_ORACLE"]
    assert decision["actor_unverified"] == ["TEST_ORACLE"]
    # With no other valid votes, quorum is insufficient → SECOND_ROUND.
    assert decision["action"] == "SECOND_ROUND"


def test_tampered_query_id_review_is_rejected_as_actor_unverified():
    """Same shape as COMMIT_SHA — QUERY_ID mismatch → ACTOR_UNVERIFIED."""
    from agent_body.internal_consult_synth import synthesize

    bundle = _bundle()
    wrong_query_review = {
        "role": "ARCHITECT",
        "decision": "GO",
        "risk": "LOW",
        "confidence": 0.95,
        "counterexample": None,
        "evidence": ["agent_body/SKILL.md"],
        "query_id": "some_other_query_20260913",
        "repository": bundle["REPOSITORY"],
        "issue_or_pr": bundle["ISSUE_OR_PR"],
        "commit_sha": bundle["COMMIT_SHA"],
    }
    decision = synthesize(bundle, reviews=[wrong_query_review])
    assert decision["action"] == "SECOND_ROUND"
    assert "ARCHITECT" in decision["actor_unverified"]


# AUTO_GO --------------------------------------------------------------------


def _valid_review(role, *, risk="LOW"):
    b = _bundle()
    return {
        "role": role,
        "decision": "GO",
        "risk": risk,
        "confidence": 0.9,
        "counterexample": None,
        "evidence": ["tests/agent_body/"],
        "query_id": b["QUERY_ID"],
        "repository": b["REPOSITORY"],
        "issue_or_pr": b["ISSUE_OR_PR"],
        "commit_sha": b["COMMIT_SHA"],
    }


def test_four_independent_go_reviews_no_counterexample_yields_auto_go():
    """The 4 mandated roles → all GO → reversible → AUTO_GO.

    Per orchestrator/contracts/internal_consult_v1.yaml precedence:
    human_gate=false, no counterexample, critical=false, no HIGH/CRITICAL
    risk, no BLOCK, quorum >= 3, all decisions == GO, reversible → AUTO_GO.
    """
    from agent_body.internal_consult_synth import synthesize

    reviews = [_valid_review(role) for role in ("ARCHITECT", "EVIDENCE", "RED_TEAM", "TEST_ORACLE")]
    decision = synthesize(_bundle(), reviews=reviews)
    assert decision["action"] == "AUTO_GO"
    assert decision["max_risk"] == "LOW"
    assert decision["counterexample"] == "NONE"
    assert set(decision["review_roles"]) == {"ARCHITECT", "EVIDENCE", "RED_TEAM", "TEST_ORACLE"}


def test_single_counterexample_overrides_three_optimistic_gos():
    """One reproducible counterexample → AUTO_REPLAN (reversible)."""
    from agent_body.internal_consult_synth import synthesize

    bundle = _bundle()
    reviews = [_valid_review(role) for role in ("ARCHITECT", "EVIDENCE", "TEST_ORACLE")]
    red_team = _valid_review("RED_TEAM")
    red_team["counterexample"] = "tests fail: test_x fails on edge case Y (reproducer in evidence)"
    reviews.append(red_team)

    decision = synthesize(bundle, reviews=reviews)
    assert decision["action"] == "AUTO_REPLAN"
    assert "RED_TEAM" in decision["counterexample"]
