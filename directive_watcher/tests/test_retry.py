"""Tests for the retry/backoff helpers."""
from __future__ import annotations

import pytest

from directive_watcher.retry import (
    BackoffPolicy,
    RetryExhausted,
    call_with_backoff,
)


def test_first_attempt_success_no_sleep(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr("directive_watcher.retry.time.sleep",
                        lambda s: sleeps.append(s))
    result = call_with_backoff(lambda: "ok", BackoffPolicy())
    assert result == "ok"
    assert sleeps == []


def test_retry_until_success():
    attempts = {"n": 0}
    sleeps: list[float] = []

    def op():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("transient")
        return "ok"

    result = call_with_backoff(
        op,
        BackoffPolicy(initial_seconds=0.01, factor=2.0, max_attempts=5),
        sleep=lambda s: sleeps.append(s),
    )
    assert result == "ok"
    assert attempts["n"] == 3
    assert len(sleeps) == 2  # slept between attempts 1→2 and 2→3


def test_retry_exhausted_raises_last_exception():
    def op():
        raise RuntimeError("always fails")

    with pytest.raises(RetryExhausted) as exc:
        call_with_backoff(
            op,
            BackoffPolicy(initial_seconds=0.01, max_attempts=3),
            sleep=lambda s: None,
        )
    assert exc.value.attempts == 3
    assert isinstance(exc.value.last_exception, RuntimeError)


def test_non_retryable_error_does_not_retry():
    attempts = {"n": 0}

    def op():
        attempts["n"] += 1
        raise ValueError("permanent")

    with pytest.raises(ValueError):
        call_with_backoff(
            op,
            BackoffPolicy(initial_seconds=0.01, max_attempts=5),
            is_retryable=lambda e: not isinstance(e, ValueError),
            sleep=lambda s: None,
        )
    assert attempts["n"] == 1


def test_backoff_policy_caps_delay():
    policy = BackoffPolicy(
        initial_seconds=1.0, factor=10.0, max_seconds=5.0, max_attempts=10
    )
    assert policy.delay_for_attempt(1) <= 5.0
    assert policy.delay_for_attempt(8) <= 5.0
    # And it's still positive.
    assert policy.delay_for_attempt(1) > 0


def test_backoff_policy_zero_jitter_is_deterministic():
    policy = BackoffPolicy(
        initial_seconds=1.0, factor=2.0, max_seconds=10.0,
        jitter_ratio=0.0, max_attempts=10,
    )
    assert policy.delay_for_attempt(1) == 1.0
    assert policy.delay_for_attempt(2) == 2.0
    assert policy.delay_for_attempt(3) == 4.0
