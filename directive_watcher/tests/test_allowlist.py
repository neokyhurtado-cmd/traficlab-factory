"""Tests for the allowlist + protected-boundary gate."""
from __future__ import annotations

import pytest

from directive_watcher.allowlist import (
    AllowlistConfig,
    GateError,
    ProtectedBoundaryRequest,
    author_in_allowlist,
    evaluate_protected_boundary,
    repo_in_allowlist,
)
from directive_watcher.directive_parser import Directive, parse_directive


def _make_directive(**overrides) -> Directive:
    """Build a parsed Directive directly via the parser to keep tests close
    to the real contract."""
    body = (
        "[ASTRA_DIRECTIVE:v1]\n"
        "ACTION = CONTINUE\n"
        "REPOSITORY = neokyhurtado-cmd/traficlab-factory\n"
        "ISSUE = 18\n"
        "TARGET_BRANCH = AUTO_FROM_ISSUE_CONTEXT\n"
        "EXPECTED_HEAD = NONE\n"
        "SCOPE = test\n"
        "AUTO_NEXT_SAFE_GATE = YES\n"
        "REQUIRES_HUMAN_GO_REAL = NO\n"
        "DIRECTIVE_ID = d-1\n"
    )
    d = parse_directive(body)
    assert d is not None
    for k, v in overrides.items():
        object.__setattr__(d, k, v)  # directives are frozen; test-only override
    return d


# --- allowlist membership ---------------------------------------------------


def test_repo_in_allowlist_passes_when_listed():
    allowlist = AllowlistConfig(
        allowlisted_repos=frozenset({"neokyhurtado-cmd/traficlab-factory"}),
        allowlisted_authors=frozenset(),
    )
    d = _make_directive()
    assert repo_in_allowlist(d, allowlist) is True


def test_repo_outside_allowlist_denied():
    """An unknown repo must NEVER execute — even from an authorized author."""
    allowlist = AllowlistConfig(
        allowlisted_repos=frozenset({"neokyhurtado-cmd/traficlab-factory"}),
        allowlisted_authors=frozenset({"astra"}),
    )
    d = _make_directive(repository="somebody-else/repo")
    assert repo_in_allowlist(d, allowlist) is False


def test_repo_allowlist_is_case_sensitive_on_repo():
    """GitHub repo names are case-sensitive; case-only differences are NOT
    matches. This prevents alias-confusion attacks."""
    allowlist = AllowlistConfig(
        allowlisted_repos=frozenset({"neokyhurtado-cmd/traficlab-factory"}),
        allowlisted_authors=frozenset(),
    )
    d = _make_directive(repository="neokyhurtado-cmd/TraficLab-Factory")
    assert repo_in_allowlist(d, allowlist) is False


def test_author_in_allowlist_passes_when_listed():
    allowlist = AllowlistConfig(
        allowlisted_repos=frozenset(),
        allowlisted_authors=frozenset({"neokyhurtado-cmd"}),
    )
    assert author_in_allowlist("neokyhurtado-cmd", allowlist) is True


def test_author_in_allowlist_is_case_insensitive_on_author():
    allowlist = AllowlistConfig(
        allowlisted_repos=frozenset(),
        allowlisted_authors=frozenset({"NeokyHurtado-cmd"}),
    )
    assert author_in_allowlist("neokyhurtado-cmd", allowlist) is True


def test_author_outside_allowlist_denied():
    allowlist = AllowlistConfig(
        allowlisted_repos=frozenset({"neokyhurtado-cmd/traficlab-factory"}),
        allowlisted_authors=frozenset({"neokyhurtado-cmd"}),
    )
    assert author_in_allowlist("someone-else", allowlist) is False


def test_empty_allowlists_deny_everything():
    allowlist = AllowlistConfig()
    d = _make_directive()
    assert repo_in_allowlist(d, allowlist) is False
    assert author_in_allowlist("anyone", allowlist) is False


# --- protected-boundary gate ----------------------------------------------


def test_no_protected_request_denies_execution_but_wakes():
    d = _make_directive(requires_human_go_real=False)
    v = evaluate_protected_boundary(d, request=None)
    assert v.wake_allowed is True
    assert v.execution_allowed is False


def test_protected_request_without_directive_flag_denies_execution():
    """A protected-boundary request on a directive that did not declare
    REQUIRES_HUMAN_GO_REAL = YES must wake but NOT execute."""
    d = _make_directive(requires_human_go_real=False)
    request = ProtectedBoundaryRequest(
        kind="MERGE_PROTECTED",
        repository=d.repository,
        evidence_token="some-token",
    )
    v = evaluate_protected_boundary(d, request)
    assert v.wake_allowed is True
    assert v.execution_allowed is False
    assert "REQUIRES_HUMAN_GO_REAL" in v.reason


def test_protected_request_with_directive_flag_still_does_not_auto_execute():
    """Even with the directive flag set, this ticket NEVER auto-executes
    a protected action. The gate is presented; David owns the actual
    authorisation. The watcher posts a HUMAN_GO_REAL_REQUIRED result."""
    d = _make_directive(requires_human_go_real=True)
    request = ProtectedBoundaryRequest(
        kind="MERGE_PROTECTED",
        repository=d.repository,
        evidence_token="hgr-2026-09-11-david-token",
    )
    v = evaluate_protected_boundary(d, request)
    assert v.wake_allowed is True
    assert v.execution_allowed is False  # never auto
    assert "HUMAN_GO_REAL" in v.reason


def test_unknown_protected_kind_raises():
    d = _make_directive()
    request = ProtectedBoundaryRequest(
        kind="NUKE_FROM_ORBIT",
        repository=d.repository,
        evidence_token="x",
    )
    with pytest.raises(GateError):
        evaluate_protected_boundary(d, request)


def test_protected_request_without_evidence_token_raises():
    d = _make_directive(requires_human_go_real=True)
    request = ProtectedBoundaryRequest(
        kind="MERGE_PROTECTED",
        repository=d.repository,
        evidence_token="   ",
    )
    with pytest.raises(GateError):
        evaluate_protected_boundary(d, request)
