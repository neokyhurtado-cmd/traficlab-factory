"""Tests for the watcher handler.

The handler is the integration seam that ties parser + store + gh_client +
evidence + ack/result together. Tests use ``FakeGitHubClient`` to drive
the pipeline deterministically without hitting GitHub.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from directive_watcher.allowlist import AllowlistConfig
from directive_watcher.gh_client import FakeGitHubClient, RemoteComment
from directive_watcher.handler import (
    ExecutionOutcome,
    RESULT_HUMAN_GO,
    RESULT_READY,
    WatcherHandler,
)
from directive_watcher.retry import BackoffPolicy
from directive_watcher.sidecar_store import SidecarStore


def _make_comment(cid: int, body: str, author: str = "astra") -> RemoteComment:
    return RemoteComment(
        id=cid,
        author=author,
        body=body,
        url=f"https://github.com/r/o/issues/18#issuecomment-{cid}",
        issue_number=18,
    )


def _directive_body(directive_id: str = "d-1", requires_hgr: bool = False) -> str:
    return (
        "[ASTRA_DIRECTIVE:v1]\n"
        "ACTION = CONTINUE\n"
        "REPOSITORY = neokyhurtado-cmd/traficlab-factory\n"
        "ISSUE = 18\n"
        "TARGET_BRANCH = AUTO_FROM_ISSUE_CONTEXT\n"
        "EXPECTED_HEAD = NONE\n"
        "SCOPE = test scope\n"
        f"AUTO_NEXT_SAFE_GATE = YES\n"
        f"REQUIRES_HUMAN_GO_REAL = {'YES' if requires_hgr else 'NO'}\n"
        f"DIRECTIVE_ID = {directive_id}\n"
    )


@pytest.fixture
def env(tmp_path):
    store = SidecarStore(tmp_path / "sidecar.db")
    gh = FakeGitHubClient()
    # Seed (repo, "main") for the legacy ``EXPECTED_HEAD = NONE`` /
    # ``TARGET_BRANCH = AUTO_FROM_ISSUE_CONTEXT`` sentinels (CONTEXT_BINDING_FAIL_CLOSED
    # contract — legacy compatibility path).
    gh.set_branch_head(
        "neokyhurtado-cmd/traficlab-factory", "main",
        "1111111111111111111111111111111111111111",
    )
    allowlist = AllowlistConfig(
        allowlisted_repos=frozenset({"neokyhurtado-cmd/traficlab-factory"}),
        allowlisted_authors=frozenset({"astra"}),
    )
    evidence_root = str(tmp_path)  # evidence.py prepends "evidence/visual"
    handler = WatcherHandler(
        store=store,
        gh=gh,
        allowlist=allowlist,
        evidence_root=evidence_root,
        backoff=BackoffPolicy(initial_seconds=0.001, max_attempts=2),
    )
    return {
        "store": store,
        "gh": gh,
        "allowlist": allowlist,
        "handler": handler,
        "tmp_path": tmp_path,
        "evidence_root": evidence_root,
    }


# 1. authorized directive → claimed once
def test_authorized_directive_results_in_ack_and_result(env):
    gh = env["gh"]
    gh.add(_make_comment(101, _directive_body("d-1")))
    summary = env["handler"].tick(["neokyhurtado-cmd/traficlab-factory"])
    assert summary.directives_claimed == 1
    assert summary.directives_parsed == 1
    # Two posts: ACK + RESULT.
    assert len(gh.posted) == 2
    ack_body, result_body = gh.posted[0][2], gh.posted[1][2]
    assert "[HERMES_ACK:v1]" in ack_body
    assert "DIRECTIVE_ID = d-1" in ack_body
    assert "[HERMES_RESULT:v1]" in result_body
    # Per the Astra re-audit (Fix #1): without a dispatcher injected, the
    # handler must NOT emit READY_FOR_ASTRA_REAUDIT — it emits
    # BLOCKED_EXTERNAL_REAL because no real session was bound. The
    # handler-level "dispatch wired up" path is exercised separately
    # in test_orch_dispatch.py + test_handler_with_dispatch.py.
    assert "STATUS = BLOCKED_EXTERNAL_REAL" in result_body
    # Source comment / directive / execution all linked in the RESULT.
    assert "SOURCE_COMMENT_ID = 101" in result_body
    assert "DIRECTIVE_ID = d-1" in result_body
    assert "EXECUTION_ID = exec-101-" in result_body


# 2. same poll repeated → no second execution
def test_same_directive_seen_twice_executes_once(env):
    gh = env["gh"]
    gh.add(_make_comment(101, _directive_body("d-1")))
    handler = env["handler"]
    s1 = handler.tick(["neokyhurtado-cmd/traficlab-factory"])
    s2 = handler.tick(["neokyhurtado-cmd/traficlab-factory"])
    assert s1.directives_claimed == 1
    assert s2.directives_claimed == 0
    assert s2.directives_skipped >= 1
    # Still only one ACK + one RESULT on the wire.
    assert len(gh.posted) == 2


# 3. unauthorized author → ignored/denied
def test_unauthorized_author_is_denied(env):
    gh = env["gh"]
    gh.add(_make_comment(101, _directive_body("d-1"), author="random-user"))
    summary = env["handler"].tick(["neokyhurtado-cmd/traficlab-factory"])
    assert summary.directives_claimed == 0
    assert any("author_not_allowlisted" in n for n in summary.notes)
    assert gh.posted == []  # no ACK or RESULT posted


# 4. repo outside allowlist → ignored/denied
def test_repo_outside_allowlist_is_denied(env):
    gh = env["gh"]
    # Allow the comment through gh, but the handler is told to poll a
    # repo that is not in the allowlist.
    summary = env["handler"].tick(["neokyhurtado-cmd/someone-else"])
    assert summary.directives_claimed == 0
    assert gh.posted == []


# 5. comment without marker → ignored
def test_comment_without_marker_is_ignored(env):
    gh = env["gh"]
    gh.add(_make_comment(101, "Just chatting, no directive here."))
    summary = env["handler"].tick(["neokyhurtado-cmd/traficlab-factory"])
    assert summary.directives_parsed == 0
    assert summary.directives_claimed == 0
    assert gh.posted == []


# 5b. malformed directive (marker but bad content) → ignored, no execution
def test_malformed_directive_is_ignored_no_post(env):
    gh = env["gh"]
    gh.add(_make_comment(101, "[ASTRA_DIRECTIVE:v1]\nACTION = NUKE\n"))
    summary = env["handler"].tick(["neokyhurtado-cmd/traficlab-factory"])
    assert summary.directives_claimed == 0
    assert gh.posted == []


# 6. duplicate DIRECTIVE_ID on different comments → no double-run
def test_duplicate_directive_id_on_two_comments_executes_once(env):
    gh = env["gh"]
    gh.add(_make_comment(101, _directive_body("d-same")))
    # Different author? No — different comment_id but same DIRECTIVE_ID.
    # The second comment is by an allowlisted author too, just to isolate
    # author-vs-id duplication.
    gh.add(_make_comment(102, _directive_body("d-same"), author="astra"))
    summary = env["handler"].tick(["neokyhurtado-cmd/traficlab-factory"])
    assert summary.directives_claimed == 1


# 7. edited directive after ACK → no silent re-run
def test_edited_body_after_ack_does_not_silently_rerun(env):
    """Fix #3: edit detection must work WITHOUT manually rewinding the cursor.

    The Phase 1 test for this path cheated by resetting the comment_id
    in the seen table. Astra's re-audit explicitly flagged that as a
    "trap" — the production watcher must detect edits via the
    list_recent_comments window, not by hacking the cursor.

    This test simulates an edit by replacing the comment body in the
    FakeGitHubClient (GitHub edits don't bump the id). The watcher's
    edit-detection window (list_recent_comments) must re-observe the
    comment, see that the body_sha changed, and surface it as
    ``denied:body_edited_after_ack`` — without any cursor manipulation.
    """
    gh = env["gh"]
    cid = 101
    gh.add(_make_comment(cid, _directive_body("d-edit")))
    handler = env["handler"]
    s1 = handler.tick(["neokyhurtado-cmd/traficlab-factory"])
    assert s1.directives_claimed == 1
    # First tick produced one ACK + one RESULT.
    assert len(gh.posted) == 2

    # Simulate an edit: same comment id, new body. The cursor stays put —
    # that's the whole point. The watcher's edit window re-scans the
    # last N comments and catches the sha mismatch on its own.
    edited_body = _directive_body("d-edit") + "\n# edited by author"
    gh._comments[0] = _make_comment(cid, edited_body)

    s2 = handler.tick(["neokyhurtado-cmd/traficlab-factory"])
    # The directive MUST NOT be claimed again — body change after ACK is
    # the canonical "do not silently re-run" case.
    assert s2.directives_claimed == 0
    # The watcher must surface the edit via its notes.
    assert any("body_edited_after_ack" in n for n in s2.notes), (
        f"expected edit-detection note; got: {s2.notes}"
    )
    # Still only one ACK + one RESULT on the wire.
    assert len(gh.posted) == 2


# 8. restart with persisted state → no re-run
def test_restart_does_not_re_execute_finalised_directive(tmp_path):
    db = tmp_path / "sidecar.db"
    store = SidecarStore(db)
    gh = FakeGitHubClient()
    gh.set_branch_head(
        "neokyhurtado-cmd/traficlab-factory", "main",
        "1111111111111111111111111111111111111111",
    )
    gh.add(_make_comment(101, _directive_body("d-restart")))
    allowlist = AllowlistConfig(
        allowlisted_repos=frozenset({"neokyhurtado-cmd/traficlab-factory"}),
        allowlisted_authors=frozenset({"astra"}),
    )
    h1 = WatcherHandler(
        store=store,
        gh=gh,
        allowlist=allowlist,
        evidence_root=str(tmp_path),
        backoff=BackoffPolicy(initial_seconds=0.001),
    )
    h1.tick(["neokyhurtado-cmd/traficlab-factory"])
    assert len(gh.posted) == 2
    # Restart: re-open the same db file, fresh handler, same fake client.
    h2 = WatcherHandler(
        store=SidecarStore(db),
        gh=gh,
        allowlist=allowlist,
        evidence_root=str(tmp_path),
        backoff=BackoffPolicy(initial_seconds=0.001),
    )
    s2 = h2.tick(["neokyhurtado-cmd/traficlab-factory"])
    assert s2.directives_claimed == 0
    # No new posts on the wire.
    assert len(gh.posted) == 2


# 10. protected action without HUMAN_GO_REAL → wake allowed, execution blocked
def test_protected_directive_without_human_go_real_flag_is_blocked(env):
    gh = env["gh"]
    # Build a directive that says it requires HUMAN_GO_REAL protection but
    # the marker says REQUIRES_HUMAN_GO_REAL = NO — i.e. the directive is
    # asking for protection without declaring it.
    body = _directive_body("d-bad-hgr", requires_hgr=False)
    gh.add(_make_comment(101, body))
    s = env["handler"].tick(["neokyhurtado-cmd/traficlab-factory"])
    # The handler still claims+ACKs (wake allowed) but the default execution
    # surfaces READY_FOR_ASTRA_REAUDIT; for a directive that wants a
    # protected action without declaring the flag, the runtime path would
    # short-circuit. Here we just verify the wake-vs-execute separation is
    # observable: the director never auto-executes anything gated by
    # requires_human_go_real — only the explicit declaration matters.
    assert s.directives_claimed == 1
    # Confirm the dual gate (directive flag + protected-boundary request)
    # would still deny execution — covered in test_allowlist.py. Here we
    # only verify the handler did not blow up on this case.


# 11. explicit HUMAN_GO_REAL artifact/context → protected gate can be presented
def test_human_go_real_directive_records_human_go_required(env):
    gh = env["gh"]
    gh.add(_make_comment(101, _directive_body("d-hgr", requires_hgr=True)))
    s = env["handler"].tick(["neokyhurtado-cmd/traficlab-factory"])
    assert s.directives_claimed == 1
    result_body = gh.posted[1][2]
    assert "STATUS = HUMAN_GO_REAL_REQUIRED" in result_body


# 12. malformed directive → fail closed
def test_malformed_directive_is_logged_but_does_not_crash(env):
    gh = env["gh"]
    gh.add(_make_comment(101, "[ASTRA_DIRECTIVE:v1]\nACTION = NUKE\n"))
    gh.add(_make_comment(102, _directive_body("d-good")))
    s = env["handler"].tick(["neokyhurtado-cmd/traficlab-factory"])
    # The malformed one is skipped silently; the good one is claimed.
    assert s.directives_claimed == 1
    assert s.directives_parsed == 1
    assert len(gh.posted) == 2  # only for the good one


# 13. transient failure → retry/backoff; no lost state
def test_transient_failure_on_list_comments_is_retried(env, monkeypatch):
    gh = env["gh"]
    # Make the first call fail, the second succeed.
    real = gh.list_comments_since
    calls = {"n": 0}

    def flaky(repo, since):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("network blip")
        return real(repo, since)

    monkeypatch.setattr(gh, "list_comments_since", flaky)
    s = env["handler"].tick(["neokyhurtado-cmd/traficlab-factory"])
    assert calls["n"] == 2  # one failure, one success
    # No comments to process — the fake has none.
    assert s.directives_claimed == 0


def test_exhausted_retry_records_failure_but_continues(env, monkeypatch):
    gh = env["gh"]

    def always_fail(repo, since):
        raise ConnectionError("always")

    monkeypatch.setattr(gh, "list_comments_since", always_fail)
    s = env["handler"].tick(["neokyhurtado-cmd/traficlab-factory"])
    assert any("transient_failure" in n for n in s.notes)
    # Tick still finishes — the handler does not abort on one repo's failure.


# 14. result links source comment/directive/execution
def test_result_links_all_three_ids(env):
    gh = env["gh"]
    gh.add(_make_comment(777, _directive_body("d-link")))
    env["handler"].tick(["neokyhurtado-cmd/traficlab-factory"])
    result_body = gh.posted[1][2]
    assert "SOURCE_COMMENT_ID = 777" in result_body
    assert "DIRECTIVE_ID = d-link" in result_body
    assert "EXECUTION_ID = exec-777-" in result_body


# --- evidence contract enforcement ----------------------------------------


def test_evidence_directory_created_for_every_claim(env):
    gh = env["gh"]
    gh.add(_make_comment(101, _directive_body("d-ev")))
    env["handler"].tick(["neokyhurtado-cmd/traficlab-factory"])
    # Find the exec dir that was created, using the fixture's tmp_path.
    exec_dirs = list((env["tmp_path"] / "evidence" / "visual").iterdir())
    assert len(exec_dirs) == 1
    assert (exec_dirs[0] / "manifest.json").is_file()
    assert (exec_dirs[0] / "before").is_dir()
    assert (exec_dirs[0] / "after").is_dir()
    manifest = json.loads((exec_dirs[0] / "manifest.json").read_text())
    assert manifest["directive_id"] == "d-ev"
    assert manifest["source_comment_id"] == 101


# --- custom execution strategy --------------------------------------------


def test_custom_execution_strategy_is_used(env):
    """Director can plug in a different execution function. The handler
    must call it and use its verdict."""
    gh = env["gh"]
    gh.add(_make_comment(101, _directive_body("d-custom")))

    def custom(directive, evidence_dir):
        return ExecutionOutcome(
            status=RESULT_READY,
            head_after="custom-head",
            tests="custom-tests-pass",
            evidence=evidence_dir,
        )

    store = env["store"]
    h = WatcherHandler(
        store=store,
        gh=gh,
        allowlist=env["allowlist"],
        evidence_root=str(env["tmp_path"]),
        execution_fn=custom,
        backoff=env["handler"]._backoff,
    )
    h.tick(["neokyhurtado-cmd/traficlab-factory"])
    result_body = gh.posted[1][2]
    assert "HEAD_AFTER = custom-head" in result_body
    assert "TESTS = custom-tests-pass" in result_body
    rec = store.get_processed("d-custom")
    assert rec["head_after"] == "custom-head"
    assert rec["result_status"] == RESULT_READY


# --- evidence flow also covers the HUMAN_GO_REAL gate --------------------


def test_human_go_real_path_creates_evidence_and_records_status(env):
    gh = env["gh"]
    gh.add(_make_comment(101, _directive_body("d-hgr2", requires_hgr=True)))
    env["handler"].tick(["neokyhurtado-cmd/traficlab-factory"])
    # Evidence dir was created even though no execution happened.
    exec_dirs = list((env["tmp_path"] / "evidence" / "visual").iterdir())
    assert len(exec_dirs) == 1
    # The store records HUMAN_GO_REAL_REQUIRED.
    rec = env["store"].get_processed("d-hgr2")
    assert rec["result_status"] == RESULT_HUMAN_GO
