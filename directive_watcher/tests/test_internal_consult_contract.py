"""Static contract tests for the Hermes project-local INTERNAL_CONSULT skill."""
from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / ".hermes" / "skills" / "internal-consult" / "SKILL.md"
POLICY = ROOT / "orchestrator" / "contracts" / "internal_consult_v1.yaml"


def _policy() -> dict:
    return yaml.safe_load(POLICY.read_text(encoding="utf-8"))


def test_internal_consult_is_a_real_project_local_hermes_skill():
    text = SKILL.read_text(encoding="utf-8")
    assert "name: internal-consult" in text
    assert "delegate_task(tasks=[...])" in text
    assert "ARCHITECT" in text
    assert "EVIDENCE" in text
    assert "RED_TEAM" in text
    assert "TEST_ORACLE" in text


def test_counterexample_precedes_consensus():
    cfg = _policy()
    precedence = cfg["precedence"]
    assert precedence.index("reproducible_counterexample") < precedence.index("consensus")
    assert cfg["rules"]["counterexample_reversible"] == "AUTO_REPLAN"
    assert cfg["rules"]["counterexample_irreversible"] == "ESCALATE_ASTRA"


def test_low_medium_reversible_consensus_can_autogo_but_critical_escalates():
    cfg = _policy()
    assert cfg["min_quorum"] >= 3
    assert cfg["rules"]["consensus_go_reversible_low_or_medium"] == "AUTO_GO"
    assert cfg["rules"]["critical_gate"] == "ESCALATE_ASTRA"
    assert cfg["rules"]["irreversible"] == "ESCALATE_ASTRA"
    assert cfg["rules"]["high_risk"] == "ESCALATE_ASTRA"


def test_human_gate_is_narrow_and_explicit():
    cfg = _policy()
    assert cfg["rules"]["human_gate"] == "ESCALATE_DAVID"
    assert "ESCALATE_DAVID" in cfg["actions"]


def test_transport_identity_is_not_decision_identity():
    cfg = _policy()
    ident = cfg["identity"]
    assert ident["transport_actor_is_decision_actor"] is False
    assert ident["actor_unverified_value"] == "ACTOR_UNVERIFIED"
    assert set(ident["required_correlation_fields"]) == {
        "QUERY_ID", "REPOSITORY", "ISSUE_OR_PR", "COMMIT_SHA"
    }
    assert "ASTRA" in ident["decision_actors"]
    assert "DAVID" in ident["decision_actors"]
    assert "MINIMAX_CONSULTANT" in ident["decision_actors"]


def test_no_new_provider_secret_contract():
    cfg = _policy()
    provider = cfg["provider"]
    assert provider["reuse_parent_provider_configuration"] is True
    assert provider["new_api_key_required"] is False
    assert provider["secret_copying"] == "forbidden"
    assert provider["provider_change"] == "forbidden"


def test_consultation_is_read_only_and_first_round_independent():
    cfg = _policy()
    assert cfg["consultation_mutation"] == "forbidden"
    assert cfg["first_round_independent"] is True
    assert len(set(cfg["review_roles"])) == 4
