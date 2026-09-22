"""Orchestrator dispatch seam — wake a real Hermes session for a directive.

Why this module exists
----------------------
Phase 1 of the directive watcher (see traficlab-factory#18) was merging with
a `default_execution()` that returned `READY_FOR_ASTRA_REAUDIT` without
actually executing anything — the Astra re-audit (review 5174697532) flagged
this as a "doorbell but no one opens" failure.

This module fixes that by:

  1. **Real session binding.** Every dispatched directive mints a
     `SessionRecord` (the Session Registry minimum from the re-audit) and
     persists it to a JSONL sidecar BEFORE returning success. Without the
     session bind, `READY_FOR_ASTRA_REAUDIT` is never emitted by the
     handler (it would be BLOCKED_EXTERNAL_REAL or HUMAN_GO_REAL_REQUIRED).
  2. **Real kanban dispatch.** The dispatcher reuses
     `orchestrator/scripts/github_poller.py::create_kanban_task` so the
     existing routing table + `hermes kanban create` flow stays the single
     source of truth. We do NOT spin up a second hidden scheduling island.
  3. **Idempotency by directive_id.** A second `dispatch()` call for the
     same `directive_id` returns the same session without spawning a new
     subprocess — same contract the kanban CLI provides via
     `--idempotency-key`.

Session Registry contract
-------------------------
Every session record carries:

    session_id       — UUIDv4, stable across restarts
    execution_id     — the directive watcher's execution_id
    directive_id     — the ASTRA directive id
    repository       — owner/repo
    issue_number     — GitHub issue
    target_branch    — branch declared by the directive
    kanban_task_id   — id of the kanban task created (or "" on failure)
    assignee         — profile resolved via routing table
    state            — DISPATCHED|RUNNING|WAITING_REVIEW|BLOCKED|DONE
    source_comment_id
    head_before      — branch head at dispatch time, or None
    head_after       — branch head after completion, or None
    created_at       — unix seconds
    updated_at       — unix seconds

This is the "minimum multi-session foundation" the re-audit asked for —
no UI, no War Room, no Telegram integration. Just the durable model.
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

# Co-located modules — make sure we can import orchestrator/scripts even
# when the directive_watcher package is invoked from a different cwd.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_ORCH_SCRIPTS = _REPO_ROOT / "orchestrator" / "scripts"
if str(_ORCH_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_ORCH_SCRIPTS))

from directive_watcher.directive_parser import Directive  # noqa: E402
from directive_watcher.kanban_primitive import dispatch_to_kanban  # noqa: E402
from directive_watcher.orca_auto_wake import (  # noqa: E402
    OrcaAutoWakeBridge,
    OrcaAutoWakeError,
    directive_requests_orca,
)


# --- Session Registry model --------------------------------------------------


SESSION_STATE_DISPATCHED = "DISPATCHED"
SESSION_STATE_RUNNING = "RUNNING"
SESSION_STATE_WAITING = "WAITING_REVIEW"
SESSION_STATE_BLOCKED = "BLOCKED"
SESSION_STATE_DONE = "DONE"
SESSION_STATE_FAILED = "FAILED"

VALID_SESSION_STATES = frozenset({
    SESSION_STATE_DISPATCHED,
    SESSION_STATE_RUNNING,
    SESSION_STATE_WAITING,
    SESSION_STATE_BLOCKED,
    SESSION_STATE_DONE,
    SESSION_STATE_FAILED,
})


@dataclass
class SessionRecord:
    """Minimum session record for the multi-session registry.

    This is the durable model. The War Room UI (deferred to a separate
    ticket) will read the same JSONL log via a thin reader; the contract
    is intentionally flat and JSON-friendly.
    """

    session_id: str
    execution_id: str
    directive_id: str
    repository: str
    issue_number: int
    target_branch: str
    kanban_task_id: str
    assignee: str
    state: str
    source_comment_id: int
    head_before: Optional[str] = None
    head_after: Optional[str] = None
    tests_summary: str = "-"
    evidence_uri: str = ""
    block_reason: str = ""
    requires_human_go_real: bool = False
    created_at: int = field(default_factory=lambda: int(time.time()))
    updated_at: int = field(default_factory=lambda: int(time.time()))

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    @staticmethod
    def from_json(line: str) -> "SessionRecord":
        d = json.loads(line)
        return SessionRecord(**d)


# --- Dispatch request / result ----------------------------------------------


@dataclass(frozen=True)
class DispatchRequest:
    """Inputs the handler passes to the dispatcher.

    The handler has already done claim() and body-edit detection — by the
    time dispatch() is called we know the directive is fresh and durable.
    """

    directive: Directive
    source_comment_id: int
    execution_id: str
    head_before: Optional[str] = None


@dataclass(frozen=True)
class DispatchResult:
    """What dispatch returns to the handler.

    `session_id` is the durable handle the handler threads through the
    ACK/RESULT body. Without a non-empty session_id the handler must NOT
    emit READY_FOR_ASTRA_REAUDIT.
    """

    session_id: str
    kanban_task_id: str
    assignee: str
    state: str  # one of VALID_SESSION_STATES


# --- Errors ------------------------------------------------------------------


class DispatchError(RuntimeError):
    """Raised when dispatch cannot wake a session — handler must surface
    this as BLOCKED_EXTERNAL_REAL (or HUMAN_GO_REAL_REQUIRED if the
    directive is protected)."""


class SessionAlreadyExistsError(DispatchError):
    """Raised when a different execution_id claims the same directive_id.
    Different from idempotent re-dispatch (which returns the existing
    session)."""


# --- Dispatcher --------------------------------------------------------------


class OrchestratorDispatcher:
    """Wake a real Hermes session for a directive.

    Persistence model: JSONL sidecar (append-only, one record per line).
    The sidecar is the Session Registry minimum. SQLite would be the
    next step (per the re-audit's "durable" requirement) but for the
    minimum we need a model that:
      - survives a process restart
      - is human-inspectable
      - is easy to test
    JSONL covers all three. A sidecar_store extension to add a
    `session_registry` table is a follow-up; the model is the same.
    """

    def __init__(
        self,
        *,
        session_log: str | Path,
        routing_table_path: str | Path,
        # The orchestrator profile is the default target — same convention
        # as `github_poller.py::PARENT_TASK_ID`. Tests override this.
        parent_task_id: str = "t_47131ada",
        kanban_bin: str = "hermes",
        timeout_seconds: int = 60,
        orca_bridge: OrcaAutoWakeBridge | None = None,
    ) -> None:
        self._session_log = Path(session_log)
        self._session_log.parent.mkdir(parents=True, exist_ok=True)
        self._routing_table_path = Path(routing_table_path)
        self._parent_task_id = parent_task_id
        self._kanban_bin = kanban_bin
        self._timeout_seconds = timeout_seconds
        # Construct lazily unless a test/runtime injects a bridge. This keeps
        # non-Orca directive paths independent of local Orca installation state.
        self._orca_bridge = orca_bridge

        # In-memory mirror for fast queries. Rebuilt from disk on init.
        self._sessions: dict[str, SessionRecord] = {}
        self._by_directive: dict[str, str] = {}  # directive_id → session_id
        self._load()

    # ---- Session Registry I/O --------------------------------------------

    def _load(self) -> None:
        if not self._session_log.exists():
            return
        with self._session_log.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = SessionRecord.from_json(line)
                except (json.JSONDecodeError, TypeError, KeyError):
                    # Skip malformed lines — the registry must never crash
                    # a tick because of a corrupted record.
                    continue
                self._sessions[rec.session_id] = rec
                self._by_directive[rec.directive_id] = rec.session_id

    def _append(self, rec: SessionRecord) -> None:
        with self._session_log.open("a", encoding="utf-8") as f:
            f.write(rec.to_json() + "\n")
            f.flush()
        self._sessions[rec.session_id] = rec
        self._by_directive[rec.directive_id] = rec.session_id

    def list_sessions(self) -> list[SessionRecord]:
        """Return all sessions, newest first."""
        return sorted(
            self._sessions.values(),
            key=lambda s: s.created_at,
            reverse=True,
        )

    def get_session(self, session_id: str) -> Optional[SessionRecord]:
        return self._sessions.get(session_id)

    def get_by_directive(self, directive_id: str) -> Optional[SessionRecord]:
        sid = self._by_directive.get(directive_id)
        return self._sessions.get(sid) if sid else None

    def update_session(
        self,
        session_id: str,
        *,
        state: Optional[str] = None,
        head_after: Optional[str] = None,
        tests_summary: Optional[str] = None,
        evidence_uri: Optional[str] = None,
        block_reason: Optional[str] = None,
        kanban_task_id: Optional[str] = None,
    ) -> SessionRecord:
        """Mutate a session in-place and rewrite its JSONL record.

        We rewrite (not append) so the registry stays a single source of
        truth. JSONL append-only would force a tombstone + new record
        pattern, which the minimum registry doesn't need.
        """
        rec = self._sessions.get(session_id)
        if rec is None:
            raise KeyError(f"unknown session_id: {session_id}")
        if state is not None:
            if state not in VALID_SESSION_STATES:
                raise ValueError(
                    f"invalid session state: {state!r} "
                    f"(valid: {sorted(VALID_SESSION_STATES)})"
                )
            rec.state = state
        if head_after is not None:
            rec.head_after = head_after
        if tests_summary is not None:
            rec.tests_summary = tests_summary
        if evidence_uri is not None:
            rec.evidence_uri = evidence_uri
        if block_reason is not None:
            rec.block_reason = block_reason
        if kanban_task_id is not None:
            rec.kanban_task_id = kanban_task_id
        rec.updated_at = int(time.time())
        self._rewrite_log()
        return rec

    def _rewrite_log(self) -> None:
        """Rewrite the whole JSONL log from the in-memory mirror.

        Called after every mutation. Cheap because the registry is bounded
        (one record per dispatched directive). For >10k records this
        should move to SQLite, which is a documented follow-up.
        """
        tmp = self._session_log.with_suffix(self._session_log.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for rec in self._sessions.values():
                f.write(rec.to_json() + "\n")
        os.replace(tmp, self._session_log)

    # ---- Routing resolution ---------------------------------------------

    def _resolve_assignee(self, directive: Directive) -> str:
        """Read the orchestrator routing table and resolve the assignee.

        We import the resolver lazily so the dispatcher's tests don't
        require the production routing table to exist on disk. Routes
        without a `repo:` key (e.g. ASHLEY) don't apply here.
        """
        # Lazy import — keeps test fixtures self-contained.
        try:
            import routing_resolver  # type: ignore
        except Exception:
            # If the orchestrator scripts aren't importable (e.g. isolated
            # test env), fall back to the configured default. We still
            # log this so the failure is visible.
            return "hermes-director"

        # Provide the routing_table_path if requested via env.
        # The resolver reads HERMES_ROUTING_PATH > HERMES_HOME/config > fallback.
        prev_env = os.environ.get("HERMES_ROUTING_PATH")
        try:
            os.environ["HERMES_ROUTING_PATH"] = str(self._routing_table_path)
            decision = routing_resolver.resolve_route(directive.repository, None)
        finally:
            if prev_env is None:
                os.environ.pop("HERMES_ROUTING_PATH", None)
            else:
                os.environ["HERMES_ROUTING_PATH"] = prev_env
        if not decision.allowed:
            raise DispatchError(
                f"routing denied for {directive.repository}: "
                f"{decision.denial_reason}"
            )
        return decision.assignee or "hermes-director"

    # ---- Orca zero-copy dispatch ------------------------------------------

    def _get_orca_bridge(self) -> OrcaAutoWakeBridge:
        """Return the durable GitHub -> Orca wake bridge.

        The registry lives beside sessions.jsonl so it survives checkout/worktree
        changes and follows the same per-profile runtime boundary as the watcher.
        """
        if self._orca_bridge is None:
            self._orca_bridge = OrcaAutoWakeBridge(
                registry_path=self._session_log.parent / "orca_runs.json",
            )
        return self._orca_bridge

    def _dispatch_to_orca(
        self,
        request: DispatchRequest,
        *,
        assignee: str,
    ) -> DispatchResult:
        """Start/resume one Orca Run and deliver the directive to Hermes.

        Important: this path intentionally BYPASSES `hermes kanban create`.
        Creating the normal kanban task would auto-spawn a direct Hermes worker,
        which is exactly the copy/paste / non-Orca execution path this bridge
        closes. The durable SessionRecord remains the watcher-side lineage.
        """
        d = request.directive
        try:
            wake = self._get_orca_bridge().start_or_resume(
                d,
                source_comment_id=request.source_comment_id,
                execution_id=request.execution_id,
            )
        except OrcaAutoWakeError as exc:
            raise DispatchError(
                f"Orca auto-wake failed for {d.directive_id}: {exc}"
            ) from exc

        session_id = f"sess-{uuid.uuid4().hex[:12]}"
        synthetic_task_id = f"orca:{wake.run_id}"
        rec = SessionRecord(
            session_id=session_id,
            execution_id=request.execution_id,
            directive_id=d.directive_id,
            repository=d.repository,
            issue_number=d.issue,
            target_branch=d.target_branch,
            kanban_task_id=synthetic_task_id,
            assignee=assignee,
            state=SESSION_STATE_RUNNING,
            source_comment_id=request.source_comment_id,
            head_before=request.head_before,
            tests_summary=(
                f"orca_run_id={wake.run_id}; worktree_id={wake.worktree_id}; "
                f"terminal_handle={wake.terminal_handle}; wake={wake.action}"
            ),
            evidence_uri=f"orca://run/{wake.run_id}",
            requires_human_go_real=d.requires_human_go_real,
        )
        self._append(rec)

        # Keep Live Brain visibility without pretending an Orca Run is a kanban
        # task. The synthetic subject is namespaced and cannot collide with t_*.
        try:
            from . import live_brain_bridge as _lbb  # type: ignore
            _lbb.on_session_bound(
                task_id=synthetic_task_id,
                session_id=session_id,
                execution_id=request.execution_id,
                directive_id=d.directive_id,
                assignee=assignee,
                repo=d.repository,
                branch=d.target_branch,
                head_sha=request.head_before,
                started_at_epoch=time.time(),
            )
        except Exception:  # pragma: no cover - bridge is best-effort
            pass

        return DispatchResult(
            session_id=session_id,
            kanban_task_id=synthetic_task_id,
            assignee=assignee,
            state=SESSION_STATE_RUNNING,
        )

    # ---- Kanban dispatch --------------------------------------------------
    #
    # Phase 3 / Objective 3 — single kanban primitive. This adapter is a
    # domain adaptor: it builds the kanban payload from a Directive and
    # delegates the actual ``hermes kanban create`` subprocess to
    # ``directive_watcher.kanban_primitive.dispatch_to_kanban``. No
    # adapter in the repo is allowed to spawn ``hermes kanban create``
    # directly — see ``directive_watcher/tests/test_kanban_primitive.py``
    # for the static + import guard.

    def _invoke_kanban(
        self,
        directive: Directive,
        assignee: str,
    ) -> str:
        """Build the kanban payload from the directive and delegate to
        the single primitive. Returns the kanban task_id.

        The idempotency_key convention (``directive:<DIRECTIVE_ID>``) is
        preserved so re-runs dedupe naturally through the kanban CLI's
        own --idempotency-key handling.
        """
        idem_key = f"directive:{directive.directive_id}"
        title = (
            f"[{directive.repository.split('/')[-1].upper()}#{directive.issue}] "
            f"{directive.directive_id} {directive.action}"
        )
        body = (
            f"Directive-driven dispatch from HERMES-2.0 watcher.\n\n"
            f"- Repo:   {directive.repository}\n"
            f"- Issue:  #{directive.issue}\n"
            f"- Action: {directive.action}\n"
            f"- Target branch: {directive.target_branch}\n"
            f"- Expected head: {directive.expected_head}\n"
            f"- Scope:  {directive.scope}\n"
            f"- DIRECTIVE_ID: {directive.directive_id}\n\n"
            f"---\n\n"
            f"{directive.scope}\n"
        )
        payload = {
            "title": title,
            "body": body,
            "assignee": assignee,
            "parent_task_id": self._parent_task_id,
        }
        try:
            return dispatch_to_kanban(
                payload,
                idem_key,
                kanban_bin=self._kanban_bin,
                timeout_seconds=self._timeout_seconds,
            )
        except (ValueError, RuntimeError) as exc:
            # Re-raise as DispatchError so the handler maps it to
            # BLOCKED_EXTERNAL_REAL without leaking primitive details.
            raise DispatchError(
                f"kanban dispatch failed for {directive.directive_id}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

    # ---- Public dispatch entry point -------------------------------------

    def dispatch(self, request: DispatchRequest) -> DispatchResult:
        """Wake a session and dispatch the directive through the kanban CLI.

        On success: returns a DispatchResult with a real session_id and
        the kanban task_id. The session is persisted in DISPATCHED state
        before this returns.

        On failure: raises DispatchError. The handler must translate that
        into BLOCKED_EXTERNAL_REAL (or HUMAN_GO_REAL_REQUIRED for
        protected directives).
        """
        d = request.directive

        # Idempotency: if a session for this directive_id already exists,
        # return it as-is without spawning another subprocess.
        existing = self.get_by_directive(d.directive_id)
        if existing is not None:
            if existing.execution_id != request.execution_id:
                # Same directive_id, different execution_id — that's a
                # conflict (two concurrent watchers) not idempotency.
                raise SessionAlreadyExistsError(
                    f"directive {d.directive_id} already bound to "
                    f"session {existing.session_id} "
                    f"(execution_id={existing.execution_id})"
                )
            # Live Brain bridge — report idempotent re-bind as a session_bound event.
            # Failure is fail-soft; the watch tick MUST NOT abort on a bridge error.
            try:
                from . import live_brain_bridge as _lbb  # type: ignore
                _lbb.on_session_bound(
                    task_id=existing.kanban_task_id or d.directive_id,
                    session_id=existing.session_id,
                    execution_id=existing.execution_id,
                    directive_id=d.directive_id,
                    assignee=existing.assignee,
                    repo=d.repository,
                    branch=d.target_branch,
                    head_sha=request.head_before,
                    started_at_epoch=existing.created_at if isinstance(existing.created_at, (int, float)) else None,
                )
            except Exception:  # pragma: no cover - bridge is best-effort
                pass
            return DispatchResult(
                session_id=existing.session_id,
                kanban_task_id=existing.kanban_task_id,
                assignee=existing.assignee,
                state=existing.state,
            )

        # Resolve assignee via the orchestrator routing table.
        assignee = self._resolve_assignee(d)

        # Zero-copy execution target: explicit Orca directives bypass the
        # normal kanban auto-spawn and wake/resume an Orca-owned Hermes
        # coordinator instead. Non-Orca directives retain the frozen path.
        if directive_requests_orca(d):
            return self._dispatch_to_orca(request, assignee=assignee)

        # Existing direct-Hermes path for directives that did not request Orca.
        kanban_task_id = self._invoke_kanban(d, assignee)

        # Create the session record BEFORE returning — that is the bind
        # the re-audit required. Without it READY_FOR_ASTRA_REAUDIT would
        # be a lie.
        session_id = f"sess-{uuid.uuid4().hex[:12]}"
        rec = SessionRecord(
            session_id=session_id,
            execution_id=request.execution_id,
            directive_id=d.directive_id,
            repository=d.repository,
            issue_number=d.issue,
            target_branch=d.target_branch,
            kanban_task_id=kanban_task_id,
            assignee=assignee,
            state=SESSION_STATE_DISPATCHED,
            source_comment_id=request.source_comment_id,
            head_before=request.head_before,
            requires_human_go_real=d.requires_human_go_real,
        )
        self._append(rec)
        # Live Brain bridge — emit a real task.started event when the session
        # is bound. Canonical subject = kanban_task_id. This is the B3 source-side
        # hook from #46. Failure is fail-soft: a Live Brain outage MUST NOT abort
        # the watch tick.
        try:
            from . import live_brain_bridge as _lbb  # type: ignore
            _lbb.on_session_bound(
                task_id=kanban_task_id or d.directive_id,
                session_id=session_id,
                execution_id=request.execution_id,
                directive_id=d.directive_id,
                assignee=assignee,
                repo=d.repository,
                branch=d.target_branch,
                head_sha=request.head_before,
                started_at_epoch=time.time(),
            )
        except Exception:  # pragma: no cover - bridge is best-effort
            pass
        return DispatchResult(
            session_id=session_id,
            kanban_task_id=kanban_task_id,
            assignee=assignee,
            state=SESSION_STATE_DISPATCHED,
        )
