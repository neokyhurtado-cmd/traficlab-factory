"""Watcher handler — orchestrates one poll tick end to end.

The handler is the only piece of the watcher that knows the full pipeline:

  list_comments_since → parse_directive → repo/author allowlist →
  sidecar_store.claim → ACK post → execution → RESULT post

The handler is deliberately framework-free. It returns a per-tick summary
so the scheduler can decide whether to retry, sleep, or exit. The
scheduler module wraps this handler in a 5-minute loop; the cron wrapper
hides the loop behind a single subprocess invocation.
"""
from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from directive_watcher.ack_result import (
    AckFacts,
    ResultFacts,
    format_ack,
    format_result,
)
from directive_watcher.allowlist import (
    AllowlistConfig,
    author_in_allowlist,
    evaluate_protected_boundary,
    repo_in_allowlist,
)
from directive_watcher.directive_parser import (
    Directive,
    DirectiveParseError,
    parse_directive,
)
from directive_watcher.evidence import prepare_execution_dir
from directive_watcher.gh_client import GitHubClient, RemoteComment
from directive_watcher.retry import BackoffPolicy, RetryExhausted, call_with_backoff
from directive_watcher.sidecar_store import (
    ACK_CLAIMED,
    RESULT_BLOCKED,
    RESULT_HUMAN_GO,
    RESULT_READY,
    RESULT_SCIENTIFIC,
    AlreadyProcessed,
    SidecarStore,
)

LOG = logging.getLogger("directive_watcher.handler")

TRANSIENT_RETRYABLE = (
    ConnectionError,
    TimeoutError,
)


@dataclass
class TickSummary:
    polled_repos: list[str] = field(default_factory=list)
    comments_seen: int = 0
    directives_parsed: int = 0
    directives_claimed: int = 0
    directives_skipped: int = 0
    directives_failed: int = 0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "polled_repos": list(self.polled_repos),
            "comments_seen": self.comments_seen,
            "directives_parsed": self.directives_parsed,
            "directives_claimed": self.directives_claimed,
            "directives_skipped": self.directives_skipped,
            "directives_failed": self.directives_failed,
            "notes": list(self.notes),
        }


def _sha256(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


# ExecutionStrategy is the seam where the Director would plug in. For this
# ticket we ship a default that records the canonical STATUS_READY /
# STATUS_HUMAN_GO outcomes based on the directive + protected-boundary
# verdict, so the entire pipeline is testable end-to-end without spinning
# up a real Director.
@dataclass
class ExecutionOutcome:
    status: str
    head_after: Optional[str]
    tests: str
    evidence: str


ExecutionFn = Callable[[Directive, str], ExecutionOutcome]


def default_execution(directive: Directive, evidence_dir: str) -> ExecutionOutcome:
    """The default execution strategy for Phase 1.

    Phase 1 does NOT perform merge/release/deploy. For protected-boundary
    directives (those that requested ``REQUIRES_HUMAN_GO_REAL = YES`` and
    would normally cross a protected boundary), we surface
    ``HUMAN_GO_REAL_REQUIRED`` and stop. For ordinary directives we mark
    the run ``READY_FOR_ASTRA_REAUDIT`` so Astra can re-audit. The actual
    code execution of a lawful directive is delegated to whichever tool
    the Director already uses for that scope; this module only records
    the orchestrator-level outcome.

    The Head pointer is read from the local sidecar's ``head_before`` (the
    caller passes it via ``evidence_dir`` metadata). Since this strategy
    does not advance any branch, ``head_after`` is the same as
    ``head_before`` (or ``NONE``).
    """
    # The actual head_before was recorded at claim time. For Phase 1 we
    # intentionally do not advance the branch — the Director's PR (if any)
    # is its own PR. So we report HEAD_AFTER = NONE so Astra knows the
    # branch tip did not move under this orchestration.
    if directive.requires_human_go_real:
        return ExecutionOutcome(
            status=RESULT_HUMAN_GO,
            head_after=None,
            tests="-",
            evidence=evidence_dir,
        )
    return ExecutionOutcome(
        status=RESULT_READY,
        head_after=None,
        tests="-",
        evidence=evidence_dir,
    )


class WatcherHandler:
    """Orchestrates one poll tick. Stateless apart from the store + client."""

    def __init__(
        self,
        *,
        store: SidecarStore,
        gh: GitHubClient,
        allowlist: AllowlistConfig,
        evidence_root: str,
        execution_fn: ExecutionFn = default_execution,
        backoff: BackoffPolicy | None = None,
    ) -> None:
        self._store = store
        self._gh = gh
        self._allowlist = allowlist
        self._evidence_root = evidence_root
        self._execution_fn = execution_fn
        self._backoff = backoff or BackoffPolicy()

    def tick(self, repos: list[str]) -> TickSummary:
        summary = TickSummary(polled_repos=list(repos))
        run_id = self._store.record_run_start(notes=f"repos={len(repos)}")
        try:
            for repo in repos:
                self._tick_repo(repo, summary)
            self._store.record_run_finish(run_id, status="ok")
        except Exception as e:  # noqa: BLE001
            self._store.record_run_finish(run_id, status="error", notes=str(e)[:200])
            raise
        return summary

    # ------------------------------------------------------------------

    def _tick_repo(self, repo: str, summary: TickSummary) -> None:
        since_id = self._store.last_seen_comment_id()
        try:
            comments = call_with_backoff(
                lambda: self._gh.list_comments_since(repo, since_id),
                policy=self._backoff,
                is_retryable=lambda e: isinstance(e, TRANSIENT_RETRYABLE),
            )
        except RetryExhausted as e:
            summary.directives_failed += 1
            summary.notes.append(f"transient_failure:{repo}: {e}")
            LOG.warning("transient failure listing comments for %s: %s", repo, e)
            return
        summary.comments_seen += len(comments)
        for comment in comments:
            self._process_comment(repo, comment, summary)

    def _process_comment(
        self,
        repo: str,
        comment: RemoteComment,
        summary: TickSummary,
    ) -> None:
        body_sha = _sha256(comment.body)
        self._store.mark_seen(comment.id, body_sha)
        try:
            d = parse_directive(comment.body)
        except DirectiveParseError as e:
            # Fail-closed: malformed envelope = information only, never execute.
            # We still ACK no, because an ACK is a promise we'd dispatch —
            # silently skipping is the safe behaviour.
            summary.directives_skipped += 1
            summary.notes.append(f"parse_error:comment={comment.id}: {e}")
            LOG.info("skipping malformed directive in comment %s: %s",
                     comment.id, e)
            return
        if d is None:
            summary.directives_skipped += 1
            return
        summary.directives_parsed += 1

        # 3. Marker absent / fail-closed checks (parser already enforces).
        if not d.directive_id:
            summary.directives_skipped += 1
            return

        # 4. Trust gates.
        if not repo_in_allowlist(d, self._allowlist):
            summary.directives_skipped += 1
            summary.notes.append(
                f"denied:repo_outside_allowlist:{repo}:comment={comment.id}"
            )
            return
        if not author_in_allowlist(comment.author, self._allowlist):
            summary.directives_skipped += 1
            summary.notes.append(
                f"denied:author_not_allowlisted:{comment.author}:comment={comment.id}"
            )
            return

        # 5. Body-edit detection — silent re-run is forbidden.
        # (If we ever ACK a directive_id, then the same comment_id is edited,
        # we surface DIRECTIVE_CHANGED_AFTER_ACK and require a new
        # DIRECTIVE_ID. We never re-execute on a body change.)
        if self._store.detect_body_edit_after_ack(d.directive_id, body_sha):
            summary.directives_skipped += 1
            summary.notes.append(
                f"denied:body_edited_after_ack:{d.directive_id}:comment={comment.id}"
            )
            return

        # 6. Claim.
        try:
            claim = self._store.claim(
                directive_id=d.directive_id,
                source_comment_id=comment.id,
                body_sha256=body_sha,
                head_before=None,  # Director fills in once it spawns a PR
            )
        except AlreadyProcessed:
            summary.directives_skipped += 1
            return

        summary.directives_claimed += 1

        # 7. ACK (best-effort; failure to post does not roll back the claim,
        # because the claim is the durable truth).
        try:
            self._post_ack(repo, comment.issue_number, claim)
        except Exception as e:  # noqa: BLE001
            LOG.warning("ACK post failed for %s: %s", claim.directive_id, e)

        # 8. Prepare evidence dir (skeleton only).
        evidence_dir = prepare_execution_dir(
            self._evidence_root,
            execution_id=claim.execution_id,
            directive_id=d.directive_id,
            source_comment_id=comment.id,
        )

        # 9. Execute.
        try:
            outcome = self._execution_fn(d, str(evidence_dir))
        except Exception as e:  # noqa: BLE001
            LOG.warning("execution failed for %s: %s", d.directive_id, e)
            outcome = ExecutionOutcome(
                status=RESULT_BLOCKED,
                head_after=None,
                tests=f"error: {type(e).__name__}",
                evidence=str(evidence_dir),
            )
            summary.directives_failed += 1

        # 10. Finalise.
        try:
            self._store.record_result(
                d.directive_id, outcome.status, outcome.head_after
            )
        except AlreadyProcessed:
            LOG.warning("duplicate result for %s — skipping", d.directive_id)
            return

        # 11. RESULT post.
        try:
            self._post_result(repo, comment.issue_number, d, claim, outcome, str(evidence_dir))
        except Exception as e:  # noqa: BLE001
            LOG.warning("RESULT post failed for %s: %s", d.directive_id, e)

    # ------------------------------------------------------------------

    def _post_ack(
        self,
        repo: str,
        issue_number: int,
        claim,
    ) -> None:
        body = format_ack(AckFacts(
            directive_id=claim.directive_id,
            source_comment_id=claim.source_comment_id,
            execution_id=claim.execution_id,
            head_before=claim.head_before,
        ))
        call_with_backoff(
            lambda: self._gh.post_comment(repo, issue_number, body),
            policy=self._backoff,
            is_retryable=lambda e: isinstance(e, TRANSIENT_RETRYABLE),
        )

    def _post_result(
        self,
        repo: str,
        issue_number: int,
        d: Directive,
        claim,
        outcome: ExecutionOutcome,
        evidence_dir: str,
    ) -> None:
        body = format_result(ResultFacts(
            directive_id=d.directive_id,
            execution_id=claim.execution_id,
            source_comment_id=claim.source_comment_id,
            status=outcome.status,
            head_after=outcome.head_after,
            tests=outcome.tests,
            evidence=evidence_dir,
        ))
        call_with_backoff(
            lambda: self._gh.post_comment(repo, issue_number, body),
            policy=self._backoff,
            is_retryable=lambda e: isinstance(e, TRANSIENT_RETRYABLE),
        )
