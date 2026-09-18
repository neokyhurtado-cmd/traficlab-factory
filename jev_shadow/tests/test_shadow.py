from __future__ import annotations

from jev_shadow.contracts import PROTECTED_FLAGS, TaskSnapshot, jev_questions
from jev_shadow.engine import evaluate_shadow
from jev_shadow.metrics import score_observations
from jev_shadow.provider import ProviderResult


class FakeProvider:
    def __init__(self, answers):
        self.answers = answers
        self.last_state = None
        self.last_questions = None

    def evaluate(self, *, state, questions):
        self.last_state = state
        self.last_questions = questions
        return ProviderResult("OK", self.answers, {})


def fake_answers():
    return {
        "route": {
            "type": "choice",
            "choice": "code",
            "probabilities": {"code": 0.91, "research": 0.09},
        },
        "needs_review": {"type": "boolean", "probability": 0.22},
        "blocker": {
            "type": "choice",
            "choice": "none",
            "probabilities": {"none": 0.88, "runtime": 0.12},
        },
        "continuation": {
            "type": "choice",
            "choice": "continue",
            "probabilities": {"continue": 0.94, "review": 0.06},
        },
        "risk": {
            "type": "score",
            "score": 0.4,
            "probabilities": {"0": 0.6, "1": 0.4},
        },
    }


def test_questions_are_fixed_typed_decisions():
    questions = jev_questions()
    assert set(questions) == {
        "route", "needs_review", "blocker", "continuation", "risk"
    }
    assert questions["route"]["type"] == "choice"
    assert questions["needs_review"]["type"] == "boolean"
    assert questions["risk"]["type"] == "score"


def test_arbitrary_fields_are_not_forwarded():
    provider = FakeProvider(fake_answers())
    evaluate_shadow(
        {
            "task_id": "t1",
            "goal": "run tests",
            "raw_code": "PRIVATE SOURCE",
            "api_key": "SECRET",
            "document": "CLIENT CORPUS",
        },
        provider=provider,
    )
    assert provider.last_state["task_id"] == "t1"
    assert "raw_code" not in provider.last_state
    assert "api_key" not in provider.last_state
    assert "document" not in provider.last_state


def test_protected_gate_is_deterministic_and_never_delegated():
    provider = FakeProvider(fake_answers())
    decision = evaluate_shadow(
        {"task_id": "t2", "protected_flags": ["merge_main"]},
        provider=provider,
    )
    assert "merge_main" in PROTECTED_FLAGS
    assert decision.hard_gate_override is True
    assert decision.may_control_execution is False


def test_unknown_protected_flags_are_discarded_not_escalated():
    snapshot = TaskSnapshot.from_mapping(
        {"protected_flags": ["merge_main", "made_up_flag"]}
    )
    assert snapshot.protected_flags == ("merge_main",)


def test_shadow_decision_normalizes_probabilities():
    decision = evaluate_shadow({"task_id": "t3"}, provider=FakeProvider(fake_answers()))
    assert decision.provider_status == "OK"
    assert decision.route == "code"
    assert decision.route_confidence == 0.91
    assert decision.needs_review_probability == 0.22
    assert decision.blocker == "none"
    assert decision.continuation == "continue"
    assert decision.risk_score == 0.4
    assert decision.may_control_execution is False


def test_disabled_provider_is_non_blocking_and_non_authoritative():
    decision = evaluate_shadow({"task_id": "t4"})
    assert decision.provider_status == "DISABLED"
    assert decision.route is None
    assert decision.may_control_execution is False


def test_metrics_surface_dangerous_review_false_negatives():
    rows = [
        {
            "prediction": {
                "provider_status": "OK",
                "route": "code",
                "blocker": "none",
                "continuation": "continue",
                "needs_review_probability": 0.1,
                "risk_score": 1.0,
            },
            "actual": {
                "route": "code",
                "blocker": "none",
                "continuation": "review",
                "needs_review": True,
                "risk_score": 2.0,
            },
        },
        {
            "prediction": {
                "provider_status": "OK",
                "route": "research",
                "blocker": "missing_data",
                "continuation": "review",
                "needs_review_probability": 0.9,
                "risk_score": 2.0,
            },
            "actual": {
                "route": "research",
                "blocker": "missing_data",
                "continuation": "review",
                "needs_review": True,
                "risk_score": 2.0,
            },
        },
    ]
    metrics = score_observations(rows, review_threshold=0.5)
    assert metrics.cases == 2
    assert metrics.available_cases == 2
    assert metrics.route_accuracy == 1.0
    assert metrics.blocker_accuracy == 1.0
    assert metrics.continuation_accuracy == 0.5
    assert metrics.review_false_negative_rate == 0.5
    assert metrics.risk_mae == 0.5
