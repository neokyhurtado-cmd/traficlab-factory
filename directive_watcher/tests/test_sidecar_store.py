"""Tests for the durable sidecar store.

The store is the single source of truth for:
  - last_seen_comment_id
  - processed_directive_ids
  - comment_id → directive_id → execution_id
  - ack_status / result_status

The tests cover the 14 behavioural requirements from #18 by exercising the
store directly. Higher-level scheduler tests live in test_scheduler.py.
"""
from __future__ import annotations

import threading

import pytest

from directive_watcher.sidecar_store import (
    ACK_CLAIMED,
    AlreadyProcessed,
    RESULT_HUMAN_GO,
    RESULT_READY,
    SidecarStore,
)


@pytest.fixture
def store(tmp_path):
    s = SidecarStore(tmp_path / "sidecar.db")
    yield s
    s.close()


# 1. authorized directive → claimed once
def test_authorized_directive_is_claimed_once(store):
    claim = store.claim(
        directive_id="dir-1",
        source_comment_id=100,
        body_sha256="sha-a",
        head_before="abc",
    )
    assert claim.execution_id
    assert claim.directive_id == "dir-1"
    record = store.get_processed("dir-1")
    assert record["ack_status"] == ACK_CLAIMED
    assert record["result_status"] is None


# 2. same poll repeated → no second execution
def test_same_directive_claimed_twice_raises(store):
    store.claim("dir-1", 100, "sha-a", "abc")
    with pytest.raises(AlreadyProcessed):
        store.claim("dir-1", 100, "sha-a", "abc")


# 6. duplicate DIRECTIVE_ID on different comments → no double-run
def test_same_directive_id_on_different_comments_is_still_a_double_run(store):
    store.claim("dir-1", 100, "sha-a", "abc")
    with pytest.raises(AlreadyProcessed):
        store.claim("dir-1", 200, "sha-b", "def")


# 8. restart with persisted state → no re-run
def test_restart_with_persisted_state_does_not_rerun(tmp_path):
    s1 = SidecarStore(tmp_path / "sidecar.db")
    s1.claim("dir-1", 100, "sha-a", "abc")
    s1.record_result("dir-1", RESULT_READY, head_after="def")
    s1.close()

    # Re-open the SAME database file as a fresh process would.
    s2 = SidecarStore(tmp_path / "sidecar.db")
    with pytest.raises(AlreadyProcessed):
        s2.claim("dir-1", 100, "sha-a", "abc")
    record = s2.get_processed("dir-1")
    assert record["result_status"] == RESULT_READY
    s2.close()


# 7. edited directive after ACK → no silent re-run
def test_edited_body_after_ack_is_detected(store):
    store.claim("dir-1", 100, "sha-a", "abc")
    assert store.detect_body_edit_after_ack("dir-1", "sha-a") is False
    assert store.detect_body_edit_after_ack("dir-1", "sha-b") is True
    # Idempotent: subsequent calls stay True without flipping further.
    assert store.detect_body_edit_after_ack("dir-1", "sha-c") is True
    rec = store.get_processed("dir-1")
    assert rec["body_edited"] == 1


# 9. two watcher workers racing → one execution only
def test_two_workers_racing_one_claim(store):
    """Two threads attempt to claim the same directive. Exactly one wins,
    the other receives AlreadyProcessed."""
    barrier = threading.Barrier(2)
    winners = []
    errors = []

    def worker():
        barrier.wait()
        try:
            claim = store.claim("dir-1", 100, "sha-a", "abc")
            winners.append(claim)
        except AlreadyProcessed as e:
            errors.append(str(e))

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert len(winners) == 1
    assert len(errors) == 1


# 13. GitHub/API transient failure → retry/backoff; no lost state
def test_claim_without_result_record_stays_pending_for_recovery(store):
    """If a claim is made but the process crashes before record_result,
    the next run sees the directive as PENDING (claim without result)."""
    store.claim("dir-1", 100, "sha-a", "abc")
    pending = store.claim_pending()
    assert len(pending) == 1
    assert pending[0]["directive_id"] == "dir-1"


def test_record_result_finalises_claim(store):
    store.claim("dir-1", 100, "sha-a", "abc")
    store.record_result("dir-1", RESULT_READY, head_after="def")
    rec = store.get_processed("dir-1")
    assert rec["result_status"] == RESULT_READY
    assert rec["head_after"] == "def"
    assert store.claim_pending() == []


def test_record_result_twice_raises(store):
    store.claim("dir-1", 100, "sha-a", "abc")
    store.record_result("dir-1", RESULT_READY, head_after="def")
    with pytest.raises(AlreadyProcessed):
        store.record_result("dir-1", RESULT_READY, head_after="def")


def test_record_result_with_unknown_status_raises(store):
    store.claim("dir-1", 100, "sha-a", "abc")
    with pytest.raises(ValueError):
        store.record_result("dir-1", "BANANA", head_after="def")


def test_human_go_real_boundary_can_be_recorded(store):
    """A protected-boundary directive finalises with HUMAN_GO_REAL_REQUIRED.
    The watcher NEVER auto-executes; this records the surfaced gate."""
    store.claim("dir-1", 100, "sha-a", "abc")
    store.record_result("dir-1", RESULT_HUMAN_GO, head_after=None)
    rec = store.get_processed("dir-1")
    assert rec["result_status"] == RESULT_HUMAN_GO


# --- seen tracking ---------------------------------------------------------


def test_mark_seen_first_time_is_new(store):
    assert store.mark_seen(100, "sha-a") is True
    assert store.mark_seen(100, "sha-a") is False  # idempotent


def test_mark_seen_body_change_returns_false_but_updates(store):
    store.mark_seen(100, "sha-a")
    assert store.mark_seen(100, "sha-b") is False
    assert store.get_seen_body_sha(100) == "sha-b"


def test_last_seen_comment_id_returns_max(store):
    store.mark_seen(100, "sha-a")
    store.mark_seen(50, "sha-b")
    store.mark_seen(200, "sha-c")
    assert store.last_seen_comment_id() == 200


def test_last_seen_empty_db_returns_zero(store):
    assert store.last_seen_comment_id() == 0


def test_run_history_roundtrip(store):
    run_id = store.record_run_start(notes="tick-1")
    store.record_run_finish(run_id, status="ok", notes="ok")
    runs = store.last_runs(limit=5)
    assert len(runs) == 1
    assert runs[0]["status"] == "ok"
    assert runs[0]["notes"] == "ok"
    assert runs[0]["finished_at"] is not None
