"""Tests for per-repo comment cursor (Fix #2 from Astra re-audit).

Phase 1 used a single global `MAX(comment_id)` as the cursor — so a
directive valid for repo A would be silently skipped when the cursor
had advanced past it on a different repo poll. The re-audit explicitly
called this out: the cursor must be per-repo.

Tests:
  1. Two repos polled in sequence — each carries its own cursor.
  2. After polling repo A and advancing its cursor, repo B's cursor is
     untouched, so a directive for repo B with a lower comment id is
     STILL observed.
  3. Cursor survives restart (persisted in the sidecar).
"""
from __future__ import annotations

import pytest

from directive_watcher.gh_client import FakeGitHubClient, RemoteComment
from directive_watcher.handler import WatcherHandler
from directive_watcher.allowlist import AllowlistConfig
from directive_watcher.scheduler import Scheduler, SchedulerConfig
from directive_watcher.retry import BackoffPolicy
from directive_watcher.sidecar_store import SidecarStore


def _make_comment(cid: int, body: str, repo: str = "neokyhurtado-cmd/traficlab-factory",
                  issue_number: int = 18, author: str = "astra") -> RemoteComment:
    return RemoteComment(
        id=cid, author=author, body=body,
        url=f"https://github.com/{repo}/issues/{issue_number}#issuecomment-{cid}",
        issue_number=issue_number,
    )


def _directive_body(directive_id: str, repo: str, issue: int = 18) -> str:
    return (
        "[ASTRA_DIRECTIVE:v1]\n"
        "ACTION = CONTINUE\n"
        f"REPOSITORY = {repo}\n"
        f"ISSUE = {issue}\n"
        "TARGET_BRANCH = AUTO_FROM_ISSUE_CONTEXT\n"
        "EXPECTED_HEAD = NONE\n"
        "SCOPE = test\n"
        "AUTO_NEXT_SAFE_GATE = YES\n"
        "REQUIRES_HUMAN_GO_REAL = NO\n"
        f"DIRECTIVE_ID = {directive_id}\n"
    )


# 1. Per-repo cursors are tracked independently
def test_per_repo_cursor_tracking(tmp_path):
    store = SidecarStore(tmp_path / "sidecar.db")
    store.upsert_cursor(repo="neokyhurtado-cmd/repoA", last_seen_comment_id=100)
    store.upsert_cursor(repo="neokyhurtado-cmd/repoB", last_seen_comment_id=50)
    assert store.get_cursor("neokyhurtado-cmd/repoA") == 100
    assert store.get_cursor("neokyhurtado-cmd/repoB") == 50
    # Advancing one must NOT affect the other.
    store.upsert_cursor(repo="neokyhurtado-cmd/repoA", last_seen_comment_id=200)
    assert store.get_cursor("neokyhurtado-cmd/repoA") == 200
    assert store.get_cursor("neokyhurtado-cmd/repoB") == 50


# 2. The cursor model is dict-shaped in the API (no global cursor leak)
def test_no_global_cursor_leaks_between_repos(tmp_path):
    store = SidecarStore(tmp_path / "sidecar.db")
    # Seed each repo's cursor with very different ids.
    store.upsert_cursor(repo="neokyhurtado-cmd/repoA", last_seen_comment_id=999)
    store.upsert_cursor(repo="neokyhurtado-cmd/repoB", last_seen_comment_id=5)
    # The legacy global method, if still present, must not be the source
    # of truth — verifying it equals 0 (no observed comments yet) confirms
    # the global max is no longer authoritative for cross-repo polling.
    assert store.last_seen_comment_id() == 0, (
        "global cursor must not be authoritative; per-repo cursors win"
    )


# 3. Cursor persists across restarts
def test_cursor_persists_across_restart(tmp_path):
    db = tmp_path / "sidecar.db"
    s1 = SidecarStore(db)
    s1.upsert_cursor(repo="neokyhurtado-cmd/repoX", last_seen_comment_id=4242)
    s1.close()
    s2 = SidecarStore(db)
    assert s2.get_cursor("neokyhurtado-cmd/repoX") == 4242
    s2.close()


# 4. Multi-repo tick via the handler: repo A's cursor advances, B's stays put
def test_handler_tick_processes_two_repos_with_independent_cursors(
    tmp_path, monkeypatch
):
    store = SidecarStore(tmp_path / "sidecar.db")
    # SEGURO B / FRESH_START_WATERMARK: pre-seed both repos so the
    # fresh-start replay guard does not block the cursor test fixtures.
    store.set_watermark(repo="neokyhurtado-cmd/repoA", value=0)
    store.set_watermark(repo="neokyhurtado-cmd/repoB", value=0)
    gh = FakeGitHubClient()
    # Seed (repo, "main") for legacy sentinels.
    for r in {"neokyhurtado-cmd/repoA", "neokyhurtado-cmd/repoB"}:
        gh.set_branch_head(
            r, "main",
            "1111111111111111111111111111111111111111",
        )

    # FakeGHClient returns ALL comments regardless of repo arg (it's a
    # test fake). We segregate by author comment body to simulate the
    # "right" per-repo comment stream by using a wrapper.
    # Actually the simpler approach: stash comments per repo via the
    # fake and patch list_comments_since to filter.
    comments_by_repo: dict[str, list[RemoteComment]] = {
        "neokyhurtado-cmd/repoA": [
            _make_comment(101, _directive_body("d-A1", "neokyhurtado-cmd/repoA", 1),
                          repo="neokyhurtado-cmd/repoA", issue_number=1),
        ],
        "neokyhurtado-cmd/repoB": [
            _make_comment(50, _directive_body("d-B1", "neokyhurtado-cmd/repoB", 2),
                          repo="neokyhurtado-cmd/repoB", issue_number=2),
        ],
    }

    def fake_list(repo, since_id):
        return [c for c in comments_by_repo.get(repo, []) if c.id > since_id]

    gh.list_comments_since = fake_list  # type: ignore[assignment]

    allowlist = AllowlistConfig(
        allowlisted_repos=frozenset({"neokyhurtado-cmd/repoA", "neokyhurtado-cmd/repoB"}),
        allowlisted_authors=frozenset({"astra"}),
    )
    handler = WatcherHandler(
        store=store, gh=gh, allowlist=allowlist,
        evidence_root=str(tmp_path),
        backoff=BackoffPolicy(initial_seconds=0.001),
    )

    # Tick BOTH repos in one call.
    summary = handler.tick(["neokyhurtado-cmd/repoA", "neokyhurtado-cmd/repoB"])

    # Both directives must be claimed.
    assert summary.directives_parsed == 2
    assert summary.directives_claimed == 2
    # Per-repo cursors must reflect what was seen in each repo.
    assert store.get_cursor("neokyhurtado-cmd/repoA") == 101
    assert store.get_cursor("neokyhurtado-cmd/repoB") == 50

    # A second tick with no new comments must do nothing for either repo.
    s2 = handler.tick(["neokyhurtado-cmd/repoA", "neokyhurtado-cmd/repoB"])
    assert s2.directives_claimed == 0
