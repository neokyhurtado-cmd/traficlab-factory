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

This is the B3 worker source-hook contract from
traficlab-factory#46 [FACTORY-E2E-BRIDGE-01]. It does not modify the
watcher's existing behaviour; it observes and reports.
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
    """Called when a directive has passed allowlist + parser + dispatch started."""
    return emit(
        EVENT_TYPE_DISPATCH_STARTED,
        actor=actor,
        subject=directive_id,
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
    repo_root: Path | None = None,
) -> bool:
    """Called after OrchestratorDispatcher._append() persists the SessionRecord."""
    return emit(
        EVENT_TYPE_DISPATCH_RUNNING,
        actor=actor,
        subject=kanban_task_id or directive_id,
        project=repo,
        source=f"directive_watcher:session:{session_id}",
        status="RUNNING",
        title=f"Session {session_id} bound for {directive_id}",
        message=f"assignee={assignee} branch={branch}",
        metrics={
            "directive_id": directive_id,
            "session_id": session_id,
            "execution_id": execution_id,
            "kanban_task_id": kanban_task_id,
            "assignee": assignee,
            "branch": branch,
            "head_sha": head_sha,
        },
        repo_root=repo_root,
    )


def on_result_posted(
    *,
    directive_id: str,
    session_id: str,
    result_status: str,
    comment_id: int | None,
    actor: str,
    repo_root: Path | None = None,
) -> bool:
    """Called when the watcher posts a RESULT comment to GitHub.

    Maps to task.completed / task.failed / task.blocked per result_status.
    """
    status_lower = result_status.lower()
    if status_lower in {"ready_for_owner_review", "done"}:
        event_type = EVENT_TYPE_DISPATCH_COMPLETED
    elif status_lower in {"failed", "blocked_external_real", "failed_verification"}:
        event_type = EVENT_TYPE_DISPATCH_FAILED
    elif status_lower == "blocked":
        event_type = EVENT_TYPE_DISPATCH_BLOCKED
    else:
        event_type = EVENT_TYPE_DISPATCH_COMPLETED
    return emit(
        event_type,
        actor=actor,
        subject=directive_id,
        source=f"directive_watcher:result:{comment_id or 0}",
        status=result_status.upper(),
        title=f"Directive {directive_id} -> {result_status}",
        message=f"session={session_id} comment={comment_id}",
        metrics={
            "directive_id": directive_id,
            "session_id": session_id,
            "result_status": result_status,
            "comment_id": comment_id,
        },
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
