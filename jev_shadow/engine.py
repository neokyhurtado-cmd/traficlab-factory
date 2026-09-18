from __future__ import annotations

from typing import Any, Mapping

from .contracts import MODEL_ID, SCHEMA, ShadowDecision, TaskSnapshot, jev_questions
from .provider import DecisionProvider, DisabledProvider


def _prob(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, f))


def _choice(answer: Any) -> tuple[str | None, float | None]:
    if not isinstance(answer, Mapping):
        return None, None
    selected = answer.get("choice")
    probabilities = answer.get("probabilities")
    confidence = None
    if isinstance(probabilities, Mapping) and selected in probabilities:
        confidence = _prob(probabilities.get(selected))
    return (str(selected) if selected is not None else None, confidence)


def _boolean_probability(answer: Any) -> float | None:
    if isinstance(answer, Mapping):
        return _prob(answer.get("probability"))
    return None


def _score(answer: Any) -> float | None:
    if not isinstance(answer, Mapping):
        return None
    try:
        return float(answer.get("score"))
    except (TypeError, ValueError):
        return None


def evaluate_shadow(
    raw_state: Mapping[str, Any],
    *,
    provider: DecisionProvider | None = None,
) -> ShadowDecision:
    """Evaluate Jev in advisory shadow mode.

    The result is explicitly non-authoritative. Protected actions are detected
    in deterministic code and force hard_gate_override=True.
    """
    snapshot = TaskSnapshot.from_mapping(raw_state)
    hard_gate = bool(snapshot.protected_flags)
    result = (provider or DisabledProvider()).evaluate(
        state=snapshot.as_state(),
        questions=jev_questions(),
    )

    route, route_conf = _choice(result.answers.get("route"))
    blocker, blocker_conf = _choice(result.answers.get("blocker"))
    continuation, continuation_conf = _choice(result.answers.get("continuation"))

    return ShadowDecision(
        schema=SCHEMA,
        model=MODEL_ID,
        provider_status=result.status,
        route=route,
        route_confidence=route_conf,
        needs_review_probability=_boolean_probability(result.answers.get("needs_review")),
        blocker=blocker,
        blocker_confidence=blocker_conf,
        continuation=continuation,
        continuation_confidence=continuation_conf,
        risk_score=_score(result.answers.get("risk")),
        hard_gate_override=hard_gate,
        may_control_execution=False,
        protected_flags=snapshot.protected_flags,
        error=result.error,
    )
