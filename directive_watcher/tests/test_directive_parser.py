"""Tests for the directive parser.

The parser extracts a structured directive from a GitHub comment body.
The envelope must start with the exact marker `[ASTRA_DIRECTIVE:v1]` followed
by `KEY = VALUE` lines. Anything else (free-form prose, missing marker,
duplicate keys, malformed values) must fail closed.
"""
from __future__ import annotations

import pytest

from directive_watcher.directive_parser import (
    Directive,
    DirectiveParseError,
    parse_directive,
)


# --- Happy path ------------------------------------------------------------


def test_parses_minimal_envelope():
    body = (
        "[ASTRA_DIRECTIVE:v1]\n"
        "ACTION = CONTINUE\n"
        "REPOSITORY = neokyhurtado-cmd/traficlab-factory\n"
        "ISSUE = 18\n"
        "TARGET_BRANCH = AUTO_FROM_ISSUE_CONTEXT\n"
        "EXPECTED_HEAD = NONE\n"
        "SCOPE = fix docs typo\n"
        "AUTO_NEXT_SAFE_GATE = YES\n"
        "REQUIRES_HUMAN_GO_REAL = NO\n"
        "DIRECTIVE_ID = dir-2026-09-11-001\n"
    )
    d = parse_directive(body)
    assert d.action == "CONTINUE"
    assert d.repository == "neokyhurtado-cmd/traficlab-factory"
    assert d.issue == 18
    assert d.target_branch == "AUTO_FROM_ISSUE_CONTEXT"
    assert d.expected_head == "NONE"
    assert d.scope == "fix docs typo"
    assert d.auto_next_safe_gate is True
    assert d.requires_human_go_real is False
    assert d.directive_id == "dir-2026-09-11-001"


def test_parses_envelope_with_prose_before_and_after():
    """The parser must locate the envelope inside a comment that also has
    free-form prose. Only the structured block is authoritative."""
    body = (
        "Hola Hermes,\n"
        "please continue work on this.\n\n"
        "[ASTRA_DIRECTIVE:v1]\n"
        "ACTION = REAUDIT_FIX\n"
        "REPOSITORY = neokyhurtado-cmd/suini\n"
        "ISSUE = 7\n"
        "TARGET_BRANCH = feat/suini-fix\n"
        "EXPECTED_HEAD = abc123\n"
        "SCOPE = re-run audit\n"
        "AUTO_NEXT_SAFE_GATE = NO\n"
        "REQUIRES_HUMAN_GO_REAL = YES\n"
        "DIRECTIVE_ID = dir-2026-09-11-002\n\n"
        "Thanks!\n"
    )
    d = parse_directive(body)
    assert d.action == "REAUDIT_FIX"
    assert d.repository == "neokyhurtado-cmd/suini"
    assert d.expected_head == "abc123"
    assert d.auto_next_safe_gate is False
    assert d.requires_human_go_real is True


def test_parses_boolean_variants():
    """YES/NO, yes/no, true/false, 1/0 are all valid boolean spellings."""
    body = (
        "[ASTRA_DIRECTIVE:v1]\n"
        "ACTION = TEST\n"
        "REPOSITORY = r/o\n"
        "ISSUE = 1\n"
        "TARGET_BRANCH = AUTO_FROM_ISSUE_CONTEXT\n"
        "EXPECTED_HEAD = NONE\n"
        "SCOPE = x\n"
        "AUTO_NEXT_SAFE_GATE = yes\n"
        "REQUIRES_HUMAN_GO_REAL = false\n"
        "DIRECTIVE_ID = d-1\n"
    )
    d = parse_directive(body)
    assert d.auto_next_safe_gate is True
    assert d.requires_human_go_real is False


# --- Fail-closed ------------------------------------------------------------


def test_missing_marker_returns_no_directive():
    """A comment without the exact marker is information-only."""
    body = (
        "Just chatting, no directive here.\n"
        "ACTION = CONTINUE\n"
    )
    assert parse_directive(body) is None


def test_wrong_marker_version_returns_no_directive():
    """A different version marker must be ignored (not a parse error)."""
    body = (
        "[ASTRA_DIRECTIVE:v2]\n"
        "ACTION = CONTINUE\n"
        "DIRECTIVE_ID = d-1\n"
    )
    assert parse_directive(body) is None


def test_empty_body_returns_none():
    assert parse_directive("") is None
    assert parse_directive("\n\n") is None


def test_marker_without_required_keys_raises():
    """Marker present but missing required fields → fail closed."""
    body = (
        "[ASTRA_DIRECTIVE:v1]\n"
        "ACTION = CONTINUE\n"
        "DIRECTIVE_ID = d-1\n"
    )
    with pytest.raises(DirectiveParseError) as exc:
        parse_directive(body)
    assert "REPOSITORY" in str(exc.value)


def test_unknown_action_raises():
    body = (
        "[ASTRA_DIRECTIVE:v1]\n"
        "ACTION = NUKE\n"
        "REPOSITORY = r/o\n"
        "ISSUE = 1\n"
        "TARGET_BRANCH = b\n"
        "EXPECTED_HEAD = NONE\n"
        "SCOPE = x\n"
        "AUTO_NEXT_SAFE_GATE = NO\n"
        "REQUIRES_HUMAN_GO_REAL = YES\n"
        "DIRECTIVE_ID = d-1\n"
    )
    with pytest.raises(DirectiveParseError) as exc:
        parse_directive(body)
    assert "ACTION" in str(exc.value)


def test_invalid_boolean_raises():
    body = (
        "[ASTRA_DIRECTIVE:v1]\n"
        "ACTION = CONTINUE\n"
        "REPOSITORY = r/o\n"
        "ISSUE = 1\n"
        "TARGET_BRANCH = b\n"
        "EXPECTED_HEAD = NONE\n"
        "SCOPE = x\n"
        "AUTO_NEXT_SAFE_GATE = MAYBE\n"
        "REQUIRES_HUMAN_GO_REAL = YES\n"
        "DIRECTIVE_ID = d-1\n"
    )
    with pytest.raises(DirectiveParseError):
        parse_directive(body)


def test_issue_must_be_integer():
    body = (
        "[ASTRA_DIRECTIVE:v1]\n"
        "ACTION = CONTINUE\n"
        "REPOSITORY = r/o\n"
        "ISSUE = not-a-number\n"
        "TARGET_BRANCH = b\n"
        "EXPECTED_HEAD = NONE\n"
        "SCOPE = x\n"
        "AUTO_NEXT_SAFE_GATE = NO\n"
        "REQUIRES_HUMAN_GO_REAL = YES\n"
        "DIRECTIVE_ID = d-1\n"
    )
    with pytest.raises(DirectiveParseError):
        parse_directive(body)


def test_directive_id_must_be_non_empty():
    body = (
        "[ASTRA_DIRECTIVE:v1]\n"
        "ACTION = CONTINUE\n"
        "REPOSITORY = r/o\n"
        "ISSUE = 1\n"
        "TARGET_BRANCH = b\n"
        "EXPECTED_HEAD = NONE\n"
        "SCOPE = x\n"
        "AUTO_NEXT_SAFE_GATE = NO\n"
        "REQUIRES_HUMAN_GO_REAL = YES\n"
        "DIRECTIVE_ID = \n"
    )
    with pytest.raises(DirectiveParseError):
        parse_directive(body)


def test_directive_immutable_after_parse():
    """A parsed Directive must be a frozen record (no accidental mutation)."""
    body = (
        "[ASTRA_DIRECTIVE:v1]\n"
        "ACTION = CONTINUE\n"
        "REPOSITORY = r/o\n"
        "ISSUE = 1\n"
        "TARGET_BRANCH = b\n"
        "EXPECTED_HEAD = NONE\n"
        "SCOPE = x\n"
        "AUTO_NEXT_SAFE_GATE = NO\n"
        "REQUIRES_HUMAN_GO_REAL = YES\n"
        "DIRECTIVE_ID = d-1\n"
    )
    d = parse_directive(body)
    with pytest.raises(Exception):
        d.directive_id = "other"  # type: ignore[misc]
