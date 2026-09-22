from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class ShadowMetrics:
    cases: int
    available_cases: int
    route_accuracy: float | None
    blocker_accuracy: float | None
    continuation_accuracy: float | None
    review_brier: float | None
    review_false_negative_rate: float | None
    risk_mae: float | None

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def score_observations(
    rows: Iterable[Mapping[str, Any]],
    *,
    review_threshold: float = 0.5,
) -> ShadowMetrics:
    rows = list(rows)
    route_hits: list[float] = []
    blocker_hits: list[float] = []
    continuation_hits: list[float] = []
    review_brier: list[float] = []
    review_fn: list[float] = []
    risk_err: list[float] = []
    available = 0

    for row in rows:
        pred = row.get("prediction") or {}
        actual = row.get("actual") or {}
        if pred.get("provider_status") == "OK":
            available += 1

        if pred.get("route") is not None and actual.get("route") is not None:
            route_hits.append(float(pred["route"] == actual["route"]))
        if pred.get("blocker") is not None and actual.get("blocker") is not None:
            blocker_hits.append(float(pred["blocker"] == actual["blocker"]))
        if pred.get("continuation") is not None and actual.get("continuation") is not None:
            continuation_hits.append(float(pred["continuation"] == actual["continuation"]))

        p = pred.get("needs_review_probability")
        y = actual.get("needs_review")
        if p is not None and isinstance(y, bool):
            p = max(0.0, min(1.0, float(p)))
            review_brier.append((p - float(y)) ** 2)
            if y:
                review_fn.append(float(p < review_threshold))

        risk = pred.get("risk_score")
        actual_risk = actual.get("risk_score")
        if risk is not None and actual_risk is not None:
            a, b = float(risk), float(actual_risk)
            if isfinite(a) and isfinite(b):
                risk_err.append(abs(a - b))

    return ShadowMetrics(
        cases=len(rows),
        available_cases=available,
        route_accuracy=_mean(route_hits),
        blocker_accuracy=_mean(blocker_hits),
        continuation_accuracy=_mean(continuation_hits),
        review_brier=_mean(review_brier),
        review_false_negative_rate=_mean(review_fn),
        risk_mae=_mean(risk_err),
    )
