"""INTERNAL_CONSULT synthesis oracle — executable counterpart to
orchestrator/contracts/internal_consult_v1.yaml.

The YAML freezes the policy. This module is the runtime that interprets
it. The tests in agent_body/tests/test_internal_consult_executable.py
and agent_body/tests/test_evolution_e2e_001_actor_and_autogo.py exercise
this code, so the YAML policy and the runtime never drift.

Public surface:
    parse_review_envelope(text, expected_bundle) -> (parsed, correlation)
    correlate(parsed, expected_bundle) -> dict
    synthesize(bundle, reviews, parsed_reviews=None) -> dict
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

_POLICY_PATH = Path(__file__).resolve().parent.parent / "orchestrator" / "contracts" / "internal_consult_v1.yaml"
_POLICY_CACHE: Optional[dict] = None


def _policy() -> dict:
    global _POLICY_CACHE
    if _POLICY_CACHE is None:
        _POLICY_CACHE = yaml.safe_load(_POLICY_PATH.read_text(encoding="utf-8"))
    return _POLICY_CACHE


# Envelope marker regex — one of the four frozen roles.
_REVIEW_MARKER = re.compile(
    r"\[MINIMAX_REVIEW:(ARCHITECT|EVIDENCE|RED_TEAM|TEST_ORACLE):v1\]"
)
_FIELD_LINE = re.compile(r"^\s*([A-Z_]+)\s*=\s*(.*?)\s*$")

# Canonical enum sets — frozen from orchestrator/contracts/internal_consult_v1.yaml.
# These MUST stay in lock-step with the YAML; the yaml is authoritative and
# the regression tests under directive_watcher/tests/test_internal_consult_contract.py
# freeze the contract. The Python sets here are the runtime enforcement that
# catches a non-canonical role / malformed enum before it can vote.
CANONICAL_REVIEW_ROLES: frozenset = frozenset({
    "ARCHITECT", "EVIDENCE", "RED_TEAM", "TEST_ORACLE",
})
CANONICAL_REVIEW_DECISIONS: frozenset = frozenset({
    "GO", "REPLAN", "BLOCK", "ESCALATE",
})
CANONICAL_RISK_LEVELS: frozenset = frozenset({
    "LOW", "MEDIUM", "HIGH", "CRITICAL",
})

# Required correlation fields per internal_consult_v1.yaml::identity::required_correlation_fields.
# A review missing any of these is rejected as ACTOR_UNVERIFIED — fail closed.
REQUIRED_CORRELATION_FIELDS: tuple = (
    "query_id", "repository", "issue_or_pr", "commit_sha",
)

# Required per-review fields for synthesize() direct path.
# A review missing any of these cannot vote and is rejected as ACTOR_UNVERIFIED.
REQUIRED_REVIEW_FIELDS: tuple = (
    "role", "decision", "risk",
) + REQUIRED_CORRELATION_FIELDS


def parse_review_envelope(text: str, expected_bundle: dict) -> Tuple[Optional[dict], dict]:
    """Parse a [MINIMAX_REVIEW:<ROLE>:v1] envelope into a structured dict.

    Returns (parsed_dict_or_None, correlation_dict). The correlation dict
    has keys: valid (bool), mismatch_fields (list), actor (str).
    """
    m = _REVIEW_MARKER.search(text)
    if not m:
        return None, {"valid": False, "mismatch_fields": ["MARKER"], "actor": "ACTOR_UNVERIFIED"}

    role = m.group(1)
    parsed: Dict[str, object] = {"role": role}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("["):
            continue
        fm = _FIELD_LINE.match(line)
        if not fm:
            continue
        key, value = fm.group(1), fm.group(2)
        if key in {"DECISION"}:
            parsed["decision"] = value
        elif key in {"RISK"}:
            parsed["risk"] = value
        elif key in {"CONFIDENCE"}:
            try:
                parsed["confidence"] = float(value)
            except ValueError:
                parsed["confidence"] = 0.0
        elif key in {"QUERY_ID", "REPOSITORY", "ISSUE_OR_PR", "COMMIT_SHA"}:
            parsed[key.lower()] = value
        elif key in {"COUNTEREXAMPLE"}:
            parsed["counterexample"] = None if value.lower() == "none" else value
        elif key in {"EVIDENCE"}:
            parsed["evidence"] = value
        elif key in {"NOTES"}:
            parsed["notes"] = value

    # Required fields per orchestrator/contracts/internal_consult_v1.yaml
    required = ("decision", "risk", "query_id", "repository", "issue_or_pr", "commit_sha")
    missing = [k for k in required if k not in parsed]
    if missing:
        return parsed, {
            "valid": False,
            "mismatch_fields": missing,
            "actor": "ACTOR_UNVERIFIED",
        }

    correlation = correlate(parsed, expected_bundle)
    return parsed, correlation


def correlate(parsed: dict, expected_bundle: dict) -> dict:
    """Verify the parsed review against the bundle AND the canonical enums.

    The review is admitted to the quorum only if:
      1. Its ``role`` is one of the four canonical review_roles, AND
      2. Its ``decision`` is one of the canonical review_decisions, AND
      3. Its ``risk`` is one of the canonical risk_levels, AND
      4. Every required correlation field is present in both the review
         and the bundle, AND matches exactly.

    Any failure returns ``valid=False``, ``actor="ACTOR_UNVERIFIED"``,
    and a populated ``mismatch_fields`` so the caller can show why.

    The four required correlation fields per internal_consult_v1.yaml::
        QUERY_ID, REPOSITORY, ISSUE_OR_PR, COMMIT_SHA.
    """
    # Structural checks: missing fields, non-canonical role/decision/risk.
    missing = [f for f in REQUIRED_REVIEW_FIELDS if not parsed.get(f)]
    if missing:
        return {
            "valid": False,
            "mismatch_fields": [m.upper() for m in missing],
            "actor": "ACTOR_UNVERIFIED",
            "reason": "missing_required_fields",
        }

    role = parsed.get("role")
    if role not in CANONICAL_REVIEW_ROLES:
        return {
            "valid": False,
            "mismatch_fields": ["ROLE"],
            "actor": "ACTOR_UNVERIFIED",
            "reason": "non_canonical_role",
        }

    decision = parsed.get("decision")
    if decision not in CANONICAL_REVIEW_DECISIONS:
        return {
            "valid": False,
            "mismatch_fields": ["DECISION"],
            "actor": "ACTOR_UNVERIFIED",
            "reason": "non_canonical_decision",
        }

    risk = parsed.get("risk")
    if risk not in CANONICAL_RISK_LEVELS:
        return {
            "valid": False,
            "mismatch_fields": ["RISK"],
            "actor": "ACTOR_UNVERIFIED",
            "reason": "non_canonical_risk",
        }

    # Correlation: every required field must match the bundle exactly.
    mismatch = []
    for f in REQUIRED_CORRELATION_FIELDS:
        want = expected_bundle.get(f.upper())
        got = parsed.get(f)
        if want is None or got != want:
            mismatch.append(f.upper())
    if mismatch:
        return {
            "valid": False,
            "mismatch_fields": mismatch,
            "actor": "ACTOR_UNVERIFIED",
            "reason": "correlation_mismatch",
        }
    return {
        "valid": True,
        "mismatch_fields": [],
        "actor": parsed.get("role", "MINIMAX_CONSULTANT"),
    }


def synthesize(
    bundle: dict,
    reviews: Optional[List[dict]] = None,
    parsed_reviews: Optional[List[Tuple[dict, dict]]] = None,
) -> dict:
    """Apply the precedence map to a set of reviews and produce a decision.

    Either pass `reviews` (raw dicts already correlated) or
    `parsed_reviews` (the output of parse_review_envelope). When both
    are given, parsed_reviews wins.
    """
    pol = _policy()

    pairs: List[Tuple[dict, dict]] = []
    if parsed_reviews is not None:
        pairs = list(parsed_reviews)
    elif reviews is not None:
        for r in reviews:
            pairs.append((r, correlate(r, bundle)))

    # Filter to valid reviews; track rejected separately.
    valid: List[dict] = []
    rejected_roles: List[str] = []
    actor_unverified: List[str] = []
    for parsed, corr in pairs:
        if corr["valid"]:
            valid.append(parsed)
        else:
            role = parsed.get("role", "?")
            rejected_roles.append(role)
            actor_unverified.append(role)

    human_gate = bool(bundle.get("HUMAN_GATE", False))
    reversible = bool(bundle.get("REVERSIBLE", True))
    critical_gate = bool(bundle.get("CRITICAL_GATE", False))

    base = {
        "query_id": bundle.get("QUERY_ID", ""),
        "review_roles": sorted({r["role"] for r in valid}),
        "quorum_size": len(valid),
        "rejected_reviews": sorted(rejected_roles),
        "actor_unverified": sorted(actor_unverified),
        "max_risk": _max_risk([r.get("risk", "LOW") for r in valid]),
    }

    # Precedence 1: HUMAN_GATE → ESCALATE_DAVID.
    if human_gate:
        return {**base, "action": pol["rules"]["human_gate"], "counterexample": "NONE",
                "reason": "human_gate true"}

    # Precedence 2: reproducible counterexample.
    has_counter = next((r for r in valid if r.get("counterexample")), None)
    if has_counter:
        key = "counterexample_reversible" if reversible else "counterexample_irreversible"
        return {
            **base,
            "action": pol["rules"][key],
            "counterexample": f"{has_counter['role']}: {has_counter['counterexample']}",
            "reason": "reproducible counterexample overrides consensus",
        }

    # Precedence 3: critical or irreversible.
    if critical_gate or not reversible:
        return {
            **base,
            "action": pol["rules"]["critical_gate"],
            "counterexample": "NONE",
            "reason": "critical gate / irreversible",
        }

    # Precedence 4: HIGH/CRITICAL risk.
    if any(r.get("risk") in {"HIGH", "CRITICAL"} for r in valid):
        return {
            **base,
            "action": pol["rules"]["high_risk"],
            "counterexample": "NONE",
            "reason": "max risk HIGH/CRITICAL",
        }

    # Precedence 5: BLOCK consensus.
    if valid and all(r.get("decision") == "BLOCK" for r in valid):
        return {
            **base,
            "action": pol["rules"]["material_blocker"],
            "counterexample": "NONE",
            "reason": "all reviews BLOCK",
        }

    # Precedence 6: insufficient quorum.
    min_quorum = pol["min_quorum"]
    if len({r["role"] for r in valid}) < min_quorum:
        return {
            **base,
            "action": pol["rules"]["insufficient_quorum"],
            "counterexample": "NONE",
            "reason": f"quorum {len({r['role'] for r in valid})} < {min_quorum}",
        }

    # Precedence 7: disagreement.
    decisions = {r.get("decision") for r in valid}
    if len(decisions) != 1:
        return {
            **base,
            "action": pol["rules"]["disagreement"],
            "counterexample": "NONE",
            "reason": f"disagreement across roles: {sorted(decisions)}",
        }

    # Precedence 8: consensus.
    if decisions == {"GO"}:
        return {
            **base,
            "action": pol["rules"]["consensus_go_reversible_low_or_medium"],
            "counterexample": "NONE",
            "reason": "consensus GO reversible low/medium risk",
        }
    if decisions == {"REPLAN"}:
        return {
            **base,
            "action": pol["rules"]["consensus_replan_reversible"],
            "counterexample": "NONE",
            "reason": "consensus REPLAN reversible",
        }
    return {
        **base,
        "action": "SECOND_ROUND",
        "counterexample": "NONE",
        "reason": "no consensus rule matched",
    }


_RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


def _max_risk(risks: List[str]) -> str:
    if not risks:
        return "LOW"
    return max(risks, key=lambda r: _RISK_ORDER.get(r, 0))
