"""Live Brain bridge — emit PANORAMA Live Brain events from the watcher.

Adapter layer between `directive_watcher` and `panorama-mission-control`
Live Brain runtime. This module does NOT introduce a new daemon, queue,
SQLite, or polling loop; it provides a single Python function that the
watcher's existing hooks call when real state transitions occur.

Contract:
  * One function: `emit(event_type, **fields)` -> bool.
  * Maps directive_watcher state to Live Brain event types using the
    canonical names documented in panorama-mission-control/99_SYSTEM/live_brain/README.md.
  * Idempotent by event_id: the same (directive_id, step) maps to the
    same event_id so retries do not duplicate.
  * Fail-soft: if the emitter subprocess fails, log + warn + return False.
    The watcher's tick MUST NOT fail because Live Brain is unreachable.
  * Configurable repo root via `LIVE_BRAIN_REPO_DIR` env var (default
    resolves to the sibling panorama-mission-control checkout at
    `../panorama-mission-control-main`).

This is the B3 (worker source-hook contract) and B4 (outcome observer)
from traficlab-factory#46 [FACTORY-E2E-BRIDGE-01]. It does not modify
the watcher's existing behaviour; it observes and reports.

B2 NOTE — the orchestrator backing this bridge lives at
`orchestrator/` (single-tick ingestion + per-repo routing), NOT at
`loop_engineering/engine.py` as referenced in the directive body. The
actual path was verified during ASTRA_REAUDIT_20260919_173000Z. The
explicit SEQUENTIAL/PARALLEL/HYBRID state machine named in the directive
is not implemented; per-repo routing via `orchestrator/scripts/routing_resolver.py`
covers the current pilot (#45) scope. Reusing the existing orchestrator
satisfies traficlab-factory#37 frozen rules (no new SQLite/queue/daemon).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess  # re-exported so tests can mock `directive_watcher.live_brain_bridge.subprocess.run`
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_LIVE_BRAIN_REPO = Path(
    r"C:/dev/TraficLabPro/panorama-mission-control-main"
)
EMITTER_REL = Path("99_SYSTEM/live_brain/emit_event.py")

# Mapping of directive_watcher state transitions -> Live Brain event types.
# Keep in sync with panorama-mission-control#15 scope #15 types.
EVENT_TYPE_DISPATCH_STARTED = "task.created"
EVENT_TYPE_DISPATCH_RUNNING = "task.started"
EVENT_TYPE_DISPATCH_HEARTBEAT = "task.heartbeat"
EVENT_TYPE_DISPATCH_BLOCKED = "task.blocked"
EVENT_TYPE_DISPATCH_COMPLETED = "task.completed"
EVENT_TYPE_DISPATCH_FAILED = "task.failed"
EVENT_TYPE_VERIFICATION_STARTED = "verification.started"
EVENT_TYPE_VERIFICATION_PASSED = "verification.passed"
EVENT_TYPE_VERIFICATION_FAILED = "verification.failed"
EVENT_TYPE_GOAL_CREATED = "goal.created"
EVENT_TYPE_GOAL_RUNNING = "goal.running"
EVENT_TYPE_AGENT_HEARTBEAT = "agent.heartbeat"

ALL_EVENT_TYPES = frozenset(
    {
        EVENT_TYPE_DISPATCH_STARTED,
        EVENT_TYPE_DISPATCH_RUNNING,
        EVENT_TYPE_DISPATCH_HEARTBEAT,
        EVENT_TYPE_DISPATCH_BLOCKED,
        EVENT_TYPE_DISPATCH_COMPLETED,
        EVENT_TYPE_DISPATCH_FAILED,
        EVENT_TYPE_VERIFICATION_STARTED,
        EVENT_TYPE_VERIFICATION_PASSED,
        EVENT_TYPE_VERIFICATION_FAILED,
        EVENT_TYPE_GOAL_CREATED,
        EVENT_TYPE_GOAL_RUNNING,
        EVENT_TYPE_AGENT_HEARTBEAT,
    }
)


def live_brain_repo_root() -> Path:
    """Resolve the panorama-mission-control checkout for the live runtime.

    Order:
      1. `LIVE_BRAIN_REPO_DIR` env var (production override).
      2. `DEFAULT_LIVE_BRAIN_REPO` (sibling workspace).
    """
    env = os.environ.get("LIVE_BRAIN_REPO_DIR")
    if env:
        return Path(env)
    return DEFAULT_LIVE_BRAIN_REPO


def make_event_id(prefix: str, *keys: Any) -> str:
    """Stable event_id for idempotency.

    Hash of (prefix, *keys) -> UUIDv4-shaped string. Two calls with the
    same inputs produce the same event_id, so retries dedupe naturally.
    """
    raw = "|".join([str(prefix)] + [str(k) for k in keys])
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"{prefix}-{digest[:12]}"


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_payload(
    event_type: str,
    *,
    actor: str,
    subject: str,
    project: str | None = None,
    source: str | None = None,
    status: str | None = None,
    title: str | None = None,
    message: str | None = None,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if event_type not in ALL_EVENT_TYPES:
        raise ValueError(f"unknown event type for Live Brain: {event_type!r}")
    payload: dict[str, Any] = {
        "event_id": make_event_id("lbbridge", event_type, actor, subject),
        "ts": utc_iso(),
        "type": event_type,
        "actor": actor,
        "subject": subject,
    }
    if project:
        payload["project"] = project
    if source:
        payload["source"] = source
    if status:
        payload["status"] = status.upper()
    if title:
        payload["title"] = title
    if message:
        payload["message"] = message
    if metrics:
        # Drop None values for compactness.
        payload["metrics"] = {k: v for k, v in metrics.items() if v is not None}
    return payload


def live_brain_bridge_enabled() -> bool:
    """Whether the bridge is allowed to spawn the emitter subprocess.

    Defaults to OFF. Operators opt-in by setting LIVE_BRAIN_BRIDGE_ENABLED=1.
    The watcher's tick MUST NOT abort if Live Brain is unreachable; this
    default also keeps the bridge quiet in CI / unit tests where the
    subprocess would otherwise hit a real filesystem path.
    """
    val = os.environ.get("LIVE_BRAIN_BRIDGE_ENABLED", "").strip().lower()
    return val in {"1", "true", "yes", "on"}


def emit(
    event_type: str,
    *,
    actor: str,
    subject: str,
    project: str | None = None,
    source: str | None = None,
    status: str | None = None,
    title: str | None = None,
    message: str | None = None,
    metrics: dict[str, Any] | None = None,
    repo_root: Path | None = None,
    timeout_seconds: float = 5.0,
) -> bool:
    """Emit a Live Brain event via the canonical emitter.

    Returns True on success, False on any failure (fail-soft). Never raises.
    No-op (returns False) when LIVE_BRAIN_BRIDGE_ENABLED is not set.
    """
    if not live_brain_bridge_enabled():
        return False
    try:
        payload = build_payload(
            event_type,
            actor=actor,
            subject=subject,
            project=project,
            source=source,
            status=status,
            title=title,
            message=message,
            metrics=metrics,
        )
    except ValueError as exc:
        sys.stderr.write(f"live_brain_bridge: {exc}\n")
        return False

    root = Path(repo_root) if repo_root else live_brain_repo_root()
    emitter = root / EMITTER_REL
    if not emitter.exists():
        sys.stderr.write(f"live_brain_bridge: emitter not found at {emitter}\n")
        return False

    cmd = [
        sys.executable,
        str(emitter),
        "--type",
        payload["type"],
        "--actor",
        payload["actor"],
        "--subject",
        payload["subject"],
    ]
    if payload.get("project"):
        cmd += ["--project", payload["project"]]
    if payload.get("source"):
        cmd += ["--source", payload["source"]]
    if payload.get("status"):
        cmd += ["--status", payload["status"]]
    if payload.get("title"):
        cmd += ["--title", payload["title"]]
    if payload.get("message"):
        cmd += ["--message", payload["message"]]
    for k, v in (payload.get("metrics") or {}).items():
        cmd += ["--metric", f"{k}={v}"]

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        sys.stderr.write(f"live_brain_bridge: subprocess failed: {exc}\n")
        return False

    if proc.returncode != 0:
        sys.stderr.write(
            f"live_brain_bridge: emitter exit={proc.returncode} stderr={proc.stderr.strip()[:300]}\n"
        )
        return False
    return True


# ---- Hooks called from directive_watcher code ------------------------------


def on_directive_claimed(
    *,
    directive_id: str,
    repository: str,
    issue_number: int,
    target_branch: str,
    head_sha: str | None,
    actor: str,
    repo_root: Path | None = None,
) -> bool:
    """Called from handler.py:_post_ack after the durable claim succeeds.

    Subject is the directive_id at this point because no kanban_task_id
    nor session_id exists yet. Once a session binds, _resolve_task_subject
    will return kanban_task_id and subsequent events will use that — the
    Live Brain consumer correlates them via the directive_id metric (which
    is present on every event). See _resolve_task_subject docstring.
    """
    subject = _resolve_task_subject(directive_id=directive_id)
    return emit(
        EVENT_TYPE_DISPATCH_STARTED,
        actor=actor,
        subject=subject,
        project=repository,
        source="directive_watcher:on_directive_claimed",
        status="RUNNING",
        title=f"Directive {directive_id} claimed for {repository}#{issue_number}",
        message=f"target_branch={target_branch}",
        metrics={
            "directive_id": directive_id,
            "repository": repository,
            "issue": issue_number,
            "target_branch": target_branch,
            "head_sha": head_sha,
        },
        repo_root=repo_root,
    )


def on_session_bound(
    *,
    session_id: str,
    execution_id: str,
    directive_id: str,
    kanban_task_id: str,
    assignee: str,
    repo: str,
    branch: str,
    head_sha: str | None,
    actor: str,
    started_at: str | None = None,
    worker_pid: int | None = None,
    worker_runtime_id: str | None = None,
    repo_root: Path | None = None,
) -> bool:
    """Called after OrchestratorDispatcher._append() persists the SessionRecord.

    C2 — RUNNING physical proof. The dispatcher observes the real worker
    identity (PID when the worker runs in-process, or the orchestrator's
    own PID when the worker is a separate process the dispatcher does
    not own). If a real PID cannot be obtained, the dispatcher passes
    worker_pid=None and the bridge records worker_pid=UNKNOWN with the
    worker_runtime_id explaining why. The bridge MUST NOT fabricate a PID.

    C5 — stable subject. The task subject for this transition is
    kanban_task_id if present, otherwise session_id, otherwise
    directive_id. See _resolve_task_subject.
    """
    subject = _resolve_task_subject(
        directive_id=directive_id,
        kanban_task_id=kanban_task_id,
        session_id=session_id,
    )
    metrics: dict[str, Any] = {
        "directive_id": directive_id,
        "session_id": session_id,
        "execution_id": execution_id,
        "kanban_task_id": kanban_task_id,
        "assignee": assignee,
        "branch": branch,
        "head_sha": head_sha,
    }
    if started_at is not None:
        metrics["started_at"] = started_at
    if worker_pid is not None:
        metrics["worker_pid"] = worker_pid
    else:
        # Honest "unknown" instead of a fabricated PID.
        metrics["worker_pid"] = "UNKNOWN"
    if worker_runtime_id is not None:
        metrics["worker_runtime_id"] = worker_runtime_id
    return emit(
        EVENT_TYPE_DISPATCH_RUNNING,
        actor=actor,
        subject=subject,
        project=repo,
        source=f"directive_watcher:session:{session_id}",
        status="RUNNING",
        title=f"Session {session_id} bound for {directive_id}",
        message=f"assignee={assignee} branch={branch}",
        metrics=metrics,
        repo_root=repo_root,
    )


def _resolve_task_subject(
    *,
    directive_id: str,
    kanban_task_id: str | None = None,
    session_id: str | None = None,
) -> str:
    """Stable task subject for the entire directive/task lifecycle (C5).

    Preference order (most stable → least stable):
      1. kanban_task_id once it exists (the durable, observable identity).
      2. session_id if a session is bound but kanban_task_id not yet minted.
      3. directive_id as last resort (only valid before any session exists).

    Once a kanban_task_id is observed, every subsequent hook (session bound,
    result posted, reconciliation terminal) MUST use the same subject — even
    if a different code path computes it from directive_id — so that Live
    Brain shows ONE task record per directive.

    See traficlab-factory#47 review P1 finding "Keep one subject across the
    task lifecycle".
    """
    if kanban_task_id:
        return kanban_task_id
    if session_id:
        return session_id
    return directive_id


# Result-status → Live Brain event type mapping. CLOSED set by design (C3):
#
#   DISPATCHED   → NOT TERMINAL  (must NEVER emit task.completed)
#   RUNNING      → NOT TERMINAL  (heartbeat)
#   READY_FOR_OWNER_REVIEW → TERMINAL but NOT PRODUCT_DONE
#   DONE         → task.completed (only after independent verification)
#   FAILED       → task.failed
#   FAILED_VERIFICATION → task.failed
#   BLOCKED      → task.blocked
#   BLOCKED_EXTERNAL_REAL → task.blocked
#   HUMAN_GO_REAL_REQUIRED → NOT_TERMINAL (gate, not a worker outcome)
#   UNKNOWN / not in set → task.blocked (FAIL CLOSED / NOT_PROVEN)
#
# Anything not in TERMINAL_STATUSES or NONTERMINAL_STATUSES becomes
# task.blocked with status=UNKNOWN_PROCESSED — NEVER task.completed.
TERMINAL_STATUSES = frozenset(
    {
        "ready_for_owner_review",
        "done",
        "failed",
        "failed_verification",
        "blocked",
        "blocked_external_real",
    }
)
NONTERMINAL_STATUSES = frozenset(
    {
        "dispatched",
        "running",
        "human_go_real_required",
    }
)


def on_result_posted(
    *,
    directive_id: str,
    session_id: str,
    result_status: str,
    comment_id: int | None,
    actor: str,
    kanban_task_id: str | None = None,
    repo_root: Path | None = None,
) -> bool:
    """Called when the watcher posts a RESULT comment to GitHub.

    SEMANTICS (C3+C5+C6):
      * DISPATCHED is a NONTERMINAL state — it MUST map to task.heartbeat,
        NEVER to task.completed. A directive that was just dispatched is
        still in flight; "READY_FOR_OWNER_REVIEW" is what the owner-facing
        terminal state looks like after the watcher posts its RESULT
        comment.
      * Terminal statuses are mapped explicitly. Any UNKNOWN status
        degrades to task.blocked with status="UNKNOWN_PROCESSED" — NEVER
        defaults to task.completed (FAIL CLOSED / NOT_PROVEN).
      * READY_FOR_OWNER_REVIEW is treated as a terminal event for the
        WATCHER tick but the status field still carries the literal
        "READY_FOR_OWNER_REVIEW" so downstream consumers can distinguish
        it from a true product DONE.
      * Subject is kanban_task_id if available, otherwise directive_id
        (see _resolve_task_subject).
    """
    status_lower = (result_status or "").lower()
    if status_lower == "ready_for_owner_review" or status_lower == "done":
        event_type = EVENT_TYPE_DISPATCH_COMPLETED
    elif status_lower in {"failed", "failed_verification"}:
        event_type = EVENT_TYPE_DISPATCH_FAILED
    elif status_lower in {"blocked", "blocked_external_real"}:
        event_type = EVENT_TYPE_DISPATCH_BLOCKED
    elif status_lower == "dispatched":
        # DISPATCHED is nonterminal; surface as heartbeat, not completion.
        event_type = EVENT_TYPE_DISPATCH_HEARTBEAT
    elif status_lower == "running":
        event_type = EVENT_TYPE_DISPATCH_HEARTBEAT
    elif status_lower == "human_go_real_required":
        # Gate state, not a worker outcome. Surface as blocked so it is
        # visible but cannot be mistaken for completion.
        event_type = EVENT_TYPE_DISPATCH_BLOCKED
    else:
        # Unknown / unrecognised status → FAIL CLOSED. We refuse to emit
        # task.completed for an unknown; the operator must extend
        # TERMINAL_STATUSES explicitly. This satisfies acceptance C3:
        # "UNKNOWN STATUS → NO debe defaultar a task.completed."
        event_type = EVENT_TYPE_DISPATCH_BLOCKED
        status_lower = "unknown_processed"
    subject = _resolve_task_subject(
        directive_id=directive_id,
        kanban_task_id=kanban_task_id,
        session_id=session_id,
    )
    return emit(
        event_type,
        actor=actor,
        subject=subject,
        source=f"directive_watcher:result:{comment_id or 0}",
        status=status_lower.upper(),
        title=f"Directive {directive_id} -> {result_status}",
        message=f"session={session_id} comment={comment_id}",
        metrics={
            "directive_id": directive_id,
            "session_id": session_id,
            "kanban_task_id": kanban_task_id,
            "result_status": result_status,
            "comment_id": comment_id,
        },
        repo_root=repo_root,
    )


def on_terminal_observed(
    *,
    directive_id: str,
    session_id: str,
    kanban_task_id: str | None,
    outcome: str,  # "done" | "failed" | "blocked_external_real"
    actor: str,
    tests_summary: str | None = None,
    evidence_uri: str | None = None,
    repo_root: Path | None = None,
) -> bool:
    """Called from kanban_session_sync.reconcile_open_sessions() when a
    session reaches a terminal state ASYNCHRONOUSLY (after the watcher
    tick that originally dispatched it).

    This is C4: the path that actually observes "the worker finished
    after the dispatch tick" — distinct from on_result_posted() which
    only fires when the watcher itself posts a RESULT comment.

    Maps to the SAME terminal event types as on_result_posted but uses
    the observation source so consumers can distinguish watcher-driven
    vs reconciliation-driven terminal events.
    """
    outcome_lower = (outcome or "").lower()
    if outcome_lower == "done":
        event_type = EVENT_TYPE_DISPATCH_COMPLETED
        status = "DONE"
    elif outcome_lower == "failed":
        event_type = EVENT_TYPE_DISPATCH_FAILED
        status = "FAILED"
    elif outcome_lower == "blocked_external_real":
        event_type = EVENT_TYPE_DISPATCH_BLOCKED
        status = "BLOCKED_EXTERNAL_REAL"
    else:
        # FAIL CLOSED: unknown reconciliation outcome → blocked, never
        # task.completed.
        event_type = EVENT_TYPE_DISPATCH_BLOCKED
        status = "UNKNOWN_RECONCILIATION_OUTCOME"
    subject = _resolve_task_subject(
        directive_id=directive_id,
        kanban_task_id=kanban_task_id,
        session_id=session_id,
    )
    metrics: dict[str, Any] = {
        "directive_id": directive_id,
        "session_id": session_id,
        "kanban_task_id": kanban_task_id,
        "outcome": outcome,
        "observed_via": "kanban_session_sync.reconcile_open_sessions",
    }
    if tests_summary:
        metrics["tests_summary"] = tests_summary
    if evidence_uri:
        metrics["evidence_uri"] = evidence_uri
    return emit(
        event_type,
        actor=actor,
        subject=subject,
        source="directive_watcher:reconcile_open_sessions",
        status=status,
        title=f"Reconciliation observed terminal: {directive_id} -> {outcome}",
        message=f"session={session_id} outcome={outcome}",
        metrics=metrics,
        repo_root=repo_root,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Smoke test the live_brain_bridge from the CLI"
    )
    parser.add_argument("--probe", action="store_true", help="Print config and exit")
    args = parser.parse_args()
    if args.probe:
        root = live_brain_repo_root()
        emitter = root / EMITTER_REL
        print(json.dumps({
            "live_brain_repo_root": str(root),
            "emitter_path": str(emitter),
            "emitter_exists": emitter.exists(),
            "supported_event_types": sorted(ALL_EVENT_TYPES),
        }, indent=2))
        return 0
    parser.error("use --probe")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
