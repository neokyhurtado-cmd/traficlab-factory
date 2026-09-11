"""Tests for CONTEXT_BINDING_FAIL_CLOSED contracts (PR #19 closeout).

These tests encode the 5 frozen context-binding contracts the directive
watcher must satisfy before activation. Each test reads as a behavioural
contract:

  - REPO_BINDING:     directive.repository == actual_repo
  - ISSUE_BINDING:    directive.issue      == comment.issue_number
  - HEAD_BINDING:     directive.expected_head == gh.get_branch_head(repo, branch)
  - AUTO_FROM_CTX:    if YES, resolve from context; if NO, keep envelope literal;
                      fail-closed when YES + insufficient context
  - FRESH_START:      empty sidecar + historical comment → cursor seeded, no replay

The sabotage run is the explicit guarantee: removing the production fix must
turn the test RED with the on-topic "context binding fail-closed" message.
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
    directive_id: str = "d-ctx-1",
    repository: str = "neokyhurtado-cmd/traficlab-factory",
    issue: int = 18,
    target_branch: str = "feat/hermes-2.0-github-directive-watcher",
    expected_head: str = "07d44c33649a4a29a141a9d477fb22200a542529",
    auto_from_ctx: str = "NO",
) -> str:
    return textwrap.dedent(
        f"""\
        [ASTRA_DIRECTIVE:v1]
        ACTION = CONTINUE
        REPOSITORY = {repository}
        ISSUE = {issue}
        TARGET_BRANCH = {target_branch}
        EXPECTED_HEAD = {expected_head}
        SCOPE = ctx binding closeout
        AUTO_NEXT_SAFE_GATE = NO
        REQUIRES_HUMAN_GO_REAL = NO
        DIRECTIVE_ID = {directive_id}
        AUTO_FROM_ISSUE_CONTEXT = {auto_from_ctx}
        """
    )


@pytest.fixture
def env(tmp_path: Path):
    store = SidecarStore(tmp_path / "sidecar.db")
    # SEGURO B / FRESH_START_WATERMARK (PR #19 Phase 4 closeout):
    # pre-seed the watermark to 0 so the existing CONTEXT_BINDING_FAIL_CLOSED
    # fixtures are treated as "already-seeded". The cutoff is the
    # subject of the dedicated SEGURO B tests in
    # ``test_fresh_start_watermark.py``; here we want to assert the
    # binding behaviour independently of the temporal cutoff.
    store.set_watermark(repo="neokyhurtado-cmd/traficlab-factory", value=0)
    store.set_watermark(repo="neokyhurtado-cmd/IA-VISION", value=0)
    gh = FakeGitHubClient()
    allowlist = AllowlistConfig(
        allowlisted_repos=frozenset({
            "neokyhurtado-cmd/traficlab-factory",
            "neokyhurtado-cmd/IA-VISION",
        }),
        allowlisted_authors=frozenset({"neokyhurtado-cmd"}),
    )
    handler = WatcherHandler(
        store=store,
        gh=gh,
        allowlist=allowlist,
        evidence_root=str(tmp_path),
        backoff=BackoffPolicy(initial_seconds=0.001, max_attempts=2),
    )
    # Seed the fake gh client's view of HEAD for the repo we test against.
    # The handler reads ``gh.get_branch_head(repo, branch)``; for the
    # default branch the canonical name is the repo's HEAD ref.
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


# =============================================================================
# CONTRACT 1 — REPO_BINDING
# =============================================================================


def test_repo_binding_admits_directive_that_matches_actual_repo(env):
    """Envelope REPOSITORY == poll repo → разрешено."""
    gh = env["gh"]
    gh.add(_make_comment(101, _directive_body(
        directive_id="d-repo-match",
        repository="neokyhurtado-cmd/traficlab-factory",
    )))
    s = env["handler"].tick(["neokyhurtado-cmd/traficlab-factory"])
    assert s.directives_claimed == 1
    assert not any("directive repo" in n for n in s.notes), s.notes


def test_repo_binding_blocks_directive_whose_repo_differs(env):
    """Envelope REPOSITORY == IA-VISION while polling traficlab-factory → BLOCKED."""
    gh = env["gh"]
    gh.add(_make_comment(101, _directive_body(
        directive_id="d-repo-mismatch",
        repository="neokyhurtado-cmd/IA-VISION",
    )))
    s = env["handler"].tick(["neokyhurtado-cmd/traficlab-factory"])
    assert s.directives_claimed == 0
    assert s.directives_skipped >= 1
    # Must surface the specific contract message + the offending pair.
    matching = [n for n in s.notes if "directive repo" in n and "IA-VISION" in n]
    assert matching, f"expected contract #1 note, got notes={s.notes}"
    assert any("traficlab-factory" in n for n in matching)
    # No ACK or RESULT on the wire — this is a BLOCK.
    assert gh.posted == []


# =============================================================================
# CONTRACT 2 — ISSUE_BINDING
# =============================================================================


def test_issue_binding_admits_directive_that_matches_comment(env):
    """Envelope ISSUE == comment.issue_number → разрешено."""
    gh = env["gh"]
    gh.add(_make_comment(
        101,
        _directive_body(directive_id="d-issue-match", issue=18),
        issue_number=18,
    ))
    s = env["handler"].tick(["neokyhurtado-cmd/traficlab-factory"])
    assert s.directives_claimed == 1


def test_issue_binding_blocks_directive_whose_issue_differs(env):
    """Envelope ISSUE == 99 but comment is on issue 18 → BLOCKED."""
    gh = env["gh"]
    gh.add(_make_comment(
        101,
        _directive_body(directive_id="d-issue-mismatch", issue=99),
        issue_number=18,
    ))
    s = env["handler"].tick(["neokyhurtado-cmd/traficlab-factory"])
    assert s.directives_claimed == 0
    matching = [n for n in s.notes if "directive issue" in n and "99" in n and "18" in n]
    assert matching, f"expected contract #2 note, got notes={s.notes}"
    assert gh.posted == []


# =============================================================================
# CONTRACT 3 — EXPECTED_HEAD_BINDING
# =============================================================================


def test_head_binding_admits_when_expected_head_matches_branch_head(env):
    """EXPECTED_HEAD == gh.get_branch_head(repo, branch) → разрешено."""
    gh = env["gh"]
    gh.add(_make_comment(101, _directive_body(
        directive_id="d-head-match",
        expected_head="07d44c33649a4a29a141a9d477fb22200a542529",
    )))
    s = env["handler"].tick(["neokyhurtado-cmd/traficlab-factory"])
    assert s.directives_claimed == 1


def test_head_binding_blocks_when_expected_head_is_stale(env):
    """Historical directive EXPECTED_HEAD=cd7c809... against current 07d44c33 → BLOCKED."""
    gh = env["gh"]
    gh.add(_make_comment(101, _directive_body(
        directive_id="d-head-stale",
        expected_head="cd7c8091111111111111111111111111111111111",
    )))
    s = env["handler"].tick(["neokyhurtado-cmd/traficlab-factory"])
    assert s.directives_claimed == 0
    matching = [n for n in s.notes if "EXPECTED_HEAD" in n and "mismatch" in n]
    assert matching, f"expected contract #3 mismatch note, got notes={s.notes}"
    assert gh.posted == []


def test_head_binding_blocks_when_expected_head_is_empty(env):
    """Empty EXPECTED_HEAD is fail-closed (no silent defaults)."""
    gh = env["gh"]
    body = _directive_body(directive_id="d-head-empty", expected_head="")
    gh.add(_make_comment(101, body))
    s = env["handler"].tick(["neokyhurtado-cmd/traficlab-factory"])
    assert s.directives_claimed == 0
    matching = [n for n in s.notes if "EXPECTED_HEAD missing" in n]
    assert matching, f"expected missing-head note, got notes={s.notes}"


def test_head_binding_blocks_when_branch_cannot_be_resolved(env):
    """If gh.get_branch_head returns None, the directive is BLOCKED fail-closed."""
    gh = env["gh"]
    # Do NOT seed the branch head for this repo.
    # Poll a repo that is allowlisted but has no seeded HEAD.
    body = _directive_body(
        directive_id="d-head-unresolvable",
        repository="neokyhurtado-cmd/IA-VISION",
        issue=99,
        expected_head="anything",
    )
    gh.add(_make_comment(101, body, issue_number=99))
    s = env["handler"].tick(["neokyhurtado-cmd/IA-VISION"])
    # Cannot resolve branch head → fail-closed BLOCK (not skip).
    assert s.directives_failed >= 1
    matching = [n for n in s.notes if "cannot resolve branch head" in n]
    assert matching, f"expected unresolvable-head note, got notes={s.notes}"


# =============================================================================
# CONTRACT 4 — AUTO_FROM_ISSUE_CONTEXT with fail-closed
# =============================================================================


def test_auto_from_ctx_yes_with_sufficient_context_overrides_envelope(env):
    """AUTO_FROM_ISSUE_CONTEXT=YES + comment.issue_number set → envelope REPOSITORY/ISSUE
    are overridden with the actual context."""
    gh = env["gh"]
    # Envelope says IA-VISION but poll repo is traficlab-factory; with
    # AUTO_FROM_ISSUE_CONTEXT=YES the repo/issue MUST be overwritten to the
    # actual context, and the directive must proceed if HEAD also matches.
    body = textwrap.dedent("""\
        [ASTRA_DIRECTIVE:v1]
        ACTION = CONTINUE
        REPOSITORY = neokyhurtado-cmd/IA-VISION
        ISSUE = 99
        TARGET_BRANCH = feat/hermes-2.0-github-directive-watcher
        EXPECTED_HEAD = 07d44c33649a4a29a141a9d477fb22200a542529
        SCOPE = auto ctx yes
        AUTO_NEXT_SAFE_GATE = NO
        REQUIRES_HUMAN_GO_REAL = NO
        DIRECTIVE_ID = d-auto-yes
        AUTO_FROM_ISSUE_CONTEXT = YES
        """)
    # Seed HEAD for both repos (the resolved one is traficlab-factory).
    gh.set_branch_head(
        "neokyhurtado-cmd/traficlab-factory",
        "feat/hermes-2.0-github-directive-watcher",
        "07d44c33649a4a29a141a9d477fb22200a542529",
    )
    gh.add(_make_comment(101, body, issue_number=18))
    s = env["handler"].tick(["neokyhurtado-cmd/traficlab-factory"])
    assert s.directives_claimed == 1, (
        f"AUTO_FROM_ISSUE_CONTEXT=YES with sufficient context must override; "
        f"got claimed={s.directives_claimed}, notes={s.notes}"
    )


def test_auto_from_ctx_yes_without_issue_number_blocks_fail_closed(env):
    """AUTO_FROM_ISSUE_CONTEXT=YES but comment has no issue_number (e.g. PR
    review comment) → BLOCKED fail-closed, no silent defaults."""
    gh = env["gh"]
    body = textwrap.dedent("""\
        [ASTRA_DIRECTIVE:v1]
        ACTION = CONTINUE
        REPOSITORY = neokyhurtado-cmd/traficlab-factory
        ISSUE = 18
        TARGET_BRANCH = feat/hermes-2.0-github-directive-watcher
        EXPECTED_HEAD = 07d44c33649a4a29a141a9d477fb22200a542529
        SCOPE = auto ctx yes no issue
        AUTO_NEXT_SAFE_GATE = NO
        REQUIRES_HUMAN_GO_REAL = NO
        DIRECTIVE_ID = d-auto-yes-no-issue
        AUTO_FROM_ISSUE_CONTEXT = YES
        """)
    c = _make_comment(101, body, issue_number=0)  # 0 = no issue
    gh.add(c)
    s = env["handler"].tick(["neokyhurtado-cmd/traficlab-factory"])
    assert s.directives_claimed == 0
    matching = [n for n in s.notes if "AUTO_FROM_ISSUE_CONTEXT" in n and "issue_number" in n]
    assert matching, f"expected AUTO_FROM_ISSUE_CONTEXT fail-closed note, got notes={s.notes}"


def test_auto_from_ctx_no_uses_envelope_literal(env):
    """AUTO_FROM_ISSUE_CONTEXT=NO (default) → envelope REPOSITORY/ISSUE literal,
    so an envelope pointing to a different repo is BLOCKED by Contract #1."""
    gh = env["gh"]
    body = textwrap.dedent("""\
        [ASTRA_DIRECTIVE:v1]
        ACTION = CONTINUE
        REPOSITORY = neokyhurtado-cmd/IA-VISION
        ISSUE = 99
        TARGET_BRANCH = feat/hermes-2.0-github-directive-watcher
        EXPECTED_HEAD = 07d44c33649a4a29a141a9d477fb22200a542529
        SCOPE = auto ctx no
        AUTO_NEXT_SAFE_GATE = NO
        REQUIRES_HUMAN_GO_REAL = NO
        DIRECTIVE_ID = d-auto-no
        AUTO_FROM_ISSUE_CONTEXT = NO
        """)
    gh.add(_make_comment(101, body, issue_number=99))
    s = env["handler"].tick(["neokyhurtado-cmd/traficlab-factory"])
    # Contract #1 must still fire: envelope says IA-VISION, polling traficlab-factory.
    assert s.directives_claimed == 0
    assert any("directive repo" in n for n in s.notes), s.notes


# =============================================================================
# CONTRACT 5 — FRESH_START_NO_HISTORY_REPLAY
# =============================================================================


def test_fresh_start_does_not_claim_historical_directive_with_stale_head(env):
    """Empty sidecar + historical comment with stale EXPECTED_HEAD → BLOCKED
    by Contract #3. No run record claims it; cursor seeds to max id."""
    tmp_path = env["tmp_path"]
    gh = env["gh"]
    # Brand-new empty sidecar.
    assert env["store"].get_cursor("neokyhurtado-cmd/traficlab-factory") == 0
    # Historical directive: stale HEAD.
    gh.add(_make_comment(
        42,
        _directive_body(
            directive_id="ASTRA-FACTORY18-PR19-REPLAN-V2-20260910",
            expected_head="cd7c8091111111111111111111111111111111111",
        ),
    ))
    s = env["handler"].tick(["neokyhurtado-cmd/traficlab-factory"])
    # Stale HEAD → Contract #3 rejects.
    assert s.directives_claimed == 0
    assert s.directives_failed == 0  # reject is SKIP not FAIL
    # No run record moved it to finalised.
    rec = env["store"].get_processed("ASTRA-FACTORY18-PR19-REPLAN-V2-20260910")
    assert rec is None
    # Cursor DID advance so we don't re-poll the same comment.
    assert env["store"].get_cursor("neokyhurtado-cmd/traficlab-factory") >= 42


def test_fresh_start_admits_historical_comment_with_current_head(env):
    """Empty sidecar + comment whose EXPECTED_HEAD == current HEAD → разрешено
    (this is the historical comment that genuinely targets the current branch)."""
    gh = env["gh"]
    gh.add(_make_comment(
        7,
        _directive_body(
            directive_id="ASTRA-FACTORY18-PR19-CURRENT",
            expected_head="07d44c33649a4a29a141a9d477fb22200a542529",
        ),
    ))
    s = env["handler"].tick(["neokyhurtado-cmd/traficlab-factory"])
    assert s.directives_claimed == 1


# =============================================================================
# CONTRACT 6 — PROD/TEST ENV SEPARATION  (CLI flag)
# =============================================================================
# Imported here from a sibling module so this file remains the canonical
# closeout test seam. Tests live in test_cli_env_separation.py.