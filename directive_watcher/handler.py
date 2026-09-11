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
import inspect
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
from directive_watcher.gh_client import (
    GHCLIError,
    GitHubClient,
    RemoteComment,
)
from directive_watcher.orch_dispatch import (
    DispatchError,
    DispatchRequest,
    OrchestratorDispatcher,
)
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


def _is_retryable(exc: BaseException) -> bool:
    """Classify an exception for retry.

    Per Fix #5 from the Astra re-audit, the watcher must classify
    production ``gh`` errors correctly:

      - ConnectionError / TimeoutError → retry
      - GHCLIError with retryable exit code/stderr → retry
      - Other Exception subclasses → do NOT retry (fail-closed)
    """
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    if isinstance(exc, GHCLIError):
        return exc.is_retryable
    return False


# Kept for legacy callers that referenced it directly.
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


# ExecutionFn signature is kept stable for callers that supply their own
# implementation: ``(directive, evidence_dir)`` — the handler wraps it
# with a closure that injects dispatcher/source_comment_id/execution_id.
# Custom execution_fn MAY accept those kwargs via **kwargs to opt into
# the dispatcher; otherwise they are ignored and the legacy signature
# keeps working (used by the test suite that asserts behaviour without
# a real dispatcher).
ExecutionFn = Callable[..., ExecutionOutcome]


def default_execution(
    directive: Directive,
    evidence_dir: str,
    *,
    dispatcher: OrchestratorDispatcher | None = None,
    source_comment_id: int = 0,
    execution_id: str = "",
) -> ExecutionOutcome:
    """The default execution strategy for Phase 1.

    Astra re-audit (review 5174697532) flagged that the previous default
    returned READY_FOR_ASTRA_REAUDIT without doing any work — the
    "doorbell but no one opens" failure. This version wires through the
    real orchestrator dispatch seam:

      - Protected-boundary directives (REQUIRES_HUMAN_GO_REAL = YES)
        surface HUMAN_GO_REAL_REQUIRED as before.
      - All other directives MUST go through the dispatcher:
          * If the dispatcher is None (test path with legacy fixtures) we
            emit BLOCKED_EXTERNAL_REAL — never READY without proof.
          * If the dispatcher succeeds, we emit RESULT_DISPATCHED with the
            session_id / kanban_task_id wired into the result so Astra
            sees a real bind.
          * If the dispatcher raises DispatchError, we emit
            BLOCKED_EXTERNAL_REAL with the failure in the evidence path.

    The status string ``READY_FOR_ASTRA_REAUDIT`` is reserved for the
    future case where the dispatcher reports DONE (delegated work
    completed). Until then it is never emitted by the default execution.
    """
    if directive.requires_human_go_real:
        return ExecutionOutcome(
            status=RESULT_HUMAN_GO,
            head_after=None,
            tests="-",
            evidence=evidence_dir,
        )

    if dispatcher is None:
        # No dispatcher → fail-closed. We refuse to emit READY without
        # a session bind; BLOCKED_EXTERNAL_REAL is the honest signal.
        return ExecutionOutcome(
            status=RESULT_BLOCKED,
            head_after=None,
            tests="-",
            evidence=evidence_dir,
        )

    try:
        result = dispatcher.dispatch(
            DispatchRequest(
                directive=directive,
                source_comment_id=source_comment_id,
                execution_id=execution_id,
            )
        )
    except DispatchError as e:
        return ExecutionOutcome(
            status=RESULT_BLOCKED,
            head_after=None,
            tests=f"dispatch_error: {type(e).__name__}",
            evidence=evidence_dir,
        )

    # Dispatch succeeded → session is bound. We emit a new status
    # ``DISPATCHED`` so the handler's RESULT body carries the session_id
    # + kanban_task_id back to GitHub. READY is reserved for completed
    # delegated work — see module docstring.
    return ExecutionOutcome(
        status="DISPATCHED",
        head_after=None,
        tests=f"session_id={result.session_id}; kanban_task_id={result.kanban_task_id}",
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
        dispatcher: OrchestratorDispatcher | None = None,
    ) -> None:
        self._store = store
        self._gh = gh
        self._allowlist = allowlist
        self._evidence_root = evidence_root
        self._backoff = backoff or BackoffPolicy()
        self._dispatcher = dispatcher
        self._current_source_comment_id = 0
        self._current_execution_id = ""
        # Number of recent comments to re-scan each tick for edit
        # detection (Fix #3). Production default: 50 comments = the
        # last ~1 hour of GitHub activity for an active repo.
        self._edit_window = 50
        # Wrap the user-supplied execution_fn so it gets the dispatcher,
        # source_comment_id, and execution_id threaded through. The
        # closure keeps the (Directive, evidence_dir) signature stable
        # for callers that supply their own execution_fn.
        base_fn = execution_fn
        # Detect whether base_fn declares the extra kwargs (dispatcher,
        # source_comment_id, execution_id). If not, we fall back to the
        # legacy (directive, evidence_dir) call — this keeps the existing
        # test suite (which uses plain `def custom(d, e)`) green.
        try:
            base_params = inspect.signature(base_fn).parameters
            accepts_dispatcher = any(
                p in base_params
                for p in ("dispatcher", "source_comment_id", "execution_id")
            )
        except (TypeError, ValueError):
            accepts_dispatcher = False

        def _wrapped(directive: Directive, evidence_dir: str) -> ExecutionOutcome:
            if accepts_dispatcher:
                return base_fn(
                    directive,
                    evidence_dir,
                    dispatcher=self._dispatcher,
                    source_comment_id=self._current_source_comment_id,
                    execution_id=self._current_execution_id,
                )
            return base_fn(directive, evidence_dir)

        self._execution_fn = _wrapped

    def tick(self, repos: list[str]) -> TickSummary:
        summary = TickSummary(polled_repos=list(repos))
        run_id = self._store.record_run_start(notes=f"repos={len(repos)}")
        try:
            # Fix #4: publish-durable recovery. Before polling, drain
            # any rows that owe a GitHub publication (ACK or RESULT)
            # from a previous tick. We do this FIRST so a transient
            # outage at tick N doesn't drop the message permanently.
            self._republish_pending_publications(summary)
            for repo in repos:
                self._tick_repo(repo, summary)
            self._store.record_run_finish(run_id, status="ok")
        except Exception as e:  # noqa: BLE001
            self._store.record_run_finish(run_id, status="error", notes=str(e)[:200])
            raise
        return summary

    def _republish_pending_publications(self, summary: TickSummary) -> None:
        """Re-post ACK / RESULT for any directive whose previous attempt failed.

        This is the durable-retry path the re-audit asked for: business
        outcome stays recorded, publication gets its own retry budget.
        """
        for row in self._store.list_pending_publications():
            did = row["directive_id"]
            # We don't have the directive body here — but we DO have the
            # claim row, so we can re-post from the stored fields.
            rec = self._store.get_processed(did)
            if rec is None:
                continue
            # ACK is republishable if ack_posted=0
            if not row["ack_posted"]:
                try:
                    ack_claim = type("C", (), {
                        "directive_id": did,
                        "source_comment_id": row["source_comment_id"],
                        "execution_id": row["execution_id"],
                        "head_before": rec.get("head_before"),
                    })()
                    self._post_ack("", row["source_comment_id"], ack_claim)
                except Exception as e:  # noqa: BLE001
                    LOG.warning("ACK republish failed for %s: %s", did, e)
                    self._store.mark_post_failed(
                        did, f"ack_republish: {type(e).__name__}: {e}"
                    )
                    continue
            # RESULT is republishable if result_status IS NOT NULL and
            # result_posted=0.
            if row["result_status"] and not row["result_posted"]:
                try:
                    outcome = ExecutionOutcome(
                        status=row["result_status"],
                        head_after=rec.get("head_after"),
                        tests=rec.get("last_body_sha256") or "-",
                        evidence=str(self._evidence_root),
                    )
                    d_stub = type("D", (), {
                        "directive_id": did,
                    })()
                    claim = type("C", (), {
                        "directive_id": did,
                        "source_comment_id": row["source_comment_id"],
                        "execution_id": row["execution_id"],
                    })()
                    self._post_result(
                        "", row["source_comment_id"], d_stub, claim,
                        outcome, str(self._evidence_root),
                    )
                except Exception as e:  # noqa: BLE001
                    LOG.warning("RESULT republish failed for %s: %s", did, e)
                    self._store.mark_post_failed(
                        did, f"result_republish: {type(e).__name__}: {e}"
                    )
                    continue

    # ------------------------------------------------------------------

    def _tick_repo(self, repo: str, summary: TickSummary) -> None:
        # Per-repo cursor (Fix #2 from Astra re-audit) — the global
        # ``last_seen_comment_id`` is no longer authoritative for the
        # poll tick. We still bump it for the global view (so legacy
        # readers of ``watcher_status.json`` keep working) but the
        # actual filter uses ``store.get_cursor(repo)``.
        since_id = self._store.get_cursor(repo)
        try:
            new_comments = call_with_backoff(
                lambda: self._gh.list_comments_since(repo, since_id),
                policy=self._backoff,
                is_retryable=_is_retryable,
            )
            recent_comments = call_with_backoff(
                lambda: self._gh.list_recent_comments(repo, limit=self._edit_window),
                policy=self._backoff,
                is_retryable=_is_retryable,
            )
        except RetryExhausted as e:
            summary.directives_failed += 1
            summary.notes.append(f"transient_failure:{repo}: {e}")
            LOG.warning("transient failure listing comments for %s: %s", repo, e)
            return

        # Fix #3: edit detection — re-observe already-seen comments and
        # surface any body_sha change. We merge recent (already-seen
        # window) + new (id > since_id) into a single deduped stream.
        # Without this, the legacy ``id > since_id`` filter would
        # permanently skip edited comments.
        seen_ids: set[int] = set()
        merged: list[RemoteComment] = []
        for c in recent_comments:
            if c.id not in seen_ids:
                seen_ids.add(c.id)
                merged.append(c)
        for c in new_comments:
            if c.id not in seen_ids:
                seen_ids.add(c.id)
                merged.append(c)
        merged.sort(key=lambda c: c.id)

        summary.comments_seen += len(merged)
        # Advance the per-repo cursor. We use the max id of ``new_comments``
        # (genuinely new) — ``recent_comments`` may contain ids older
        # than the cursor by design (edit window), so we don't take its
        # max as the cursor.
        max_id = since_id
        for comment in merged:
            self._process_comment(repo, comment, summary)
            if comment.id > since_id and comment.id > max_id:
                max_id = comment.id
        if max_id > since_id:
            self._store.upsert_cursor(repo=repo, last_seen_comment_id=max_id)

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

        # Stash source_comment_id + execution_id so the wrapped
        # execution_fn can pass them to the dispatcher.
        self._current_source_comment_id = comment.id
        self._current_execution_id = claim.execution_id

        # 7. ACK (best-effort; failure to post does not roll back the claim,
        # because the claim is the durable truth).
        try:
            self._post_ack(repo, comment.issue_number, claim)
        except Exception as e:  # noqa: BLE001
            LOG.warning("ACK post failed for %s: %s", claim.directive_id, e)
            self._store.mark_post_failed(
                claim.directive_id, f"ack_post: {type(e).__name__}: {e}"
            )

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
            self._store.mark_post_failed(
                d.directive_id, f"result_post: {type(e).__name__}: {e}"
            )

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
            is_retryable=_is_retryable,
        )
        # Fix #4: separate "delivered" from "finalised". Even if the
        # call raised above and we caught it, we only mark posted on
        # success. The caller wraps this in try/except to surface
        # failures to the durable publication list.
        self._store.mark_ack_posted(claim.directive_id)

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
            is_retryable=_is_retryable,
        )
        self._store.mark_result_posted(d.directive_id)
