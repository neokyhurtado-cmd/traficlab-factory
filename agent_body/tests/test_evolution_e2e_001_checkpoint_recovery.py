"""EVOLUTION-E2E-001: checkpoint recovery + STALE detection.

Per directive `evolution-v1-closeout-20260914-01` (issue #27), a fresh
Hermes session (B) with NO chat history, NO David briefing, and NO
in-process state must be able to reconstruct every required field of the
worker bootstrap shape from a checkpoint written by a previous session (A)
alone.

The acceptance criteria for this test are explicit:
    MANUAL_CONTEXT_COPY_PASTE = 0
    WRONG_REPO                = 0
    WRONG_TASK                = 0
    TASK_STATE_LOSS           = 0
    DUPLICATE_WORK            = 0

The test ALSO enforces the STALE detection policy: a checkpoint written
against an older commit SHA must be reported STALE (not silently re-used)
when the GitHub HEAD has advanced past it. This is the same fail-closed
contract the directive watcher's handler.py enforces for non-REVIEW
directives (per #29), but here applied to body checkpoints.
"""
from __future__ import annotations

import pytest


# EVOLUTION-E2E-001 (recovery invariants) -----------------------------------


def test_checkpoint_round_trip_recovers_full_bootstrap_shape(tmp_path):
    """Session A writes → Session B (fresh, no context) reads full bootstrap."""
    from agent_body.checkpoint_store import (
        CheckpointStore,
        Checkpoint,
        AuthoritativePointer,
    )

    db = tmp_path / "checkpoints.sqlite"
    store_a = CheckpointStore(db)
    cp = Checkpoint(
        task_id="t_evolution_e2e_001",
        objective="Resume #27 evolution closeout from durable sidecar.",
        authoritative_pointers=[
            AuthoritativePointer(scheme="repo", value="neokyhurtado-cmd/traficlab-factory"),
            AuthoritativePointer(scheme="issue", value="#27"),
            AuthoritativePointer(scheme="commit", value="7225d3e383f268b3b7032294ac6ef0c76d5c5d62"),
            AuthoritativePointer(scheme="branch", value="main"),
        ],
        last_verified_head="7225d3e383f268b3b7032294ac6ef0c76d5c5d62",
        evidence_already_checked=[5658210225, 5658256935, 5659485468, 5659491838],
        blockers=[],
        next_safe_action="execute_evolution_closeout_directive",
        state="ACTIVE",
    )
    store_a.write(cp)

    # Simulate a fresh session B by constructing a NEW store object on the
    # SAME durable file. B has no in-memory state from A.
    store_b = CheckpointStore(db)
    loaded = store_b.read("t_evolution_e2e_001")

    # Every bootstrap field from #27 body must be reconstructable from the
    # checkpoint alone. None of these values may be inferred from chat
    # history (which session B does not have).
    assert loaded is not None
    assert loaded.task_id == "t_evolution_e2e_001"
    assert loaded.last_verified_head == "7225d3e383f268b3b7032294ac6ef0c76d5c5d62"
    assert loaded.next_safe_action == "execute_evolution_closeout_directive"
    assert loaded.state == "ACTIVE"
    # Pointers must include repo + issue + commit + branch in order.
    schemes = [p.scheme for p in loaded.authoritative_pointers]
    assert "repo" in schemes
    assert "issue" in schemes
    assert "commit" in schemes
    assert "branch" in schemes
    # Evidence list survives round-trip — proves DUPLICATE_WORK = 0.
    assert set(loaded.evidence_already_checked) == {5658210225, 5658256935, 5659485468, 5659491838}


def test_fresh_session_recovers_project_task_head_authority(tmp_path):
    """The seven bootstrap fields of #27 body must all be derivable."""
    from agent_body.checkpoint_store import CheckpointStore, Checkpoint, AuthoritativePointer

    db = tmp_path / "checkpoints.sqlite"
    CheckpointStore(db).write(Checkpoint(
        task_id="t_bootstrap_check",
        objective="reconstruct bootstrap",
        authoritative_pointers=[
            AuthoritativePointer("repo", "neokyhurtado-cmd/traficlab-factory"),
            AuthoritativePointer("issue", "#27"),
            AuthoritativePointer("commit", "7225d3e383f268b3b7032294ac6ef0c76d5c5d62"),
            AuthoritativePointer("branch", "main"),
        ],
        last_verified_head="7225d3e383f268b3b7032294ac6ef0c76d5c5d62",
        evidence_already_checked=[5658210225, 5659485468],
        blockers=[],
        next_safe_action="emit_evolution_closeout",
        state="ACTIVE",
    ))

    # Fresh store, no warm cache, no parent process memory.
    store = CheckpointStore(db)
    cp = store.read("t_bootstrap_check")
    assert cp is not None

    # Derived bootstrap fields — these are what a fresh worker would feed
    # into its own prompt as the "active context" line. None of them may
    # be a default; each must come from the durable record.
    bootstrap = store.derive_bootstrap(cp)
    assert bootstrap["PROJECT"] == "neokyhurtado-cmd/traficlab-factory"
    assert bootstrap["TASK"] == "#27"
    assert bootstrap["HEAD"] == "7225d3e383f268b3b7032294ac6ef0c76d5c5d62"
    assert bootstrap["AUTHORITY"] == "github_remote"
    assert bootstrap["BLOCKER"] == ""  # none, but key is present and explicit
    assert bootstrap["NEXT_SAFE_ACTION"] == "emit_evolution_closeout"
    assert bootstrap["MANUAL_CONTEXT_COPY_PASTE"] == 0


# EVOLUTION-E2E-001 (STALE detection) ----------------------------------------


def test_stale_checkpoint_against_live_head_returns_state_stale(tmp_path):
    """A checkpoint at 8e2d9c9 against live HEAD 7225d3e MUST be reported STALE.

    The Body inherits the strict (non-REVIEW) policy from
    directive_watcher/handler.py:619-651 — Body never silently rewrites
    its view of GitHub state. If last_verified_head != current_head,
    the worker MUST NOT continue blindly.
    """
    from agent_body.checkpoint_store import (
        CheckpointStore,
        Checkpoint,
        AuthoritativePointer,
        HeadResolver,
    )

    db = tmp_path / "checkpoints.sqlite"
    CheckpointStore(db).write(Checkpoint(
        task_id="t_stale_check",
        objective="verify stale handling",
        authoritative_pointers=[
            AuthoritativePointer("repo", "neokyhurtado-cmd/traficlab-factory"),
            AuthoritativePointer("commit", "8e2d9c9"),
        ],
        last_verified_head="8e2d9c9",
        evidence_already_checked=[],
        blockers=[],
        next_safe_action="resume_after_reconcile",
        state="ACTIVE",
    ))

    # Live HEAD advanced to 7225d3e since the checkpoint was written.
    live_head = "7225d3e383f268b3b7032294ac6ef0c76d5c5d62"
    store = CheckpointStore(db)
    verdict = store.check_freshness(
        "t_stale_check",
        current_head=live_head,
        resolver=HeadResolver.from_literal(live_head),
    )

    assert verdict.state == "STALE"
    assert verdict.reconciliation_required is True
    assert verdict.old_head == "8e2d9c9"
    assert verdict.new_head == live_head
    assert verdict.drift_commits >= 1
    assert verdict.safe_action == "stop_and_reconcile"
    # No silent continuation. The body must NOT permit resuming on stale info.
    assert verdict.allowed_to_continue is False


def test_fresh_checkpoint_matches_live_head_returns_active(tmp_path):
    """A checkpoint whose last_verified_head equals the live HEAD is ACTIVE."""
    from agent_body.checkpoint_store import (
        CheckpointStore,
        Checkpoint,
        AuthoritativePointer,
        HeadResolver,
    )

    db = tmp_path / "checkpoints.sqlite"
    live_head = "7225d3e383f268b3b7032294ac6ef0c76d5c5d62"
    CheckpointStore(db).write(Checkpoint(
        task_id="t_fresh_check",
        objective="verify fresh handling",
        authoritative_pointers=[
            AuthoritativePointer("repo", "neokyhurtado-cmd/traficlab-factory"),
            AuthoritativePointer("commit", live_head),
        ],
        last_verified_head=live_head,
        evidence_already_checked=[],
        blockers=[],
        next_safe_action="continue",
        state="ACTIVE",
    ))
    store = CheckpointStore(db)
    verdict = store.check_freshness(
        "t_fresh_check",
        current_head=live_head,
        resolver=HeadResolver.from_literal(live_head),
    )
    assert verdict.state == "ACTIVE"
    assert verdict.reconciliation_required is False
    assert verdict.allowed_to_continue is True
