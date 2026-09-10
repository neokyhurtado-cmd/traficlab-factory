#!/usr/bin/env python3
"""
test_eligibility.py — Unit tests for the eligibility gate.

Covers the six required cases from SUINI#35.AD-2:
  1. Happy path: ready task with valid assignee -> allowed.
  2. Missing assignee -> denial, E1.
  3. Unknown profile (assignee="phantom") -> denial, E2.
  4. Product mismatch (resolver_out.allowed=False) -> denial, E3.
  5. Ashley non-READ_ONLY -> denial, E6.
  6. Cap exceeded (mock _cap_exceeded == True) -> deferred (NOT denied),
     E4/E5.

Plus a few defensive cases:
  - Event payload shape matches the §5 contract exactly.
  - The resolver's denial_reason is preserved when the resolver denies
    (not silently rewritten).
  - The hook is callable from a one-liner (AC-4).

Run with:
    python -m pytest ~/.hermes/profiles/orchestrator/scripts/test_eligibility.py -v
"""

from __future__ import annotations

import os
import sys

import pytest

# Make sure co-located modules are importable regardless of CWD.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import eligibility  # noqa: E402
import routing_resolver  # noqa: E402


# --- Fixtures ---------------------------------------------------------------

@pytest.fixture
def allowed_resolver_out():
    """A permissive RouteDecision that resolves to SUINI/orchestrator."""
    return routing_resolver.RouteDecision(
        allowed=True,
        assignee="orchestrator",
        product="SUINI",
        capabilities=["write"],
    )


@pytest.fixture
def ashley_resolver_out():
    """A permissive RouteDecision that resolves to ASHLEY/default (read-only)."""
    return routing_resolver.RouteDecision(
        allowed=True,
        assignee="default",
        product="ASHLEY",
        capabilities=["read"],
        max_runtime_seconds=1800,
    )


@pytest.fixture
def denied_resolver_out():
    """A denied RouteDecision (mirrors what the resolver would emit on
    a task_assignee mismatch)."""
    return routing_resolver.RouteDecision(
        allowed=False,
        assignee="orchestrator",
        product="SUINI",
        denial_reason="PRODUCT_OWNERSHIP_MISMATCH: assignee=default product=SUINI expected=orchestrator",
    )


@pytest.fixture
def on_disk():
    """The set of profiles the dispatcher considers ON_DISK in the test world."""
    return {"orchestrator", "default"}


# --- Case 1: happy path -----------------------------------------------------

def test_happy_path_valid_assignee_allowed(allowed_resolver_out, on_disk):
    task = {"id": "t_1", "assignee": "orchestrator", "repo": "neokyhurtado-cmd/suini"}
    result = eligibility.check(task, allowed_resolver_out, on_disk)
    assert result.allowed is True
    assert result.deferred is False
    assert result.denial_reason is None
    assert result.event_payload is None
    # All six checks should have run (E4/E5 are no-ops when not capped).
    assert result.checked == ["E1", "E2", "E3", "E4", "E5", "E6"]


# --- Case 2: missing assignee -> E1 denial ---------------------------------

def test_missing_assignee_denied_e1(allowed_resolver_out, on_disk):
    task = {"id": "t_2", "repo": "neokyhurtado-cmd/suini"}  # no assignee
    result = eligibility.check(task, allowed_resolver_out, on_disk)
    assert result.allowed is False
    assert result.deferred is False
    assert result.denial_reason is not None
    # E1 sub-tag uses the locked PRODUCT_OWNERSHIP_MISMATCH prefix.
    assert result.denial_reason.startswith("PRODUCT_OWNERSHIP_MISMATCH")
    assert "missing_assignee" in result.denial_reason
    # E1 failure short-circuits — no later checks should have run.
    assert result.checked == ["E1"]
    # Event payload is shaped per the contract.
    assert result.event_payload is not None
    assert result.event_payload["kind"] == "WO_ROUTING_DENIED"
    assert result.event_payload["task_id"] == "t_2"
    assert result.event_payload["context"]["assignee"] is None


def test_blank_assignee_denied_e1(allowed_resolver_out, on_disk):
    # Whitespace-only assignee must also trip E1.
    task = {"id": "t_2b", "assignee": "   ", "repo": "neokyhurtado-cmd/suini"}
    result = eligibility.check(task, allowed_resolver_out, on_disk)
    assert result.allowed is False
    assert result.checked == ["E1"]
    assert "missing_assignee" in result.denial_reason


# --- Case 3: unknown profile -> E2 denial -----------------------------------

def test_unknown_assignee_denied_e2(allowed_resolver_out, on_disk):
    task = {"id": "t_3", "assignee": "phantom", "repo": "neokyhurtado-cmd/suini"}
    result = eligibility.check(task, allowed_resolver_out, on_disk)
    assert result.allowed is False
    assert result.deferred is False
    assert result.denial_reason == "ASSIGNEE_NOT_ON_DISK"
    # E1 passed (assignee was set), E2 failed (not on disk).
    assert result.checked == ["E1", "E2"]
    # Event payload uses the contract reason verbatim.
    assert result.event_payload is not None
    assert result.event_payload["reason"] == "ASSIGNEE_NOT_ON_DISK"
    assert result.event_payload["context"]["assignee"] == "phantom"


# --- Case 4: product mismatch -> E3 denial ---------------------------------

def test_product_mismatch_denied_e3(denied_resolver_out, on_disk):
    task = {"id": "t_4", "assignee": "default", "repo": "neokyhurtado-cmd/suini"}
    result = eligibility.check(task, denied_resolver_out, on_disk)
    assert result.allowed is False
    assert result.deferred is False
    # The resolver's exact denial_reason is preserved (so the operator
    # sees "expected=orchestrator", not a generic rewrite).
    assert result.denial_reason == (
        "PRODUCT_OWNERSHIP_MISMATCH: assignee=default product=SUINI expected=orchestrator"
    )
    # E1 + E2 + E3 ran; later checks did not.
    assert result.checked == ["E1", "E2", "E3"]
    # Event payload reflects the resolver's product / assignee so the
    # operator can see what the table says.
    assert result.event_payload["reason"] == (
        "PRODUCT_OWNERSHIP_MISMATCH: assignee=default product=SUINI expected=orchestrator"
    )
    assert result.event_payload["context"]["product"] == "SUINI"


# --- Case 5: Ashley non-READ_ONLY -> E6 denial ------------------------------

def test_ashley_non_read_only_denied_e6(ashley_resolver_out, on_disk):
    task = {
        "id": "t_5",
        "assignee": "default",
        "repo": None,  # ASHLEY routes are repo-less
        "body": {},    # no READ_ONLY flag
    }
    result = eligibility.check(task, ashley_resolver_out, on_disk)
    assert result.allowed is False
    assert result.deferred is False
    assert result.denial_reason == "ASHLEY_SCOPE_VIOLATION"
    # E1/E2/E3/E4/E5 passed (Ashley's product + default assignee is valid),
    # E6 caught the missing READ_ONLY flag.
    assert result.checked == ["E1", "E2", "E3", "E4", "E5", "E6"]
    assert result.event_payload["reason"] == "ASHLEY_SCOPE_VIOLATION"
    assert result.event_payload["context"]["product"] == "ASHLEY"


def test_ashley_read_only_allowed(ashley_resolver_out, on_disk):
    # Counter-case: Ashley WITH READ_ONLY flag must pass.
    task = {
        "id": "t_5b",
        "assignee": "default",
        "repo": None,
        "body": {"READ_ONLY": True},
    }
    result = eligibility.check(task, ashley_resolver_out, on_disk)
    assert result.allowed is True
    assert result.denial_reason is None


def test_ashley_read_only_in_body_string_allowed(ashley_resolver_out, on_disk):
    # READ_ONLY marker embedded in body text also passes E6 (the
    # dispatcher creates tasks with the flag in different shapes).
    task = {
        "id": "t_5c",
        "assignee": "default",
        "repo": None,
        "body": {"body": "Some task description.\nREAD_ONLY: true\nEnd."},
    }
    result = eligibility.check(task, ashley_resolver_out, on_disk)
    assert result.allowed is True


# --- Case 6: cap exceeded -> DEFERRED (not denied) -------------------------

def test_cap_exceeded_deferred_not_denied(allowed_resolver_out, on_disk):
    task = {
        "id": "t_6",
        "assignee": "orchestrator",
        "repo": "neokyhurtado-cmd/suini",
        "_cap_exceeded": True,  # set by the dispatcher's cap checker
    }
    result = eligibility.check(task, allowed_resolver_out, on_disk)
    # Cap is a defer, NOT a denial — allowed=False but deferred=True.
    assert result.allowed is False
    assert result.deferred is True
    assert result.denial_reason is None
    # No event payload: cap is NOT an event per §4.
    assert result.event_payload is None
    # E1/E2/E3 ran; the cap defer short-circuits at E5 (E4+E5 are a
    # single "cap" decision). E6 doesn't run because the task is being
    # deferred, not denied — Ashley scope is checked only on tasks that
    # would otherwise proceed to spawn.
    assert result.checked == ["E1", "E2", "E3", "E4", "E5"]


# --- Defensive: event payload shape matches §5 exactly ---------------------

def test_event_payload_matches_contract(allowed_resolver_out, on_disk):
    task = {"id": "t_evt", "assignee": "phantom", "repo": "neokyhurtado-cmd/suini"}
    result = eligibility.check(task, allowed_resolver_out, on_disk)
    assert result.event_payload is not None
    # §5 contract:
    #   { "kind": "WO_ROUTING_DENIED",
    #     "task_id": "<id>",
    #     "reason": "<PRODUCT_OWNERSHIP_MISMATCH|ASSIGNEE_NOT_ON_DISK|
    #                 ALREADY_CLAIMED|UNKNOWN_REPO|ASHLEY_SCOPE_VIOLATION>",
    #     "context": {"repo": ..., "assignee": ..., "product": ...} }
    assert result.event_payload["kind"] == "WO_ROUTING_DENIED"
    assert result.event_payload["task_id"] == "t_evt"
    assert result.event_payload["reason"] == "ASSIGNEE_NOT_ON_DISK"
    assert set(result.event_payload["context"].keys()) == {"repo", "assignee", "product"}


# --- Defensive: resolver denial_reason is preserved ------------------------

def test_resolver_denial_reason_preserved_through_e3(denied_resolver_out, on_disk):
    task = {"id": "t_resolver_msg", "assignee": "default", "repo": "neokyhurtado-cmd/suini"}
    result = eligibility.check(task, denied_resolver_out, on_disk)
    # The resolver's specific message is the gate's denial_reason — we
    # don't silently rewrite it. This is the contract: routing-table
    # failures surface verbatim so the operator sees the exact expected
    # assignee.
    assert result.denial_reason == denied_resolver_out.denial_reason


# --- Defensive: None resolver -> skipped, not denied ----------------------

def test_none_resolver_skips_e3_and_e6(on_disk):
    # Per the contract, ``check()`` accepts ``resolver_out=None`` to mean
    # "the resolver wasn't applicable / didn't run" — it skips E3 (and
    # the resolver-dependent part of E6) rather than denying. This is
    # the one-liner smoke behaviour: ``check({'assignee':'orchestrator'},
    # None, {'orchestrator'})`` returns allowed=True. The production
    # hook ALWAYS supplies a real resolver (or a denial-shaped sentinel
    # when the resolver raised) so production denials still flow.
    task = {"id": "t_no_resolver", "assignee": "orchestrator", "repo": "neokyhurtado-cmd/suini"}
    result = eligibility.check(task, None, on_disk)
    assert result.allowed is True
    # E3 ran (it's appended unconditionally for telemetry), but its
    # denial branch is what gets skipped.
    assert result.checked == ["E1", "E2", "E3", "E4", "E5", "E6"]


def test_denied_resolver_sentinel_still_denies(on_disk):
    # The hook synthesises a denial-shaped sentinel when the real
    # resolver raises (FileNotFoundError etc). Confirm the gate still
    # produces a structured denial for that case.
    class _Sentinel:
        allowed = False
        denial_reason = "PRODUCT_OWNERSHIP_MISMATCH: resolver_error=FileNotFoundError"
        assignee = None
        product = None
        capabilities = []

    task = {"id": "t_sentinel", "assignee": "orchestrator", "repo": "neokyhurtado-cmd/suini"}
    result = eligibility.check(task, _Sentinel(), on_disk)
    assert result.allowed is False
    assert result.denial_reason == (
        "PRODUCT_OWNERSHIP_MISMATCH: resolver_error=FileNotFoundError"
    )
    # E3 fired the denial — later checks did not.
    assert result.checked == ["E1", "E2", "E3"]


# --- AC-4: hook is callable from a one-liner -------------------------------

def test_hook_one_liner_callable(allowed_resolver_out, on_disk, monkeypatch):
    # The hook's pre_spawn_check is the canonical one-liner call site.
    # Test that the import statement in the task body works without
    # the dispatcher context.
    import eligibility_hook  # noqa: F401
    assert hasattr(eligibility_hook, "pre_spawn_check")
    # Direct invocation (we monkeypatch the on-disk fetcher so the test
    # doesn't shell out to the hermes CLI).
    from eligibility_hook import pre_spawn_check
    import eligibility_hook as eh

    monkeypatch.setattr(eh, "_load_assignees_on_disk", lambda: frozenset(on_disk))
    # Also stub the resolver: the hook calls _resolve, which delegates
    # to routing_resolver.resolve_route. That call hits disk (reads
    # routing.yaml), which is fine because the test runs in the
    # orchestrator profile where the file exists. We don't need to
    # monkeypatch it.
    #
    # AUTO_DISPATCH_02: with the routing table now pointing SUINI at the
    # real `suini` profile, an `assignee=orchestrator` claim for a suini
    # issue is a legitimate PRODUCT_OWNERSHIP_MISMATCH — exactly the
    # behaviour we want. We exercise that branch here so the test
    # surfaces it instead of papering over it.

    task = {"id": "t_one_liner", "assignee": "orchestrator", "repo": "neokyhurtado-cmd/suini"}
    result = pre_spawn_check(task)
    assert result.allowed is False
    assert result.denial_reason is not None
    assert result.denial_reason.startswith("PRODUCT_OWNERSHIP_MISMATCH")
    # Event payload is shaped per the §5 contract.
    assert result.event_payload is not None
    assert result.event_payload["kind"] == "WO_ROUTING_DENIED"
    assert result.event_payload["task_id"] == "t_one_liner"
