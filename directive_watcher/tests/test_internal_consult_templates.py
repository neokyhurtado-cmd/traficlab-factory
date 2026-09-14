"""Keep consultation correlation fields explicit at the GitHub boundary."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "orchestrator" / "contracts"


def test_query_template_carries_exact_context():
    text = (CONTRACTS / "internal_consult_query_template.md").read_text(encoding="utf-8")
    for field in ("QUERY_ID", "REPOSITORY", "ISSUE_OR_PR", "COMMIT_SHA", "REVERSIBLE", "CRITICAL_GATE", "HUMAN_GATE"):
        assert field in text


def test_decision_template_separates_transport_and_decision_actor():
    text = (CONTRACTS / "internal_consult_decision_template.md").read_text(encoding="utf-8")
    assert "TRANSPORT_ACTOR" in text
    assert "DECISION_ACTOR" in text
    assert "ACTOR_UNVERIFIED" in text
    assert "COMMIT_SHA" in text
