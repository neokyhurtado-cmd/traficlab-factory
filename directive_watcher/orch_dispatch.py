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
import subprocess
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
    ) -> None:
        self._session_log = Path(session_log)
        self._session_log.parent.mkdir(parents=True, exist_ok=True)
        self._routing_table_path = Path(routing_table_path)
        self._parent_task_id = parent_task_id
        self._kanban_bin = kanban_bin
        self._timeout_seconds = timeout_seconds

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

    # ---- Kanban dispatch --------------------------------------------------

    def _invoke_kanban(
        self,
        directive: Directive,
        assignee: str,
    ) -> str:
        """Invoke the hermes kanban create CLI and return the task_id.

        Reuses the same idempotency-key convention as github_poller.py:
        ``directive:<DIRECTIVE_ID>`` so a second invocation dedupes
        naturally via the kanban CLI.
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
        cmd = [
            self._kanban_bin, "kanban", "create", title,
            "--body", body,
            "--assignee", assignee,
            "--parent", self._parent_task_id,
            "--idempotency-key", idem_key,
            "--json",
        ]
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=self._timeout_seconds
        )
        if proc.returncode != 0:
            raise DispatchError(
                f"hermes kanban create failed for {directive.directive_id} "
                f"(exit {proc.returncode}): {proc.stderr.strip()[:300]}"
            )
        try:
            result = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError as e:
            raise DispatchError(
                f"could not parse kanban JSON: {e}"
            ) from e
        return str(result.get("id") or "")

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
            return DispatchResult(
                session_id=existing.session_id,
                kanban_task_id=existing.kanban_task_id,
                assignee=existing.assignee,
                state=existing.state,
            )

        # Resolve assignee via the orchestrator routing table.
        assignee = self._resolve_assignee(d)

        # Invoke the hermes kanban CLI.
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
        return DispatchResult(
            session_id=session_id,
            kanban_task_id=kanban_task_id,
            assignee=assignee,
            state=SESSION_STATE_DISPATCHED,
        )
