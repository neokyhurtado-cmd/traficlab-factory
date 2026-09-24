"""Action + verification fusion without introducing a shell executor."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Generic, Optional, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class Verification:
    passed: bool
    summary: str = ""


@dataclass(frozen=True)
class FusedActionResult(Generic[T]):
    name: str
    status: str
    action_result: Optional[T]
    verification: Optional[Verification]
    duration_ms: int
    error: str = ""


class ActionFusion:
    """Run one caller-provided action immediately followed by its verifier.

    This intentionally accepts callables rather than shell strings. The
    existing runtime remains the authority for permissions and command
    execution; this primitive only removes an unnecessary reasoning round-trip.
    """

    @staticmethod
    def run(
        name: str,
        action: Callable[[], T],
        verifier: Callable[[T], Verification | bool],
    ) -> FusedActionResult[T]:
        started = time.perf_counter()
        try:
            value = action()
        except Exception as exc:
            return FusedActionResult(
                name=name,
                status="ACTION_FAILED",
                action_result=None,
                verification=None,
                duration_ms=int((time.perf_counter() - started) * 1000),
                error=f"{type(exc).__name__}: {exc}",
            )

        try:
            verdict = verifier(value)
            if isinstance(verdict, bool):
                verdict = Verification(passed=verdict)
            if not isinstance(verdict, Verification):
                raise TypeError("verifier must return Verification or bool")
        except Exception as exc:
            return FusedActionResult(
                name=name,
                status="VERIFIER_FAILED",
                action_result=value,
                verification=None,
                duration_ms=int((time.perf_counter() - started) * 1000),
                error=f"{type(exc).__name__}: {exc}",
            )

        return FusedActionResult(
            name=name,
            status="PASS" if verdict.passed else "VERIFICATION_FAILED",
            action_result=value,
            verification=verdict,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
