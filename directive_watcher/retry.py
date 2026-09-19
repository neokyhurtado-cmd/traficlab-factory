"""Retry/backoff helpers used by the gh_client layer.

Why a separate module: every I/O call (gh api list, gh issue comment) goes
through here so the retry policy is uniform and unit-testable.

The default policy is bounded exponential backoff with jitter, capped at
5 attempts. Failures past the cap are surfaced to the caller as
``RetryExhausted`` so the scheduler can mark the run ``transient_failure``
without losing any state.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Callable, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class BackoffPolicy:
    initial_seconds: float = 0.5
    factor: float = 2.0
    max_seconds: float = 30.0
    max_attempts: int = 5
    jitter_ratio: float = 0.20  # ±20%

    def delay_for_attempt(self, attempt: int) -> float:
        """``attempt`` is 1-based. attempt=1 returns ~initial_seconds."""
        base = self.initial_seconds * (self.factor ** (attempt - 1))
        capped = min(base, self.max_seconds)
        if self.jitter_ratio <= 0:
            return capped
        # Jitter is bounded so the worst case stays <= max_seconds * (1 + jitter_ratio).
        # We then clamp to max_seconds for absolute safety — the contract
        # is "delay never exceeds max_seconds by more than jitter_ratio",
        # but a hard upper bound keeps the policy predictable.
        spread = capped * self.jitter_ratio
        jittered = capped + random.uniform(-spread, spread)
        return min(jittered, self.max_seconds)


class RetryExhausted(RuntimeError):
    """Raised when every attempt under the policy failed."""

    def __init__(self, attempts: int, last_exception: BaseException) -> None:
        super().__init__(
            f"retry exhausted after {attempts} attempts; "
            f"last error: {type(last_exception).__name__}: {last_exception}"
        )
        self.attempts = attempts
        self.last_exception = last_exception


def call_with_backoff(
    fn: Callable[[], T],
    policy: BackoffPolicy,
    is_retryable: Callable[[BaseException], bool] = lambda e: True,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call ``fn`` with exponential backoff.

    ``is_retryable`` lets callers opt out of retrying non-transient errors
    (e.g. parsing errors). ``sleep`` is injectable so tests can run without
    real sleeps.
    """
    last: BaseException | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return fn()
        except BaseException as e:  # noqa: BLE001 — we re-raise at the end
            last = e
            if not is_retryable(e):
                raise
            if attempt >= policy.max_attempts:
                break
            sleep(policy.delay_for_attempt(attempt))
    assert last is not None
    raise RetryExhausted(policy.max_attempts, last)
