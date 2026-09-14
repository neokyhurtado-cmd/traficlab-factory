"""Sabotage tests for canonical role/whitelist and decision/risk enum enforcement.

Per directive `evolution-v1-role-whitelist-fix-20260914-01` (issue #27):

  - Enforce canonical review_roles on every synth path (both envelope-parsed
    and direct-dict paths).
  - Fail closed on missing required correlation fields.
  - Reject malformed decision/risk enums.
  - Sabotage tests prove three non-canonical roles (PROMPTER / GHOST /
    MINION) cannot push a quorum of four to AUTO_GO.

These tests are the executable complement of the YAML contract frozen in
``orchestrator/contracts/internal_consult_v1.yaml``. They exercise the
runtime, not the doc.
"""
from __future__ import annotations

import pytest

from agent_body.internal_consult_synth import (
    CANONICAL_REVIEW_DECISIONS,
    CANONICAL_REVIEW_ROLES,
    CANONICAL_RISK_LEVELS,
    REQUIRED_CORRELATION_FIELDS,
    correlate,
    parse_review_envelope,
    synthesize,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

GOOD_BUNDLE = {
    "QUERY_ID": "evolution_v1_role_whitelist_fix_20260914_01",
    "REPOSITORY": "neokyhurtado-cmd/traficlab-factory",
    "ISSUE_OR_PR": "#27",
    "COMMIT_SHA": "513aff3f3e95b7577afa12e67b6d83cb7e383902",
    "REVERSIBLE": True,
    "CRITICAL_GATE": False,
    "HUMAN_GATE": False,
}


def _canonical_review(role: str, decision: str = "GO", risk: str = "LOW") -> dict:
    """One canonical review dict, all correlation fields exact-match the bundle."""
    assert role in CANONICAL_REVIEW_ROLES
    assert decision in CANONICAL_REVIEW_DECISIONS
    assert risk in CANONICAL_RISK_LEVELS
    return {
        "role": role,
        "decision": decision,
        "risk": risk,
        "confidence": 0.9,
        "counterexample": None,
        "evidence": ["agent_body/"],
        "query_id": GOOD_BUNDLE["QUERY_ID"],
        "repository": GOOD_BUNDLE["REPOSITORY"],
        "issue_or_pr": GOOD_BUNDLE["ISSUE_OR_PR"],
        "commit_sha": GOOD_BUNDLE["COMMIT_SHA"],
    }


def _saboteur_review(role: str) -> dict:
    """A non-canonical 'role' inserted in place of a real consultant.

    Correlation fields still match the bundle (the attack is on the role
    whitelist, not on correlation). If the runtime lets this through,
    AUTO_GO is possible — that is the regression we are guarding against.
    """
    return {
        "role": role,
        "decision": "GO",
        "risk": "LOW",
        "confidence": 0.9,
        "counterexample": None,
        "evidence": ["agent_body/"],
        "query_id": GOOD_BUNDLE["QUERY_ID"],
        "repository": GOOD_BUNDLE["REPOSITORY"],
        "issue_or_pr": GOOD_BUNDLE["ISSUE_OR_PR"],
        "commit_sha": GOOD_BUNDLE["COMMIT_SHA"],
    }


# ---------------------------------------------------------------------------
# 1. Canonical role / decision / risk sets are exactly four / four / four
# ---------------------------------------------------------------------------


def test_canonical_review_roles_are_exactly_the_four_frozen_roles():
    """Frozen set per orchestrator/contracts/internal_consult_v1.yaml.

    If a fifth role is ever added it MUST go through the YAML contract
    and the four existing reviewers must still cover it.
    """
    assert CANONICAL_REVIEW_ROLES == frozenset({
        "ARCHITECT", "EVIDENCE", "RED_TEAM", "TEST_ORACLE",
    })


def test_canonical_decisions_and_risk_levels_are_frozen():
    """Mirror the YAML enums so the runtime can reject malformed values."""
    assert CANONICAL_REVIEW_DECISIONS == frozenset({
        "GO", "REPLAN", "BLOCK", "ESCALATE",
    })
    assert CANONICAL_RISK_LEVELS == frozenset({
        "LOW", "MEDIUM", "HIGH", "CRITICAL",
    })


# ---------------------------------------------------------------------------
# 2. correlate() rejects non-canonical roles on the direct-dict path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bogus_role", ["PROMPTER", "GHOST", "MINION"])
def test_correlate_rejects_non_canonical_role_direct_path(bogus_role):
    """synthesize(reviews=[...]) is the path a programmatic caller uses.

    A non-canonical role MUST be rejected as ACTOR_UNVERIFIED there, not
    just on the envelope parser.
    """
    corr = correlate(_saboteur_review(bogus_role), GOOD_BUNDLE)
    assert corr["valid"] is False
    assert corr["actor"] == "ACTOR_UNVERIFIED"
    assert "ROLE" in corr["mismatch_fields"]


@pytest.mark.parametrize("bogus_role", ["PROMPTER", "GHOST", "MINION"])
def test_correlate_rejects_non_canonical_role_envelope_path(bogus_role):
    """Even if someone hand-crafts a [MINIMAX_REVIEW:PROMPTER:v1] envelope,
    the regex itself rejects anything outside the canonical four. So the
    parser returns ACTOR_UNVERIFIED before any decision/risk can vote.
    """
    text = (
        f"[MINIMAX_REVIEW:{bogus_role}:v1]\n"
        f"QUERY_ID = {GOOD_BUNDLE['QUERY_ID']}\n"
        f"REPOSITORY = {GOOD_BUNDLE['REPOSITORY']}\n"
        f"ISSUE_OR_PR = {GOOD_BUNDLE['ISSUE_OR_PR']}\n"
        f"COMMIT_SHA = {GOOD_BUNDLE['COMMIT_SHA']}\n"
        "DECISION = GO\n"
        "RISK = LOW\n"
    )
    parsed, corr = parse_review_envelope(text, expected_bundle=GOOD_BUNDLE)
    # Envelope regex never matched → parsed is None.
    assert parsed is None
    assert corr["valid"] is False
    assert corr["actor"] == "ACTOR_UNVERIFIED"
    assert "MARKER" in corr["mismatch_fields"]


# ---------------------------------------------------------------------------
# 3. correlate() fails closed on missing required correlation fields
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "missing_field",
    ["query_id", "repository", "issue_or_pr", "commit_sha"],
)
def test_correlate_rejects_review_missing_a_required_correlation_field(missing_field):
    """Each of the four canonical correlation fields is required.

    A review missing any one of them MUST be rejected as ACTOR_UNVERIFIED —
    fail closed, no silent accept.
    """
    review = _canonical_review("ARCHITECT")
    del review[missing_field]
    corr = correlate(review, GOOD_BUNDLE)
    assert corr["valid"] is False
    assert corr["actor"] == "ACTOR_UNVERIFIED"
    assert missing_field.upper() in corr["mismatch_fields"]


def test_correlate_rejects_review_missing_role():
    """Missing role is one of REQUIRED_REVIEW_FIELDS."""
    review = _canonical_review("ARCHITECT")
    del review["role"]
    corr = correlate(review, GOOD_BUNDLE)
    assert corr["valid"] is False
    assert corr["actor"] == "ACTOR_UNVERIFIED"
    assert "ROLE" in corr["mismatch_fields"]


# ---------------------------------------------------------------------------
# 4. correlate() rejects malformed decision / risk enums
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bogus_decision", ["MAYBE", "GOGO", "", "go"])
def test_correlate_rejects_non_canonical_decision(bogus_decision):
    review = _canonical_review("ARCHITECT")
    review["decision"] = bogus_decision
    corr = correlate(review, GOOD_BUNDLE)
    assert corr["valid"] is False
    assert corr["actor"] == "ACTOR_UNVERIFIED"
    assert "DECISION" in corr["mismatch_fields"]


@pytest.mark.parametrize("bogus_risk", ["BANANA", "", "low", "EXTREME"])
def test_correlate_rejects_non_canonical_risk(bogus_risk):
    review = _canonical_review("ARCHITECT")
    review["risk"] = bogus_risk
    corr = correlate(review, GOOD_BUNDLE)
    assert corr["valid"] is False
    assert corr["actor"] == "ACTOR_UNVERIFIED"
    assert "RISK" in corr["mismatch_fields"]


# ---------------------------------------------------------------------------
# 5. THE SABOTAGE: three non-canonical roles cannot push to AUTO_GO
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "saboteur_roles",
    [
        ["PROMPTER", "GHOST", "MINION"],
        ["PROMPTER", "ARCHITECT", "EVIDENCE"],
        ["RED_TEAM", "GHOST", "MINION"],
        ["PROMPTER", "GHOST", "MINION", "ARCHITECT"],
    ],
)
def test_three_non_canonical_roles_cannot_drive_auto_go(saboteur_roles):
    """The headline sabotage test.

    Build a four-review bundle where exactly one role is canonical and the
    remaining 1-3 are saboteurs. The decision MUST NOT be AUTO_GO because:

      - The saboteur role(s) are rejected by correlate() → ACTOR_UNVERIFIED.
      - The valid votes never reach min_quorum (3).
      - synthesize() returns SECOND_ROUND (or BLOCK if consensus is BLOCK).

    If this ever returns AUTO_GO, the canonical review_roles enforcement
    is broken and the directive's safety contract is violated.
    """
    reviews = []
    for r in saboteur_roles:
        if r in CANONICAL_REVIEW_ROLES:
            reviews.append(_canonical_review(r))
        else:
            reviews.append(_saboteur_review(r))

    decision = synthesize(GOOD_BUNDLE, reviews=reviews)

    # Headline: AUTO_GO is FORBIDDEN in every sabotage scenario.
    assert decision["action"] != "AUTO_GO", (
        f"sabotage succeeded: {decision}"
    )

    # The saboteur role(s) must show up in actor_unverified / rejected.
    for r in saboteur_roles:
        if r not in CANONICAL_REVIEW_ROLES:
            assert r in decision["actor_unverified"], (
                f"saboteur {r} was not flagged actor_unverified in {decision}"
            )
            assert r in decision["rejected_reviews"], (
                f"saboteur {r} was not flagged rejected in {decision}"
            )

    # review_roles in the decision must contain only canonical roles.
    for r in decision["review_roles"]:
        assert r in CANONICAL_REVIEW_ROLES, (
            f"non-canonical role {r} leaked into review_roles in {decision}"
        )


def test_all_canonical_roles_can_still_reach_auto_go_after_enforcement():
    """Negative control: the enforcement MUST NOT over-reject.

    All four canonical roles, all GO, all correlation match → AUTO_GO.
    This guards against an over-zealous fix that breaks the happy path.
    """
    reviews = [_canonical_review(r) for r in (
        "ARCHITECT", "EVIDENCE", "RED_TEAM", "TEST_ORACLE",
    )]
    decision = synthesize(GOOD_BUNDLE, reviews=reviews)
    assert decision["action"] == "AUTO_GO", decision
    assert decision["counterexample"] == "NONE"
    assert set(decision["review_roles"]) == CANONICAL_REVIEW_ROLES
    assert decision["actor_unverified"] == []


# ---------------------------------------------------------------------------
# 6. Required correlation fields set is frozen (no silent drift)
# ---------------------------------------------------------------------------


def test_required_correlation_fields_are_exactly_the_yaml_four():
    """If the YAML ever changes the four correlation fields, both this
    test and the YAML contract test will fire — that is by design.
    """
    assert REQUIRED_CORRELATION_FIELDS == (
        "query_id", "repository", "issue_or_pr", "commit_sha",
    )
