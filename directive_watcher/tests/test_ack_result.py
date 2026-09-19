"""Tests for the ACK and RESULT composers."""
from __future__ import annotations

from directive_watcher.ack_result import (
    ACK_MARKER,
    RESULT_MARKER,
    AckFacts,
    ResultFacts,
    format_ack,
    format_result,
    parse_result_status,
)


def test_ack_includes_required_fields():
    facts = AckFacts(
        directive_id="d-1",
        source_comment_id=123,
        execution_id="exec-123-abcd",
        head_before="abc",
    )
    body = format_ack(facts)
    assert body.startswith(ACK_MARKER)
    assert "DIRECTIVE_ID = d-1" in body
    assert "SOURCE_COMMENT_ID = 123" in body
    assert "EXECUTION_ID = exec-123-abcd" in body
    assert "STATUS = CLAIMED" in body
    assert "HEAD_BEFORE = abc" in body


def test_ack_handles_missing_head_before():
    facts = AckFacts(
        directive_id="d-1",
        source_comment_id=1,
        execution_id="exec-1",
        head_before=None,
    )
    body = format_ack(facts)
    assert "HEAD_BEFORE = NONE" in body


def test_result_includes_required_fields():
    facts = ResultFacts(
        directive_id="d-1",
        execution_id="exec-1",
        source_comment_id=123,
        status="READY_FOR_ASTRA_REAUDIT",
        head_after="def",
        tests="pytest -q: 42 passed",
        evidence="evidence/visual/exec-1/manifest.json",
    )
    body = format_result(facts)
    assert body.startswith(RESULT_MARKER)
    assert "STATUS = READY_FOR_ASTRA_REAUDIT" in body
    assert "HEAD_AFTER = def" in body
    assert "TESTS = pytest -q: 42 passed" in body
    assert "EVIDENCE = evidence/visual/exec-1/manifest.json" in body


def test_result_links_back_to_source_directive_and_execution():
    """Requirement 14: result comment links source comment/directive/execution."""
    facts = ResultFacts(
        directive_id="d-directive",
        execution_id="exec-exec",
        source_comment_id=999,
        status="READY_FOR_ASTRA_REAUDIT",
        head_after="x",
        tests="t",
        evidence="e",
    )
    body = format_result(facts)
    assert "SOURCE_COMMENT_ID = 999" in body
    assert "DIRECTIVE_ID = d-directive" in body
    assert "EXECUTION_ID = exec-exec" in body


def test_parse_result_status_roundtrip():
    body = format_result(ResultFacts(
        directive_id="d", execution_id="e", source_comment_id=1,
        status="BLOCKED_EXTERNAL_REAL", head_after=None, tests="-",
        evidence="-",
    ))
    assert parse_result_status(body) == "BLOCKED_EXTERNAL_REAL"


def test_parse_result_status_returns_none_for_non_result_body():
    assert parse_result_status("hello world") is None
    assert parse_result_status("[HERMES_ACK:v1]") is None
