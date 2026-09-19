"""Guard the externally visible INTERNAL_CONSULT message contract."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / ".hermes" / "skills" / "internal-consult" / "SKILL.md"


def test_review_and_decision_markers_are_frozen():
    text = SKILL.read_text(encoding="utf-8")
    for marker in (
        "[INTERNAL_CONSULT_QUERY:v1]",
        "[MINIMAX_REVIEW:ARCHITECT:v1]",
        "[MINIMAX_REVIEW:EVIDENCE:v1]",
        "[MINIMAX_REVIEW:RED_TEAM:v1]",
        "[MINIMAX_REVIEW:TEST_ORACLE:v1]",
        "[CONSULT_DECISION:v1]",
        "[ASTRA_QUERY:v1]",
        "[ASTRA_DECISION:v1]",
        "[DAVID_DECISION:v1]",
    ):
        assert marker in text


def test_skill_never_equates_github_transport_with_decision_actor():
    text = SKILL.read_text(encoding="utf-8")
    assert "A GitHub username is not sufficient proof" in text
    assert "ACTOR_UNVERIFIED" in text
    assert "TRANSPORT_ACTOR" in text
    assert "DECISION_ACTOR" in text
