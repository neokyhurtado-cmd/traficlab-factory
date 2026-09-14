"""Verify canonical INTERNAL_CONSULT examples against policy precedence."""
from __future__ import annotations

import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
POLICY = yaml.safe_load(
    (ROOT / "orchestrator" / "contracts" / "internal_consult_v1.yaml").read_text(
        encoding="utf-8"
    )
)
EXAMPLES = json.loads(
    (ROOT / "orchestrator" / "contracts" / "internal_consult_examples.json").read_text(
        encoding="utf-8"
    )
)["examples"]


def _decide(case: dict) -> str:
    """Small executable oracle for the YAML policy, intentionally stdlib-like."""
    if case["human_gate"]:
        return POLICY["rules"]["human_gate"]
    counterexample = any(r.get("counterexample") for r in case["reviews"])
    if counterexample:
        key = "counterexample_reversible" if case["reversible"] else "counterexample_irreversible"
        return POLICY["rules"][key]
    if case["critical_gate"] or not case["reversible"]:
        return POLICY["rules"]["critical_gate"]
    if any(r["risk"] in {"HIGH", "CRITICAL"} for r in case["reviews"]):
        return POLICY["rules"]["high_risk"]
    if any(r["decision"] == "BLOCK" for r in case["reviews"]):
        return POLICY["rules"]["material_blocker"]
    if len({r["role"] for r in case["reviews"]}) < POLICY["min_quorum"]:
        return POLICY["rules"]["insufficient_quorum"]
    decisions = {r["decision"] for r in case["reviews"]}
    if len(decisions) != 1:
        return POLICY["rules"]["disagreement"]
    if decisions == {"GO"}:
        return POLICY["rules"]["consensus_go_reversible_low_or_medium"]
    if decisions == {"REPLAN"}:
        return POLICY["rules"]["consensus_replan_reversible"]
    return "SECOND_ROUND"


def test_canonical_examples_have_expected_actions():
    for case in EXAMPLES:
        assert _decide(case) == case["expected_action"], case["name"]
