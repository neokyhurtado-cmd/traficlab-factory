"""Tests for Fix #4 — durable publication state.

Phase 1 finalised ``record_result`` BEFORE the GitHub RESULT post landed.
If the post raised, the row was already terminal — the next poll would
skip it forever and Astra would never see the outcome. The re-audit
explicitly called this out.

The contract now is:
  - Business result and publication delivery are separate states.
  - ``result_status`` flips to non-NULL when local work is done.
  - ``result_posted=0`` means we still owe a publication to GitHub.
  - On the next tick, ``list_pending_publications()`` returns the
    rows that owe delivery, and the scheduler must republish them.

These tests verify:
  1. A RESULT post failure does NOT advance ``result_posted`` to 1.
  2. The directive shows up in ``list_pending_publications()``.
  3. A second tick republishes the RESULT.
  4. After a successful retry, ``result_posted=1`` and the row is gone
     from the pending list.
  5. ``mark_post_failed`` records the error string for diagnostics.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from directive_watcher.allowlist import AllowlistConfig
from directive_watcher.gh_client import FakeGitHubClient, RemoteComment
from directive_watcher.handler import WatcherHandler
from directive_watcher.retry import BackoffPolicy
from directive_watcher.sidecar_store import RESULT_DISPATCHED, SidecarStore


def _make_comment(cid: int, body: str, author: str = "astra") -> RemoteComment:
    return RemoteComment(
        id=cid, author=author, body=body,
        url=f"https://github.com/r/o/issues/18#issuecomment-{cid}",
        issue_number=18,
    )


def _directive_body(directive_id: str) -> str:
    return (
        "[ASTRA_DIRECTIVE:v1]\n"
        "ACTION = CONTINUE\n"
        "REPOSITORY = neokyhurtado-cmd/traficlab-factory\n"
        "ISSUE = 18\n"
        "TARGET_BRANCH = AUTO_FROM_ISSUE_CONTEXT\n"
        "EXPECTED_HEAD = NONE\n"
        "SCOPE = test scope\n"
        "AUTO_NEXT_SAFE_GATE = YES\n"
        "REQUIRES_HUMAN_GO_REAL = NO\n"
        f"DIRECTIVE_ID = {directive_id}\n"
    )


@pytest.fixture
def env(tmp_path: Path):
    store = SidecarStore(tmp_path / "sidecar.db")
    gh = FakeGitHubClient()
    allowlist = AllowlistConfig(
        allowlisted_repos=frozenset({"neokyhurtado-cmd/traficlab-factory"}),
        allowlisted_authors=frozenset({"astra"}),
    )
    handler = WatcherHandler(
        store=store, gh=gh, allowlist=allowlist,
        evidence_root=str(tmp_path),
        backoff=BackoffPolicy(initial_seconds=0.001, max_attempts=2),
    )
    return {"store": store, "gh": gh, "handler": handler, "tmp_path": tmp_path}


# 1. RESULT post failure does not advance result_posted
def test_result_post_failure_keeps_row_pending(env):
    """If the GitHub RESULT post fails, result_status is recorded but
    result_posted stays 0, and the row appears in list_pending_publications().
    """
    gh = env["gh"]
    store = env["store"]
    handler = env["handler"]
    gh.add(_make_comment(101, _directive_body("d-pubfail")))

    # Force BOTH posts (ACK + RESULT) to fail so we exercise the durable
    # publication path on both messages.
    original_post = gh.post_comment
    call_count = {"n": 0}

    def post_always_fail(repo, issue_number, body):
        call_count["n"] += 1
        raise RuntimeError(f"simulated gh failure (call #{call_count['n']})")

    gh.post_comment = post_always_fail  # type: ignore[assignment]

    handler.tick(["neokyhurtado-cmd/traficlab-factory"])

    # The store has a record for d-pubfail. WITHOUT a dispatcher
    # injected, default_execution emits BLOCKED_EXTERNAL_REAL — the
    # contract we test here is that whatever the status, the row is
    # durable and pending publication.
    rec = store.get_processed("d-pubfail")
    assert rec["ack_status"] == "CLAIMED"
    assert rec["result_status"] is not None
    assert rec["ack_posted"] == 0, "ACK post failed → ack_posted must be 0"
    assert rec["result_posted"] == 0, (
        "RESULT post failed → result_posted must stay 0"
    )
    # The row is in the pending-publication list.
    pending = store.list_pending_publications()
    assert any(p["directive_id"] == "d-pubfail" for p in pending)


# 2. Second tick republishes the RESULT when post recovers
def test_pending_publication_republished_on_next_tick(env):
    gh = env["gh"]
    store = env["store"]
    handler = env["handler"]
    gh.add(_make_comment(102, _directive_body("d-repub")))

    original_post = gh.post_comment
    state = {"fail_next": True}

    def flaky_post(repo, issue_number, body):
        if state["fail_next"]:
            state["fail_next"] = False
            raise RuntimeError("first attempt fails")
        return original_post(repo, issue_number, body)

    gh.post_comment = flaky_post  # type: ignore[assignment]

    handler.tick(["neokyhurtado-cmd/traficlab-factory"])
    # First tick failed → both ACK and RESULT are pending.
    rec = store.get_processed("d-repub")
    assert rec["ack_posted"] == 0

    # Second tick republishes — the flaky_post will succeed this time.
    handler.tick(["neokyhurtado-cmd/traficlab-factory"])

    rec = store.get_processed("d-repub")
    assert rec["ack_posted"] == 1
    assert rec["result_posted"] == 1
    pending = store.list_pending_publications()
    assert not any(p["directive_id"] == "d-repub" for p in pending), (
        f"d-repub should be off the pending list after recovery; got: {pending}"
    )


# 3. mark_post_failed records the error for diagnostics
def test_post_failure_records_error_message(env):
    store = env["store"]
    store.claim(
        directive_id="d-err",
        source_comment_id=200,
        body_sha256="abc",
        head_before=None,
    )
    store.record_result("d-err", RESULT_DISPATCHED, head_after=None)
    store.mark_post_failed("d-err", "ConnectionError: gh api unreachable")

    rec = store.get_processed("d-err")
    assert "ConnectionError" in (rec["last_post_error"] or "")


# 4. The pending list is empty when nothing is owed
def test_pending_publication_empty_when_all_posted(env):
    store = env["store"]
    store.claim(
        directive_id="d-done",
        source_comment_id=300,
        body_sha256="abc",
        head_before=None,
    )
    store.record_result("d-done", RESULT_DISPATCHED, head_after=None)
    store.mark_ack_posted("d-done")
    store.mark_result_posted("d-done")

    pending = store.list_pending_publications()
    assert pending == [], f"expected no pending; got: {pending}"


# 5. Direct store-level: record_result does NOT block on post
def test_record_result_does_not_require_post_success(env):
    """A failed post must NOT raise / block the store from finalising.

    Phase 1 logged the post failure but the row was already terminal; the
    watcher then silently skipped the next tick. The new store contract
    keeps the row open (result_posted=0) so the scheduler retries.
    """
    store = env["store"]
    store.claim(
        directive_id="d-finalise",
        source_comment_id=400,
        body_sha256="abc",
        head_before=None,
    )
    store.record_result("d-finalise", RESULT_DISPATCHED, head_after=None)
    rec = store.get_processed("d-finalise")
    assert rec["result_status"] == RESULT_DISPATCHED
    # result_posted is still 0 — pending until the next successful post.
    assert rec["result_posted"] == 0
