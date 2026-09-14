"""BODY-1 acceptance tests — checkpoint round-trip + fresh session.

Per AGENT_BODY_27_READONLY_AUDIT.md §9 (BODY-1):
  B1.1 fresh session writes a checkpoint from the manifest alone
  B1.2 checkpoint round-trips across two fresh sessions
  B1.4 AUTHORITY_CONFLICT — precedence map applies without model judgment
"""
from __future__ import annotations

import pytest


def test_fresh_session_writes_checkpoint_from_manifest_only(tmp_path):
    """B1.1 — a session with only the manifest + SKILL.md loaded can
    write a checkpoint without any prior chat transcript."""
    from agent_body.checkpoint_store import CheckpointStore, Checkpoint, AuthoritativePointer

    db = tmp_path / "checkpoints.sqlite"
    store = CheckpointStore(db)
    cp = Checkpoint(
        task_id="t_b1_1",
        objective="B1.1 — bootstrap-only write",
        authoritative_pointers=[
            AuthoritativePointer("repo", "neokyhurtado-cmd/traficlab-factory"),
            AuthoritativePointer("issue", "#27"),
            AuthoritativePointer("commit", "7225d3e383f268b3b7032294ac6ef0c76d5c5d62"),
            AuthoritativePointer("branch", "main"),
        ],
        last_verified_head="7225d3e383f268b3b7032294ac6ef0c76d5c5d62",
        evidence_already_checked=[5658210225, 5659485468, 5659491838],
        blockers=[],
        next_safe_action="execute_directive",
        state="ACTIVE",
    )
    store.write(cp)

    # Verify written.
    fresh = CheckpointStore(db).read("t_b1_1")
    assert fresh is not None
    assert fresh.task_id == "t_b1_1"
    assert fresh.last_verified_head == "7225d3e383f268b3b7032294ac6ef0c76d5c5d62"


def test_checkpoint_round_trip_fresh_session(tmp_path):
    """B1.2 — session A writes, session B (fresh, no transcript) reads."""
    from agent_body.checkpoint_store import CheckpointStore, Checkpoint, AuthoritativePointer

    db = tmp_path / "checkpoints.sqlite"
    CheckpointStore(db).write(Checkpoint(
        task_id="t_b1_2",
        objective="B1.2 round trip",
        authoritative_pointers=[
            AuthoritativePointer("repo", "neokyhurtado-cmd/traficlab-factory"),
            AuthoritativePointer("commit", "7225d3e383f268b3b7032294ac6ef0c76d5c5d62"),
        ],
        last_verified_head="7225d3e383f268b3b7032294ac6ef0c76d5c5d62",
        evidence_already_checked=[5658210225, 5658256935, 5659485468, 5659491838],
        blockers=[],
        next_safe_action="emit_closeout",
        state="ACTIVE",
    ))
    # Fresh session B — completely new store instance on the same file.
    cp_b = CheckpointStore(db).read("t_b1_2")
    assert cp_b is not None
    assert cp_b.last_verified_head == "7225d3e383f268b3b7032294ac6ef0c76d5c5d62"
    assert set(cp_b.evidence_already_checked) == {5658210225, 5658256935, 5659485468, 5659491838}
    assert cp_b.next_safe_action == "emit_closeout"


def test_authority_conflict_applies_precedence_map():
    """B1.4 — Mission Control says X, GitHub says Y, precedence wins.

    The precedence map (per policies/authority-hierarchy.md):
        github_remote > mission_control > ia_vision_domain > local_checkpoint
    The apply function must NOT use any model judgment — it's pure lookup.
    """
    from agent_body.authority import apply_precedence, AuthorityClaim

    claims = [
        AuthorityClaim(source="mission_control", value="BODY-2_IN_PROGRESS", freshness=100),
        AuthorityClaim(source="github_remote", value="BODY-2_NOT_MERGED", freshness=200),
    ]
    verdict = apply_precedence(claims, domain="agent_body_phase_progress")
    assert verdict.winner_source == "github_remote"
    assert verdict.winner_value == "BODY-2_NOT_MERGED"
    assert verdict.fail_closed is False  # resolved via precedence; no model judgment used


def test_authority_conflict_with_no_precedence_match_fails_closed():
    """If NO source matches the precedence map for the domain, fail closed."""
    from agent_body.authority import apply_precedence, AuthorityClaim

    claims = [
        AuthorityClaim(source="unknown_source", value="x", freshness=1),
    ]
    verdict = apply_precedence(claims, domain="agent_body_phase_progress")
    assert verdict.fail_closed is True
    assert verdict.winner_source is None
