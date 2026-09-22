from __future__ import annotations

from dataclasses import dataclass
import os
from time import monotonic
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class ProviderResult:
    status: str
    answers: Mapping[str, Any]
    metadata: Mapping[str, Any]
    error: str | None = None


class DecisionProvider(Protocol):
    def evaluate(
        self,
        *,
        state: Mapping[str, Any],
        questions: Mapping[str, Any],
    ) -> ProviderResult: ...


class DisabledProvider:
    def evaluate(
        self,
        *,
        state: Mapping[str, Any],
        questions: Mapping[str, Any],
    ) -> ProviderResult:
        return ProviderResult(
            status="DISABLED",
            answers={},
            metadata={},
            error="Jev shadow provider is disabled",
        )


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class TypeSafeJevProvider:
    """Live Jev provider using TypeSafe AI's official Python SDK.

    The provider is fail-soft and reads TYPESAFE_API_KEY only from the
    environment. Credentials are never added to state, stdout, or evidence.
    """

    def evaluate(
        self,
        *,
        state: Mapping[str, Any],
        questions: Mapping[str, Any],
    ) -> ProviderResult:
        if not os.environ.get("TYPESAFE_API_KEY"):
            return ProviderResult(
                "UNAVAILABLE",
                {},
                {"model": "jev-latest"},
                "TYPESAFE_API_KEY is not set",
            )

        try:
            from typesafe_sdk import Choice, Noul, Score, TypeSafeClient
        except Exception as exc:  # noqa: BLE001
            return ProviderResult(
                "UNAVAILABLE",
                {},
                {"model": "jev-latest"},
                f"typesafe-sdk unavailable: {type(exc).__name__}",
            )

        sdk_questions: dict[str, Any] = {}
        try:
            for name, question in questions.items():
                qtype = question.get("type")
                if qtype == "choice":
                    sdk_questions[name] = Choice(
                        instructions=question.get("instructions"),
                        criteria=question.get("criteria"),
                    )
                elif qtype == "noul":
                    sdk_questions[name] = Noul(
                        instructions=question.get("instructions"),
                    )
                elif qtype == "score":
                    sdk_questions[name] = Score(
                        instructions=question.get("instructions"),
                        criteria=question.get("criteria"),
                    )
                else:
                    raise ValueError(f"unsupported Jev question type: {qtype!r}")

            started = monotonic()
            with TypeSafeClient() as client:
                response = client.system_one(
                    state=dict(state),
                    questions=sdk_questions,
                )
            latency_ms = round((monotonic() - started) * 1000.0, 3)

            answers: dict[str, Any] = {}
            for name in sdk_questions:
                if name in response.choices:
                    answer = response.choices[name]
                    answers[name] = {
                        "type": "choice",
                        "choice": answer.choice,
                        "confidence": _number(getattr(answer, "confidence", None)),
                        "probabilities": dict(getattr(answer, "probabilities", {}) or {}),
                    }
                elif name in response.nouls:
                    answer = response.nouls[name]
                    answers[name] = {
                        "type": "noul",
                        "noul": _number(getattr(answer, "noul", None)),
                    }
                elif name in response.scores:
                    answer = response.scores[name]
                    answers[name] = {
                        "type": "score",
                        "score": _number(getattr(answer, "score", None)),
                        "confidence": _number(getattr(answer, "confidence", None)),
                        "probabilities": dict(getattr(answer, "probabilities", {}) or {}),
                    }

            usage = getattr(response, "usage", None)
            metadata = {
                "model": str(getattr(response, "model", "jev-latest")),
                "request_id": getattr(response, "request_id", None),
                "latency_ms": latency_ms,
                "usage": {
                    "input_tokens": getattr(usage, "input_tokens", None),
                    "output_tokens": getattr(usage, "output_tokens", None),
                },
            }
            return ProviderResult("OK", answers, metadata)
        except Exception as exc:  # noqa: BLE001
            # Keep provider failures non-authoritative. Never include secrets.
            return ProviderResult(
                "ERROR",
                {},
                {"model": "jev-latest"},
                f"{type(exc).__name__}: {str(exc)[:800]}",
            )
