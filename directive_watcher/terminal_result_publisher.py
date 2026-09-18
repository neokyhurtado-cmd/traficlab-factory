"""Async terminal RESULT projection for directive sessions.

The watcher posts HERMES_RESULT=DISPATCHED immediately after a real kanban
bind.  Worker execution is asynchronous, so a later canonical poll must
project the reconciled DONE/FAILED session back to the source GitHub issue.
Without this seam GitHub can remain permanently stuck at DISPATCHED even
though the physical Hermes worker has already finished.

This module is deliberately observation/publication only:
- no task creation or worker spawning;
- no scheduler authority;
- no repo/product mutation;
- GitHub durable truth is used as the restart-safe dedupe key.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from directive_watcher.ack_result import ResultFacts, format_result
from directive_watcher.orch_dispatch import (
    SESSION_STATE_DONE,
    SESSION_STATE_FAILED,
)


_TERMINAL_GITHUB_STATUSES = frozenset({
    "READY_FOR_ASTRA_REAUDIT",
    "BLOCKED_EXTERNAL_REAL",
    "DONE",
    "FAILED",
    "PASS",
})


def _runtime_evidence_for_directive(
    directive_id: str,
    *,
    kanban_db_path: str | Path | None,
) -> dict[str, Any]:
    """Return non-secret physical runtime evidence for one directive task.

    Evidence is derived only from the existing kanban DB. Missing DB/schema is
    a fail-soft empty evidence object; publication remains honest and never
    invents a worker spawn.
    """
    if not kanban_db_path:
        return {}
    try:
        with sqlite3.connect(str(kanban_db_path)) as conn:
            conn.row_factory = sqlite3.Row
            task = conn.execute(
                """
                SELECT id, assignee, status
                FROM tasks
                WHERE idempotency_key = ?
                LIMIT 1
                """,
                (f"directive:{directive_id}",),
            ).fetchone()
            if task is None:
                return {}
            events = conn.execute(
                """
                SELECT kind, payload, created_at
                FROM task_events
                WHERE task_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (task["id"],),
            ).fetchall()
    except (sqlite3.OperationalError, sqlite3.DatabaseError, OSError):
        return {}

    worker_pid: Any = None
    spawned_at: Any = None
    heartbeat_count = 0
    last_heartbeat_at: Any = None
    terminal_kind: str | None = None
    terminal_at: Any = None

    for row in events:
        kind = str(row["kind"])
        try:
            payload = json.loads(row["payload"] or "{}")
        except (TypeError, json.JSONDecodeError):
            payload = {}
        if kind == "spawned":
            if worker_pid is None:
                worker_pid = payload.get("worker_pid")
                spawned_at = row["created_at"]
        elif kind in {"heartbeat", "heartbeats"}:
            heartbeat_count += 1
            last_heartbeat_at = row["created_at"]
        elif kind in {"completed", "failed"}:
            terminal_kind = kind
            terminal_at = row["created_at"]

    return {
        "task_id": str(task["id"]),
        "assignee": str(task["assignee"] or ""),
        "task_status": str(task["status"] or ""),
        "worker_pid": worker_pid,
        "spawned_at": spawned_at,
        "heartbeat_count": heartbeat_count,
        "last_heartbeat_at": last_heartbeat_at,
        "terminal_kind": terminal_kind,
        "terminal_at": terminal_at,
    }


def _already_projected_terminal_result(gh: Any, session: Any) -> bool:
    """Use GitHub itself as the restart-safe dedupe source."""
    try:
        comments = gh.list_recent_comments(session.repository, limit=100)
    except Exception:
        return False

    did = f"DIRECTIVE_ID = {session.directive_id}"
    eid = f"EXECUTION_ID = {session.execution_id}"
    for comment in comments:
        if getattr(comment, "issue_number", None) != session.issue_number:
            continue
        body = getattr(comment, "body", "") or ""
        if "[HERMES_RESULT:v1]" not in body or did not in body or eid not in body:
            continue
        for status in _TERMINAL_GITHUB_STATUSES:
            if f"STATUS = {status}" in body:
                return True
    return False


def publish_terminal_session_results(
    *,
    dispatcher: Any,
    gh: Any,
    kanban_db_path: str | Path | None = None,
    allowed_repos: frozenset[str] | set[str] | None = None,
) -> dict[str, int]:
    """Project reconciled terminal sessions back to their source GitHub issue.

    A successful physical task maps to READY_FOR_ASTRA_REAUDIT; a failed task
    maps to BLOCKED_EXTERNAL_REAL. The first DISPATCHED result remains as
    dispatch evidence; this is the later terminal result for the SAME
    directive/execution lineage.

    Exactly-once across watcher restarts is enforced by scanning durable GitHub
    truth before posting. SINGLE_POLLING_TRUTH prevents concurrent production
    publishers inside one profile, while the GitHub check protects restarts.
    """
    if kanban_db_path is None:
        kanban_db_path = os.environ.get("HERMES_KANBAN_DB")

    stats = {"scanned": 0, "posted": 0, "skipped": 0, "errors": 0}
    for session in dispatcher.list_sessions():
        if session.state not in {SESSION_STATE_DONE, SESSION_STATE_FAILED}:
            continue
        stats["scanned"] += 1
        if allowed_repos is not None and session.repository not in allowed_repos:
            stats["skipped"] += 1
            continue

        if _already_projected_terminal_result(gh, session):
            stats["skipped"] += 1
            continue

        evidence = _runtime_evidence_for_directive(
            session.directive_id,
            kanban_db_path=kanban_db_path,
        )
        spawn_proven = evidence.get("worker_pid") is not None
        parts = [
            f"session_id={session.session_id}",
            f"kanban_task_id={session.kanban_task_id}",
            f"terminal_session_state={session.state}",
            f"WORKER_SPAWN_PROVEN={'YES' if spawn_proven else 'NO'}",
        ]
        if evidence:
            parts.extend([
                f"worker_pid={evidence.get('worker_pid')}",
                f"worker_started_at={evidence.get('spawned_at')}",
                f"heartbeat_count={evidence.get('heartbeat_count', 0)}",
                f"last_heartbeat_at={evidence.get('last_heartbeat_at')}",
                f"assignee={evidence.get('assignee', '')}",
                f"terminal_kind={evidence.get('terminal_kind')}",
                f"terminal_at={evidence.get('terminal_at')}",
            ])
        if session.tests_summary and session.tests_summary != "-":
            parts.append(f"worker_tests={session.tests_summary}")

        status = (
            "READY_FOR_ASTRA_REAUDIT"
            if session.state == SESSION_STATE_DONE
            else "BLOCKED_EXTERNAL_REAL"
        )
        body = format_result(ResultFacts(
            directive_id=session.directive_id,
            execution_id=session.execution_id,
            source_comment_id=session.source_comment_id,
            status=status,
            head_after=session.head_after,
            tests="; ".join(parts),
            evidence=session.evidence_uri or "",
        ))
        try:
            gh.post_comment(session.repository, session.issue_number, body)
        except Exception:
            stats["errors"] += 1
            continue
        stats["posted"] += 1
    return stats
