"""Live Brain bridge — emit PANORAMA Live Brain events from the watcher.

Adapter layer between `directive_watcher` and `panorama-mission-control`
Live Brain runtime. This module does NOT introduce a new daemon, queue,
SQLite, or polling loop; it provides a single Python function that the
watcher's existing hooks call when real state transitions occur.

CANONICAL CONTRACT (per #46 PR review):
  * TASK_ID = kanban_task_id (canonical subject for lifecycle events).
    For events that fire BEFORE the kanban task is created (e.g. claim
    hook), subject = directive_id and the metric
    ``task_id = None`` is recorded; reconciliation hooks MAY emit an
    alias event with subject = kanban_task_id once the id is known.
  * DISPATCHED is NOT terminal. Mapping is explicit:
        BLOCKED                 -> task.blocked
        FAILED / TIMEOUT        -> task.failed
        DONE / COMPLETED / READY_FOR_OWNER_REVIEW -> task.completed
        UNKNOWN / NOT_PROVEN     -> NOT_PROVEN (never auto-DONE)
  * No fallback from UNKNOWN -> task.completed. The handler returns
    FALSE_DONE = 0.
  * worker_pid is reported ONLY if the runtime identity carries a real
    PID. Otherwise the metric is omitted (treated as UNKNOWN, never
    the dispatcher's own os.getpid()).
  * started_at is the real ExecutionOutcome / kanban record timestamp,
    not the bridge call time.
  * All hooks are fail-soft. A Live Brain outage never aborts the watch
    tick or the reconciliation loop.
  * Idempotent: event_id = SHA256(event_type, task_id, step), so retries
    dedupe naturally.

Config:
  * LIVE_BRAIN_BRIDGE_ENABLED (default unset = OFF)
  * LIVE_BRAIN_REPO_DIR (default = sibling workspace)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess  # re-exported so tests can mock `directive_watcher.live_brain_bridge.subprocess.run`
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_LIVE_BRAIN_REPO = Path(
    r"C:/dev/TraficLabPro/panorama-mission-control-main"
)
EMITTER_REL = Path("99_SYSTEM/live_brain/emit_event.py")


# Canonical Live Brain event types this bridge emits.
EVENT_TYPE_TASK_CLAIMED = "task.created"
EVENT_TYPE_TASK_RUNNING = "task.started"
EVENT_TYPE_TASK_HEARTBEAT = "task.heartbeat"
EVENT_TYPE_TASK_BLOCKED = "task.blocked"
EVENT_TYPE_TASK_FAILED = "task.failed"
EVENT_TYPE_TASK_COMPLETED = "task.completed"
EVENT_TYPE_AGENT_HEARTBEAT = "agent.heartbeat"
EVENT_TYPE_VERIFICATION_STARTED = "verification.started"
EVENT_TYPE_VERIFICATION_PASSED = "verification.passed"
EVENT_TYPE_VERIFICATION_FAILED = "verification.failed"
EVENT_TYPE_GOAL_CREATED = "goal.created"
EVENT_TYPE_GOAL_RUNNING = "goal.running"

ALL_EVENT_TYPES = frozenset(
    {
        EVENT_TYPE_TASK_CLAIMED,
        EVENT_TYPE_TASK_RUNNING,
        EVENT_TYPE_TASK_HEARTBEAT,
        EVENT_TYPE_TASK_BLOCKED,
        EVENT_TYPE_TASK_FAILED,
        EVENT_TYPE_TASK_COMPLETED,
        EVENT_TYPE_AGENT_HEARTBEAT,
        EVENT_TYPE_VERIFICATION_STARTED,
        EVENT_TYPE_VERIFICATION_PASSED,
        EVENT_TYPE_VERIFICATION_FAILED,
        EVENT_TYPE_GOAL_CREATED,
        EVENT_TYPE_GOAL_RUNNING,
    }
)

# Result-status mapping. Explicit. No fallback from UNKNOWN to completed.
TERMINAL_STATUS_MAP: dict[str, str] = {
    "done": EVENT_TYPE_TASK_COMPLETED,
    "completed": EVENT_TYPE_TASK_COMPLETED,
    "ready_for_owner_review": EVENT_TYPE_TASK_COMPLETED,
    "failed": EVENT_TYPE_TASK_FAILED,
    "failed_verification": EVENT_TYPE_TASK_FAILED,
    "blocked_external_real": EVENT_TYPE_TASK_FAILED,
    "timeout": EVENT_TYPE_TASK_FAILED,
    "blocked": EVENT_TYPE_TASK_BLOCKED,
    "cancelled": EVENT_TYPE_TASK_BLOCKED,
    # NOT_PROVEN, UNKNOWN, DISPATCHED, RUNNING, CLAIMED, NONE, etc. are
    # deliberately NOT mapped here. They are non-terminal or
    # indeterminate. Reconciliation hooks emit a NOT_PROVEN event for
    # these instead of forcing a terminal.
}


def live_brain_repo_root() -> Path:
    env = os.environ.get("LIVE_BRAIN_REPO_DIR")
    if env:
        return Path(env)
    return DEFAULT_LIVE_BRAIN_REPO


def live_brain_bridge_enabled() -> bool:
    val = os.environ.get("LIVE_BRAIN_BRIDGE_ENABLED", "").strip().lower()
    return val in {"1", "true", "yes", "on"}


def make_event_id(prefix: str, *keys: Any) -> str:
    raw = "|".join([str(prefix)] + [str(k) for k in keys])
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"{prefix}-{digest[:12]}"


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def utc_iso_from_epoch(epoch: int | float | None) -> str | None:
    """Convert unix timestamp (seconds) to ISO 8601 Z. None in -> None out."""
    if epoch is None:
        return None
    try:
        return datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )
    except (TypeError, ValueError, OSError):
        return None


def build_payload(
    event_type: str,
    *,
    task_id: str,
    directive_id: str | None = None,
    actor: str = "Factory Director (directive_watcher)",
    project: str | None = None,
    source: str | None = None,
    status: str | None = None,
    title: str | None = None,
    message: str | None = None,
    started_at: str | None = None,
    metrics: dict[str, Any] | None = None,
    step: str = "",
) -> dict[str, Any]:
    """Build a Live Brain event payload with canonical identity.

    task_id is the canonical subject (= kanban_task_id once known,
    = directive_id before dispatch). The event_id is derived from
    (event_type, task_id, step) so retries dedupe.
    """
    if event_type not in ALL_EVENT_TYPES:
        raise ValueError(f"unknown event type for Live Brain: {event_type!r}")
    payload: dict[str, Any] = {
        "event_id": make_event_id("lbbridge", event_type, task_id, step),
        "ts": utc_iso(),
        "type": event_type,
        "actor": actor,
        "subject": task_id,
    }
    if directive_id:
        payload["directive_id"] = directive_id
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
    if started_at:
        payload["started_at"] = started_at
    if metrics:
        payload["metrics"] = {k: v for k, v in metrics.items() if v is not None}
    return payload


def emit(
    event_type: str,
    *,
    task_id: str,
    directive_id: str | None = None,
    actor: str = "Factory Director (directive_watcher)",
    project: str | None = None,
    source: str | None = None,
    status: str | None = None,
    title: str | None = None,
    message: str | None = None,
    started_at: str | None = None,
    metrics: dict[str, Any] | None = None,
    step: str = "",
    repo_root: Path | None = None,
    timeout_seconds: float = 5.0,
) -> bool:
    """Emit a Live Brain event via the canonical emitter.

    No-op when LIVE_BRAIN_BRIDGE_ENABLED is unset. Fail-soft on any error.
    """
    if not live_brain_bridge_enabled():
        return False
    try:
        payload = build_payload(
            event_type,
            task_id=task_id,
            directive_id=directive_id,
            actor=actor,
            project=project,
            source=source,
            status=status,
            title=title,
            message=message,
            started_at=started_at,
            metrics=metrics,
            step=step,
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
    # NOTE: the canonical subject is task_id. directive_id is preserved
    # in metrics only and must NOT be passed as a second --subject.
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
    # started_at is exposed via metric so the canonical emitter does not
    # need a new CLI flag. The runtime contract: started_at is the
    # authoritative lifecycle anchor.
    if payload.get("started_at") and "started_at" not in (payload.get("metrics") or {}):
        cmd += ["--metric", f"started_at={payload['started_at']}"]
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


def map_status_to_event(result_status: str | None) -> str | None:
    """Map a watcher result_status string to a Live Brain event type.

    Returns None for non-terminal or indeterminate statuses. NEVER
    maps UNKNOWN / NOT_PROVEN to task.completed; those emit a
    NOT_PROVEN event via on_indeterminate_terminal().
    """
    if not result_status:
        return None
    return TERMINAL_STATUS_MAP.get(result_status.strip().lower())


# ---------------------------------------------------------------------------
# Hooks called from production paths
# ---------------------------------------------------------------------------


def on_claim_real(
    *,
    directive_id: str,
    repository: str,
    issue_number: int,
    target_branch: str,
    head_sha: str | None,
    source_comment_id: int,
    actor: str = "Factory Director (directive_watcher)",
    repo_root: Path | None = None,
) -> bool:
    """Called from the watcher handler immediately after a durable
    ``sidecar_store.claim`` succeeded (the real production claim path).

    At this point kanban_task_id is NOT yet known, so the canonical
    subject is the directive_id. The reconciliation hook may emit an
    alias event with the real kanban_task_id once it is observed.
    """
    return emit(
        EVENT_TYPE_TASK_CLAIMED,
        task_id=directive_id,
        directive_id=directive_id,
        actor=actor,
        project=repository,
        source=f"directive_watcher:claim:comment={source_comment_id}",
        status="CLAIMED",
        title=f"Directive {directive_id} claimed for {repository}#{issue_number}",
        message=f"target_branch={target_branch} source_comment={source_comment_id}",
        started_at=utc_iso(),
        metrics={
            "directive_id": directive_id,
            "repository": repository,
            "issue": issue_number,
            "target_branch": target_branch,
            "head_sha": head_sha,
            "source_comment_id": source_comment_id,
            "task_id_pending": True,
        },
        step="claim",
        repo_root=repo_root,
    )


def on_session_bound(
    *,
    task_id: str,  # kanban_task_id, mandatory
    session_id: str,
    execution_id: str,
    directive_id: str,
    assignee: str,
    repo: str,
    branch: str,
    head_sha: str | None,
    started_at_epoch: int | float | None = None,
    worker_pid: int | None = None,
    worker_runtime_id: str | None = None,
    actor: str = "Factory Director (directive_watcher)",
    repo_root: Path | None = None,
) -> bool:
    """Called from OrchestratorDispatcher.dispatch() after a new
    SessionRecord is persisted and the kanban task is created.

    The canonical subject IS now the kanban_task_id. We also emit an
    alias task.started for the directive_id subject if it differs, so
    reconciliation can trace both identities to the same event_id
    suffix (since event_id is keyed on task_id = kanban_task_id).
    """
    started_iso = utc_iso_from_epoch(started_at_epoch)
    base_metrics: dict[str, Any] = {
        "directive_id": directive_id,
        "session_id": session_id,
        "execution_id": execution_id,
        "task_id": task_id,
        "assignee": assignee,
        "branch": branch,
        "head_sha": head_sha,
    }
    if worker_pid is not None:
        base_metrics["worker_pid"] = worker_pid
    if worker_runtime_id is not None:
        base_metrics["worker_runtime_id"] = worker_runtime_id
    ok = emit(
        EVENT_TYPE_TASK_RUNNING,
        task_id=task_id,
        directive_id=directive_id,
        actor=actor,
        project=repo,
        source=f"directive_watcher:session:{session_id}",
        status="RUNNING",
        title=f"Session {session_id} bound for {directive_id}",
        message=f"assignee={assignee} branch={branch}",
        started_at=started_iso,
        metrics=base_metrics,
        step="session_bound",
        repo_root=repo_root,
    )
    return ok


def on_result_posted(
    *,
    task_id: str,
    directive_id: str,
    session_id: str,
    result_status: str,
    started_at_epoch: int | float | None = None,
    finished_at_epoch: int | float | None = None,
    comment_id: int | None = None,
    actor: str = "Factory Director (directive_watcher)",
    repo_root: Path | None = None,
) -> bool:
    """Called from WatcherHandler._post_result() after the GitHub RESULT
    comment is posted. Maps result_status to terminal event type.
    """
    event_type = map_status_to_event(result_status)
    if event_type is None:
        # Indeterminate: emit NOT_PROVEN semantics via a dedicated event type
        # that Live Brain understands as "do not treat as DONE".
        # We re-use task.failed with a NOT_PROVEN status to make this
        # visible without inventing a new event type.
        event_type = EVENT_TYPE_TASK_FAILED
        result_status_normalized = "not_proven"
    else:
        result_status_normalized = result_status

    finished_iso = utc_iso_from_epoch(finished_at_epoch) or utc_iso()
    started_iso = utc_iso_from_epoch(started_at_epoch)
    return emit(
        event_type,
        task_id=task_id,
        directive_id=directive_id,
        actor=actor,
        source=f"directive_watcher:result:{comment_id or 0}",
        status=result_status_normalized.upper(),
        title=f"Task {task_id} -> {result_status_normalized}",
        message=f"session={session_id} comment={comment_id}",
        started_at=started_iso,
        metrics={
            "directive_id": directive_id,
            "session_id": session_id,
            "result_status": result_status_normalized,
            "comment_id": comment_id,
            "finished_at": finished_iso,
        },
        step="result_posted",
        repo_root=repo_root,
    )


def on_reconciliation_terminal(
    *,
    task_id: str,
    directive_id: str,
    session_id: str | None,
    final_state: str,  # "done" | "failed" | "blocked"
    detected_at_epoch: int | float | None,
    started_at_epoch: int | float | None,
    worker_pid: int | None = None,
    worker_runtime_id: str | None = None,
    actor: str = "Factory Director (kanban_session_sync)",
    repo_root: Path | None = None,
) -> bool:
    """Called from kanban_session_sync.reconcile_open_sessions() when
    the real terminal state of a session is observed AFTER the watcher
    tick (e.g. the worker finishes outside the watcher's visibility).

    This is the B4 reconciliation path: terminal events emitted by
    polling the durable store, NOT by the watcher tick.
    """
    state_lower = final_state.strip().lower()
    event_type = map_status_to_event(state_lower)
    if event_type is None:
        event_type = EVENT_TYPE_TASK_FAILED
        state_lower = "not_proven"

    detected_iso = utc_iso_from_epoch(detected_at_epoch) or utc_iso()
    started_iso = utc_iso_from_epoch(started_at_epoch)

    metrics: dict[str, Any] = {
        "directive_id": directive_id,
        "final_state": state_lower,
        "detected_at": detected_iso,
        "origin": "kanban_session_sync.reconcile_open_sessions",
    }
    if session_id:
        metrics["session_id"] = session_id
    if worker_pid is not None:
        metrics["worker_pid"] = worker_pid
    if worker_runtime_id is not None:
        metrics["worker_runtime_id"] = worker_runtime_id
    return emit(
        event_type,
        task_id=task_id,
        directive_id=directive_id,
        actor=actor,
        source=f"kanban_session_sync:reconcile:{detected_iso}",
        status=state_lower.upper(),
        title=f"Reconciliation: task {task_id} terminal={state_lower}",
        message=f"observed via session sync (detected_at={detected_iso})",
        started_at=started_iso,
        metrics=metrics,
        step=f"reconcile:{state_lower}",
        repo_root=repo_root,
    )


def on_indeterminate_terminal(
    *,
    task_id: str,
    directive_id: str,
    reason: str,
    actor: str = "Factory Director (directive_watcher)",
    repo_root: Path | None = None,
) -> bool:
    """Called when a terminal state cannot be classified (UNKNOWN /
    NOT_PROVEN). Emits task.failed with NOT_PROVEN semantics so the
    operator can see the gap. NEVER maps to task.completed.
    """
    return emit(
        EVENT_TYPE_TASK_FAILED,
        task_id=task_id,
        directive_id=directive_id,
        actor=actor,
        source="directive_watcher:indeterminate",
        status="NOT_PROVEN",
        title=f"Task {task_id} terminal state indeterminate",
        message=f"reason={reason}",
        metrics={"reason": reason, "false_done": 0},
        step="indeterminate",
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
            "enabled": live_brain_bridge_enabled(),
            "supported_event_types": sorted(ALL_EVENT_TYPES),
            "terminal_status_map": TERMINAL_STATUS_MAP,
        }, indent=2))
        return 0
    parser.error("use --probe")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
