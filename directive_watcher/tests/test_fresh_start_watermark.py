"""SEGURO B — FRESH_START_WATERMARK (PR #19 Phase 4 closeout).

The Phase 3 closeout closed CONTEXT_BINDING_FAIL_CLOSED (5 contracts):
EXPECTED_HEAD mismatch was supposed to block stale historical directives.
But the re-audit found two gaps the binding check does NOT close:

  1. ``EXPECTED_HEAD = NONE`` resolves to the live HEAD at compare-time
     (``sentinels.resolve_expected_head``). A directive that the
     author wrote six months ago with ``EXPECTED_HEAD = NONE`` is
     tautologically accepted today, because the live HEAD now equals
     what ``NONE`` resolves to. The binding check passes by
     construction.

  2. ``AUTO_FROM_ISSUE_CONTEXT=YES`` overwrites ``expected_head`` with
     the live HEAD before the compare (handler.py::_process_comment).
     Same tautological pass.

The fix is a WATERMARK on the sidecar, seeded on the very first tick
after a fresh start:

  - When the sidecar has no cursor for a repo, the FIRST tick fetches
    ``list_recent_comments(repo, limit=1)`` (or a similar ``max(id)``
    call) to compute the watermark. We never execute anything from
    that first batch — we only record the watermark.

  - The watermark is persisted in the sidecar's ``repo_watermark``
    table. Subsequent ticks read it back; the watermark is monotone
    non-decreasing.

  - In ``_process_comment``: if ``comment.id <= watermark`` we mark
    it seen (so the per-repo cursor doesn't re-poll it forever) and
    skip with the on-topic note ``historical_observed:comment=ID:
    watermark=W``. We DO NOT parse the body as a directive and DO NOT
    dispatch.

The sentinels (``NONE`` / ``AUTO_FROM_ISSUE_CONTEXT``) still work for
comments POSTERIOR to the watermark — the watermark is a temporal
cut-off that runs BEFORE the sentinel/binding logic, not a semantic
override.

Run with::

    python -m pytest directive_watcher/tests/test_fresh_start_watermark.py -v
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from directive_watcher.allowlist import AllowlistConfig
from directive_watcher.gh_client import FakeGitHubClient, RemoteComment
from directive_watcher.handler import WatcherHandler
from directive_watcher.retry import BackoffPolicy
from directive_watcher.sidecar_store import SidecarStore


# ---------- helpers ---------------------------------------------------------


def _make_comment(
    cid: int,
    body: str,
    author: str = "neokyhurtado-cmd",
    issue_number: int = 18,
) -> RemoteComment:
    return RemoteComment(
        id=cid,
        author=author,
        body=body,
        url=f"https://github.com/neokyhurtado-cmd/traficlab-factory/issues/{issue_number}#issuecomment-{cid}",
        issue_number=issue_number,
    )


def _directive_body(
    *,
    directive_id: str = "d-watermark-1",
    expected_head: str = "NONE",
    auto_from_ctx: str = "NO",
    issue: int = 18,
    repository: str = "neokyhurtado-cmd/traficlab-factory",
    target_branch: str = "feat/hermes-2.0-github-directive-watcher",
) -> str:
    return textwrap.dedent(
        f"""\
        [ASTRA_DIRECTIVE:v1]
        ACTION = CONTINUE
        REPOSITORY = {repository}
        ISSUE = {issue}
        TARGET_BRANCH = {target_branch}
        EXPECTED_HEAD = {expected_head}
        SCOPE = watermark test
        AUTO_NEXT_SAFE_GATE = NO
        REQUIRES_HUMAN_GO_REAL = NO
        DIRECTIVE_ID = {directive_id}
        AUTO_FROM_ISSUE_CONTEXT = {auto_from_ctx}
        """
    )


@pytest.fixture
def env(tmp_path: Path):
    store = SidecarStore(tmp_path / "sidecar.db")
    gh = FakeGitHubClient()
    allowlist = AllowlistConfig(
        allowlisted_repos=frozenset({"neokyhurtado-cmd/traficlab-factory"}),
        allowlisted_authors=frozenset({"neokyhurtado-cmd"}),
    )
    handler = WatcherHandler(
        store=store,
        gh=gh,
        allowlist=allowlist,
        evidence_root=str(tmp_path),
        backoff=BackoffPolicy(initial_seconds=0.001, max_attempts=2),
    )
    gh.set_branch_head(
        "neokyhurtado-cmd/traficlab-factory",
        "feat/hermes-2.0-github-directive-watcher",
        "07d44c33649a4a29a141a9d477fb22200a542529",
    )
    return {
        "store": store,
        "gh": gh,
        "allowlist": allowlist,
        "handler": handler,
        "tmp_path": tmp_path,
    }


# ---------- BITERS ----------------------------------------------------------
#
# Each test below is the load-bearing bit for the closeout. The original
# bug allowed these directives to be CLAIMED; the fix MUST block them.


def test_historical_comment_with_stale_head_blocked_by_watermark(env):
    """The historical directive ``ASTRA-FACTORY18-PR19-REPLAN-V2-20260910``
    carried a stale ``EXPECTED_HEAD=cd7c809...``. Today, with a fresh
    sidecar, the binding check happens to flag the mismatch. The
    watermark test is the boundary: even if the binding check happens
    to pass (e.g. someone replaces the stale SHA with a current one
    in the historical body), the watermark MUST still block it.

    Setup: sidecar empty. Add ONE historical comment with the stale
    sha. The handler must mark it seen, skip it with the
    ``historical_observed`` note, NOT claim it.
    """
    gh = env["gh"]
    # Make sure no sidecar state exists.
    assert env["store"].get_cursor("neokyhurtado-cmd/traficlab-factory") == 0

    gh.add(_make_comment(
        42,
        _directive_body(
            directive_id="ASTRA-FACTORY18-PR19-REPLAN-V2-20260910",
            expected_head="cd7c8091111111111111111111111111111111111",
        ),
    ))

    s = env["handler"].tick(["neokyhurtado-cmd/traficlab-factory"])

    # MUST NOT claim — that was the historical-replay bug.
    assert s.directives_claimed == 0, (
        f"historical directive was CLAIMED on fresh sidecar; "
        f"notes={s.notes}. Fresh-start replay vulnerability."
    )
    # MUST be marked as historical_observed in the notes.
    matching = [n for n in s.notes if "historical_observed" in n]
    assert matching, (
        f"historical comment must be skipped with 'historical_observed' "
        f"note; got notes={s.notes}"
    )
    # The note MUST carry both the comment id AND the watermark value
    # so an operator can audit exactly which comments were rejected.
    note = matching[0]
    assert "comment=42" in note, f"note must include comment id; got {note!r}"
    assert "watermark=" in note, f"note must include watermark value; got {note!r}"
    # The directive MUST NOT appear in the processed table.
    assert env["store"].get_processed(
        "ASTRA-FACTORY18-PR19-REPLAN-V2-20260910"
    ) is None


def test_historical_comment_with_NONE_sentinel_blocked_by_watermark(env):
    """The specific case the re-audit flagged: a historical comment
    with ``EXPECTED_HEAD = NONE``. The current code resolves
    ``NONE`` to the live HEAD and the comparison always passes (it
    compares the resolved value to itself). With the watermark in
    place, the historical comment is blocked BEFORE the sentinel
    resolves — the cutoff is temporal, not semantic.

    This test is the biter the re-audit demanded.
    """
    gh = env["gh"]
    gh.add(_make_comment(
        17,
        _directive_body(
            directive_id="ASTRA-FACTORY18-PR19-NONE-REPLAY",
            expected_head="NONE",
        ),
    ))

    s = env["handler"].tick(["neokyhurtado-cmd/traficlab-factory"])

    assert s.directives_claimed == 0, (
        f"historical NONE-sentinel directive was CLAIMED — the very "
        f"gap the re-audit flagged; notes={s.notes}"
    )
    matching = [n for n in s.notes if "historical_observed" in n]
    assert matching, (
        f"NONE-sentinel historical comment must be skipped with "
        f"'historical_observed' note; got notes={s.notes}"
    )
    assert env["store"].get_processed("ASTRA-FACTORY18-PR19-NONE-REPLAY") is None


def test_historical_comment_with_auto_from_ctx_blocked_by_watermark(env):
    """The other half of the re-audit gap: a historical comment with
    ``AUTO_FROM_ISSUE_CONTEXT = YES``. The current handler overwrites
    ``expected_head`` with the live HEAD before comparing, so the
    directive is tautologically accepted. The watermark MUST run
    before the AUTO_FROM_ISSUE_CONTEXT overwrite.
    """
    gh = env["gh"]
    gh.add(_make_comment(
        23,
        _directive_body(
            directive_id="ASTRA-FACTORY18-PR19-AUTOCTX-REPLAY",
            expected_head="ANYTHING",  # any value; the AUTO_CTX path will overwrite
            auto_from_ctx="YES",
        ),
    ))

    s = env["handler"].tick(["neokyhurtado-cmd/traficlab-factory"])

    assert s.directives_claimed == 0, (
        f"historical AUTO_FROM_ISSUE_CONTEXT directive was CLAIMED; "
        f"notes={s.notes}"
    )
    matching = [n for n in s.notes if "historical_observed" in n]
    assert matching, (
        f"auto-ctx historical comment must be skipped with "
        f"'historical_observed' note; got notes={s.notes}"
    )


def test_post_watermark_comment_with_NONE_sentinel_still_allowed(env):
    """The watermark must NOT change the semantic of the sentinel for
    comments POSTERIOR to it. A comment with id > watermark and
    ``EXPECTED_HEAD = NONE`` must still be admitted. We pre-seed the
    sidecar with a watermark BELOW the new comment's id so the
    watermark check passes, and we assert the sentinel still
    resolves to the live HEAD correctly.
    """
    gh = env["gh"]
    # Seed the watermark to a value BELOW the new comment's id (100).
    # has_watermark must return True so the handler does NOT overwrite
    # the watermark during the first-tick seeding pass.
    env["store"].set_watermark(
        repo="neokyhurtado-cmd/traficlab-factory",
        value=50,
    )

    gh.add(_make_comment(
        100,
        _directive_body(
            directive_id="d-post-watermark-none",
            expected_head="NONE",
        ),
    ))

    s = env["handler"].tick(["neokyhurtado-cmd/traficlab-factory"])

    # The sentinel still works post-watermark.
    assert s.directives_claimed == 1, (
        f"post-watermark comment with NONE sentinel was NOT claimed — "
        f"the sentinel must still work for comments newer than the "
        f"watermark; notes={s.notes}"
    )


def test_watermark_seeded_on_first_tick(env):
    """When the sidecar has no watermark for a repo and no cursor
    either (fresh start), the handler MUST seed the watermark to the
    max comment id currently visible BEFORE processing any comment
    in that batch. The first tick therefore processes zero claims.
    """
    gh = env["gh"]
    assert env["store"].has_watermark("neokyhurtado-cmd/traficlab-factory") is False

    # Drop a batch with the max id of 100.
    for cid in (40, 100, 99):
        gh.add(_make_comment(
            cid,
            _directive_body(directive_id=f"d-fresh-{cid}", expected_head="cd7c809"),
        ))

    s = env["handler"].tick(["neokyhurtado-cmd/traficlab-factory"])

    # Watermark seeded to the max id observed.
    wm = env["store"].get_watermark("neokyhurtado-cmd/traficlab-factory")
    assert wm == 100, (
        f"watermark must equal max comment id in the first batch; "
        f"got {wm}, expected 100"
    )
    # ALL comments in the first batch are pre-watermark and MUST be
    # blocked, not claimed.
    assert s.directives_claimed == 0, (
        f"first-tick batch claimed at least one directive; fresh-start "
        f"replay vulnerability. notes={s.notes}"
    )


def test_watermark_persists_across_sidecar_close_open(tmp_path):
    """The watermark MUST survive a process restart: close the store,
    reopen the same SQLite file, the watermark is still there and
    pre-watermark comments stay blocked."""
    gh = FakeGitHubClient()
    store_path = tmp_path / "sidecar.db"

    s1 = SidecarStore(store_path)
    s1.set_watermark(repo="neokyhurtado-cmd/traficlab-factory", value=500)
    s1.close()

    s2 = SidecarStore(store_path)
    # The watermark survives the close/open.
    assert s2.has_watermark("neokyhurtado-cmd/traficlab-factory") is True
    assert s2.get_watermark("neokyhurtado-cmd/traficlab-factory") == 500

    # A handler tick with a historical comment (id 49 <= watermark 500)
    # is still blocked after restart.
    allowlist = AllowlistConfig(
        allowlisted_repos=frozenset({"neokyhurtado-cmd/traficlab-factory"}),
        allowlisted_authors=frozenset({"neokyhurtado-cmd"}),
    )
    handler = WatcherHandler(
        store=s2,
        gh=gh,
        allowlist=allowlist,
        evidence_root=str(tmp_path),
        backoff=BackoffPolicy(initial_seconds=0.001, max_attempts=2),
    )
    gh.set_branch_head(
        "neokyhurtado-cmd/traficlab-factory", "main",
        "07d44c33649a4a29a141a9d477fb22200a542529",
    )
    gh.add(_make_comment(
        49,
        _directive_body(
            directive_id="d-pre-restart",
            expected_head="cd7c8091111111111111111111111111111111111",
        ),
    ))
    s = handler.tick(["neokyhurtado-cmd/traficlab-factory"])
    assert s.directives_claimed == 0
    matching = [n for n in s.notes if "historical_observed" in n]
    assert matching, (
        f"pre-watermark comment NOT blocked after sidecar restart; "
        f"watermark is not persisting. notes={s.notes}"
    )
    s2.close()


def test_watermark_only_monotone_increase(env):
    """A subsequent tick MUST NOT lower the watermark. We pre-seed
    the watermark to a value, then run a tick whose max comment id
    is below that value; the watermark must stay put (no clobber).
    """
    gh = env["gh"]
    env["store"].set_watermark(
        repo="neokyhurtado-cmd/traficlab-factory", value=9000
    )
    # Add a comment whose id is well below the watermark.
    gh.add(_make_comment(
        1,
        _directive_body(directive_id="d-low-id", expected_head="NONE"),
    ))

    s = env["handler"].tick(["neokyhurtado-cmd/traficlab-factory"])
    wm = env["store"].get_watermark("neokyhurtado-cmd/traficlab-factory")
    assert wm == 9000, (
        f"watermark must not decrease; got {wm}, expected 9000"
    )
    # The low-id comment is blocked.
    assert s.directives_claimed == 0
    matching = [n for n in s.notes if "historical_observed" in n]
    assert matching, f"low-id pre-watermark comment not blocked; notes={s.notes}"


# ---------- sidecar_store API surface ---------------------------------------
#
# The watermark is persisted in the sidecar with three primitives:
# ``set_watermark``, ``get_watermark``, ``has_watermark``. These tests
# prove the API exists and the basic invariants hold.


def test_watermark_api_set_get_has(tmp_path):
    s = SidecarStore(tmp_path / "sidecar.db")
    repo = "neokyhurtado-cmd/traficlab-factory"
    assert s.has_watermark(repo) is False
    assert s.get_watermark(repo) == 0
    s.set_watermark(repo=repo, value=123)
    assert s.has_watermark(repo) is True
    assert s.get_watermark(repo) == 123
    # Monotone non-decreasing: setting a lower value is a no-op.
    s.set_watermark(repo=repo, value=10)
    assert s.get_watermark(repo) == 123, (
        f"watermark must not decrease; got {s.get_watermark(repo)}"
    )
    # Higher value still works.
    s.set_watermark(repo=repo, value=999)
    assert s.get_watermark(repo) == 999
    s.close()


# ---------- sabotage-run guard ----------------------------------------------


def test_no_unconditional_skip_in_process_comment():
    """Sabotage-run guard: the handler MUST honour the
    ``comment.id <= watermark`` cutoff in ``_process_comment`` — not
    rely on the per-repo cursor or the binding check alone.

    This test inspects the handler source for the specific
    ``historical_observed`` note that the watermark fix added. If a
    future refactor removes the cutoff (e.g. by reverting to "trust
    the per-repo cursor"), this test fails with a clear, diagnostic
    message — the same shape that bit the re-audit in the first
    place.
    """
    import inspect

    src = inspect.getsource(
        __import__("directive_watcher.handler", fromlist=["WatcherHandler"])
        .WatcherHandler._process_comment
    )
    assert "historical_observed" in src, (
        "WatcherHandler._process_comment lost the historical_observed "
        "watermark cutoff. The sentinel NONE / AUTO_FROM_ISSUE_CONTEXT "
        "bypass returns — historical directives can be replayed again."
    )
    assert "watermark" in src.lower(), (
        "WatcherHandler._process_comment lost the watermark check. "
        "The Phase 4 re-audit gap reopens."
    )