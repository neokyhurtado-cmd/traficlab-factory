"""Tests for Fix #5 — retry classification of gh errors.

The Astra re-audit flagged that Phase 1 retried only
``ConnectionError / TimeoutError``. In production, ``gh`` exits with
non-zero codes for many reasons: HTTP 5xx, HTTP 4xx, rate limits,
auth failures. The retry policy must classify them correctly:

  - 4xx (401, 403, 404, 422) → MUST NOT retry (same auth/perm state
    will just produce the same 4xx; retrying wastes budget)
  - 5xx + 429 → MUST retry
  - ConnectionError / TimeoutError → MUST retry
  - Anything else non-zero → default retry (best-effort, bounded by
    max_attempts so it can't loop forever)
"""
from __future__ import annotations

import pytest

from directive_watcher.gh_client import (
    GHCLIError,
    GHCLINonRetryableError,
    GHCLIRateLimitError,
)
from directive_watcher.handler import _is_retryable
from directive_watcher.retry import BackoffPolicy, RetryExhausted, call_with_backoff


# ---------- GHCLIError classification ---------------------------------------


def test_5xx_503_is_retryable():
    e = GHCLIError("boom", exit_code=1, stderr="gh: HTTP 503 Service Unavailable")
    assert e.is_retryable is True


def test_500_is_retryable():
    e = GHCLIError("boom", exit_code=1, stderr="gh: 500 Internal Server Error")
    assert e.is_retryable is True


def test_429_rate_limit_is_retryable():
    e = GHCLIError("rate limited", exit_code=1, stderr="gh: API rate limit exceeded (429)")
    assert e.is_retryable is True


def test_401_unauthorized_is_not_retryable():
    e = GHCLIError("unauthorized", exit_code=1, stderr="gh: HTTP 401 Unauthorized")
    assert e.is_retryable is False


def test_403_forbidden_is_not_retryable():
    e = GHCLIError("forbidden", exit_code=1, stderr="gh: HTTP 403 Forbidden")
    assert e.is_retryable is False


def test_404_not_found_is_not_retryable():
    e = GHCLIError("not found", exit_code=1, stderr="gh: HTTP 404 Not Found")
    assert e.is_retryable is False


def test_422_validation_is_not_retryable():
    e = GHCLIError("unprocessable", exit_code=1, stderr="gh: HTTP 422 Unprocessable Entity")
    assert e.is_retryable is False


def test_exit_code_zero_is_not_retryable():
    e = GHCLIError("garbled", exit_code=0, stderr="")
    assert e.is_retryable is False


def test_unclassified_non_zero_is_retryable():
    """Default: unknown non-zero → retry. Bounded by max_attempts."""
    e = GHCLIError("weird", exit_code=42, stderr="")
    assert e.is_retryable is True


# ---------- _is_retryable integration ---------------------------------------


def test_is_retryable_for_connection_error():
    assert _is_retryable(ConnectionError("nope")) is True


def test_is_retryable_for_timeout():
    assert _is_retryable(TimeoutError("slow")) is True


def test_is_retryable_for_5xx_gh_error():
    e = GHCLIError("503", exit_code=1, stderr="HTTP 503")
    assert _is_retryable(e) is True


def test_is_retryable_for_4xx_gh_error():
    e = GHCLIError("401", exit_code=1, stderr="HTTP 401")
    assert _is_retryable(e) is False


def test_is_retryable_for_unknown_exception_is_false():
    """Random exceptions are NOT retryable — fail-closed."""
    assert _is_retryable(ValueError("bad input")) is False


# ---------- call_with_backoff actually retries only retryable ----------------


def test_call_with_backoff_retries_5xx():
    """A 5xx GHCLIError must trigger retry."""
    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise GHCLIError("503", exit_code=1, stderr="HTTP 503")
        return "ok"

    policy = BackoffPolicy(initial_seconds=0.001, max_attempts=5)
    result = call_with_backoff(flaky, policy=policy, is_retryable=_is_retryable)
    assert result == "ok"
    assert attempts["n"] == 3


def test_call_with_backoff_does_not_retry_4xx():
    """A 4xx GHCLIError must NOT trigger retry — same call returns the error."""
    attempts = {"n": 0}

    def always_401():
        attempts["n"] += 1
        raise GHCLIError("401", exit_code=1, stderr="HTTP 401")

    policy = BackoffPolicy(initial_seconds=0.001, max_attempts=5)
    with pytest.raises(GHCLIError) as exc_info:
        call_with_backoff(always_401, policy=policy, is_retryable=_is_retryable)
    assert "401" in str(exc_info.value)
    assert attempts["n"] == 1, (
        f"4xx must not retry; got {attempts['n']} attempts"
    )


def test_call_with_backoff_does_not_retry_random_exception():
    """Random exceptions fail-closed: no retry."""
    attempts = {"n": 0}

    def boom():
        attempts["n"] += 1
        raise ValueError("not a network error")

    policy = BackoffPolicy(initial_seconds=0.001, max_attempts=5)
    with pytest.raises(ValueError):
        call_with_backoff(boom, policy=policy, is_retryable=_is_retryable)
    assert attempts["n"] == 1


def test_retry_exhausted_after_max_attempts():
    """When all attempts hit retryable errors, RetryExhausted fires."""
    attempts = {"n": 0}

    def always_503():
        attempts["n"] += 1
        raise GHCLIError("503", exit_code=1, stderr="HTTP 503")

    policy = BackoffPolicy(initial_seconds=0.001, max_attempts=3)
    with pytest.raises(RetryExhausted):
        call_with_backoff(always_503, policy=policy, is_retryable=_is_retryable)
    assert attempts["n"] == 3


# ---------- Specific exception subclasses are recognised ---------------------


def test_rate_limit_subclass_is_retryable():
    e = GHCLIRateLimitError("rate limited", exit_code=1, stderr="429")
    assert e.is_retryable is True
    assert _is_retryable(e) is True


def test_non_retryable_subclass_is_not_retryable():
    e = GHCLINonRetryableError("401", exit_code=1, stderr="401")
    assert e.is_retryable is False
    assert _is_retryable(e) is False
