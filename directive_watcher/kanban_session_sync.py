"""Kanban → sessions.jsonl sync seam (AUTONOMY-V2, 2026-09-13).

Why this module exists
----------------------
The orchestrator dispatcher (``directive_watcher/orch_dispatch.py``) mints
a ``SessionRecord`` with ``state=DISPATCHED`` and persists it to the
JSONL sidecar BEFORE returning. Until now nothing advanced the state
when the downstream kanban task progressed — the record stayed stuck at
``DISPATCHED`` forever even when the task had ``outcome=completed``
on the board. The Astra session-of-truth review (ref #27) flagged this
as the kanban/observation gap.

This module closes the gap by reading the latest kanban ``task_events`` row
for a directive and writing the matching state onto its ``SessionRecord``
through the dispatcher's ``update_session()`` seam.

There are two observation paths:

1. ``sync_session_from_kanban_event`` — immediate post-dispatch observation.
2. ``reconcile_open_sessions`` — periodic reconciliation for sessions whose
   kanban work finishes *after* the dispatch tick. This second path is the
   critical async contract: a later tick must advance DISPATCHED/RUNNING to
   DONE/FAILED without requiring a new GitHub comment or directive.

Design constraints (all enforced by tests)
------------------------------------------
  - **No hermes_cli.kanban_db import.** We query the kanban DB via
    stdlib ``sqlite3`` and reproduce only the minimal schema we need
    (``tasks.idempotency_key`` + ``task_events.kind/payload/created_at``).
    This keeps the directive_watcher package hermetic — it can run in a
    test env without the hermes CLI on ``sys.path``.
  - **Idempotent.** Running sync twice with the same kanban event is a
    no-op the second time (no dup evidence, no bad writes).
  - **Fail-soft.** Missing DB, missing table, missing task, or missing
    session all return a no-op rather than raising — the watcher tick
    must never crash because the observation layer is down.
  - **Single-write per transition.** We only call
    ``dispatcher.update_session`` when we actually have a transition to
    record; otherwise the function returns ``False`` and leaves the
    in-memory + on-disk record untouched.
  - **No terminal regression.** Periodic reconciliation skips DONE, FAILED
    and BLOCKED sessions; a stale kanban event cannot move them backwards.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Optional

from directive_watcher.orch_dispatch import (
    SESSION_STATE_BLOCKED,
    SESSION_STATE_DONE,
    SESSION_STATE_FAILED,
    SESSION_STATE_RUNNING,
    OrchestratorDispatcher,
)


# Environment knobs that gate the sync. Setting both is the opt-in
# signal — installations without a kanban DB or without a JSONL sidecar
# keep working unchanged.
ENV_KANBAN_DB = "HERMES_KANBAN_DB"
ENV_SESSION_LOG = "HERMES_SESSION_LOG"

# States that periodic observation must never regress. WAITING_REVIEW remains
# reconcilable because a downstream kanban task may legitimately finish while
# the session is waiting for review/evidence publication.
TERMINAL_SESSION_STATES = frozenset({
    SESSION_STATE_DONE,
    SESSION_STATE_FAILED,
    SESSION_STATE_BLOCKED,
})


def _resolve_session_log(session_log: str | Path | None) -> Optional[Path]:
    """Resolve the session_log path from arg or env.

    Order: explicit arg → ``HERMES_SESSION_LOG`` env → ``None`` (caller
    will skip the sync). Returning ``None`` is the opt-out signal.
    """
    if session_log is not None:
        return Path(session_log)
    env = os.environ.get(ENV_SESSION_LOG)
    if env:
        return Path(env)
    return None


# Terminal event kinds we map to session state. Anything else
# (e.g. ``spawned`` with no worker_pid, ``heartbeat``, ``commented``)
# is ignored — it doesn't carry enough signal to mutate the session.
KIND_TO_STATE: dict[str, str] = {
    "completed": SESSION_STATE_DONE,
    "failed": SESSION_STATE_FAILED,
}


def _find_directive_id_for_session(
    session_id: str,
    *,
    session_log: str | Path,
) -> Optional[str]:
    """Look up the directive_id bound to a given session_id.

    We scan the JSONL sidecar directly so this helper has no
    dependency on the dispatcher's in-memory mirror (it works even
    when the watcher is in a fresh process mid-tick). Returns ``None``
    if the session is unknown.
    """
    p = Path(session_log)
    if not p.exists():
        return None
    needle = f'"session_id": "{session_id}"'
    try:
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                if needle not in line:
                    continue
                try:
                    blob = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if blob.get("session_id") == session_id:
                    return blob.get("directive_id")
    except OSError:
        return None
    return None


def _find_kanban_event_for_directive(
    directive_id: str,
    *,
    kanban_db_path: str | Path,
) -> Optional[dict[str, Any]]:
    """Find the latest meaningful task_event for the given directive.

    Joins ``tasks.idempotency_key = 'directive:<id>'`` against
    ``task_events`` and returns the row with the highest ``created_at``
    whose kind is completed/failed/spawned. ``spawned`` only mutates a
    session when its payload has ``worker_pid``; that validation happens
    in ``sync_session_from_kanban_event``.

    The function never raises; missing DB / table / task → ``None``.
    """
    try:
        with sqlite3.connect(str(kanban_db_path)) as conn:
            cur = conn.cursor()
            # Probe schema — if either table is missing we're done.
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('tasks', 'task_events')"
            )
            present = {row[0] for row in cur.fetchall()}
            if present != {"tasks", "task_events"}:
                return None

            idem = f"directive:{directive_id}"
            cur.execute(
                """
                SELECT e.kind, e.payload, e.created_at
                FROM task_events e
                JOIN tasks t ON t.id = e.task_id
                WHERE t.idempotency_key = ?
                  AND (
                    e.kind IN ('completed', 'failed')
                    OR (e.kind = 'spawned')
                  )
                ORDER BY e.created_at DESC
                LIMIT 1
                """,
                (idem,),
            )
            row = cur.fetchone()
    except (sqlite3.OperationalError, sqlite3.DatabaseError, OSError):
        return None
    if row is None:
        return None
    kind, payload_blob, created_at = row
    payload: dict[str, Any] = {}
    if payload_blob:
        try:
            payload = json.loads(payload_blob)
        except (TypeError, json.JSONDecodeError):
            payload = {}
    return {"kind": kind, "payload": payload, "created_at": int(created_at)}


def sync_session_from_kanban_event(
    session_id: str,
    *,
    kanban_db_path: str | Path | None = None,
    session_log: str | Path | None = None,
    dispatcher: OrchestratorDispatcher,
) -> bool:
    """Advance one SessionRecord to match the kanban task's latest event.

    Returns ``True`` when the session was mutated, ``False`` when there
    was nothing to do (unknown session, no event, event already reflected
    on the session, non-meaningful event, or observation not configured).

    Opt-in: when either ``kanban_db_path`` or the resolved ``session_log``
    is missing/empty the function returns ``False`` immediately.

    Mapping:

      - ``completed`` payload  → ``state=DONE``, with ``tests_summary``
        and ``evidence_uri`` taken from the payload when present.
      - ``failed`` payload     → ``state=FAILED``, with ``evidence_uri``
        taken from the payload when present.
      - ``spawned`` (with worker_pid) → ``state=RUNNING``.
      - Anything else → no-op.
    """
    if kanban_db_path is None:
        kanban_db_path = os.environ.get(ENV_KANBAN_DB)
    if not kanban_db_path:
        return False
    resolved_session_log = _resolve_session_log(session_log)
    if resolved_session_log is None:
        return False

    directive_id = _find_directive_id_for_session(
        session_id, session_log=resolved_session_log,
    )
    if directive_id is None:
        return False

    current = dispatcher.get_session(session_id)
    if current is None:
        return False

    event = _find_kanban_event_for_directive(
        directive_id, kanban_db_path=kanban_db_path,
    )
    if event is None:
        return False

    kind = event["kind"]
    payload = event["payload"] or {}

    if kind == "completed":
        target = SESSION_STATE_DONE
        tests_summary = payload.get("tests_summary")
        evidence_uri = payload.get("evidence_uri")
    elif kind == "failed":
        target = SESSION_STATE_FAILED
        tests_summary = None
        evidence_uri = payload.get("evidence_uri")
    elif kind == "spawned" and payload.get("worker_pid") is not None:
        target = SESSION_STATE_RUNNING
        tests_summary = None
        evidence_uri = None
    else:
        return False

    # Idempotency: don't rewrite the log when we're already in the target
    # state. We still return False so the caller knows nothing happened.
    if current.state == target:
        return False

    kwargs: dict[str, Any] = {"state": target}
    if tests_summary is not None:
        kwargs["tests_summary"] = tests_summary
    if evidence_uri is not None:
        kwargs["evidence_uri"] = evidence_uri
    dispatcher.update_session(session_id, **kwargs)
    # Live Brain bridge (B4 reconciliation path) — when a session
    # transitions to a terminal state (DONE / FAILED) OR to RUNNING
    # via reconciliation, emit a real event so the owner sees the
    # async outcome. The watcher tick that originally claimed the
    # directive did NOT see this transition because the worker finished
    # outside the tick's visibility. Fail-soft.
    try:
        from . import live_brain_bridge as _lbb  # type: ignore
        _lbb.on_reconciliation_terminal(
            task_id=current.kanban_task_id or directive_id,
            directive_id=directive_id,
            session_id=session_id,
            final_state=target,
            detected_at_epoch=event.get("created_at"),
            started_at_epoch=current.created_at if isinstance(current.created_at, (int, float)) else None,
            worker_pid=payload.get("worker_pid") if isinstance(payload, dict) else None,
            worker_runtime_id=None,  # kanban events don't carry a runtime_id
        )
    except Exception:  # pragma: no cover - bridge is best-effort
        pass
    return True


def reconcile_open_sessions(
    *,
    dispatcher: OrchestratorDispatcher,
    kanban_db_path: str | Path | None = None,
    session_log: str | Path | None = None,
) -> dict[str, int]:
    """Reconcile every non-terminal session against current kanban state.

    This function is intended to run once on *every* watcher/orchestrator
    tick, even when there are zero new GitHub comments. That makes state
    observation asynchronous: dispatch can happen on tick N, the worker can
    finish later, and tick N+1 advances the existing session to DONE/FAILED.

    The observer is deliberately fail-soft. One malformed/missing task does
    not prevent other sessions from being inspected, and observation failure
    never breaks execution. The returned counters are evidence/telemetry only.
    """
    if kanban_db_path is None:
        kanban_db_path = os.environ.get(ENV_KANBAN_DB)
    resolved_session_log = _resolve_session_log(session_log)
    if not kanban_db_path or resolved_session_log is None:
        return {"scanned": 0, "updated": 0, "errors": 0}

    scanned = 0
    updated = 0
    errors = 0
    for session in dispatcher.list_sessions():
        if session.state in TERMINAL_SESSION_STATES:
            continue
        scanned += 1
        try:
            if sync_session_from_kanban_event(
                session.session_id,
                kanban_db_path=kanban_db_path,
                session_log=resolved_session_log,
                dispatcher=dispatcher,
            ):
                updated += 1
        except Exception:  # noqa: BLE001 — observer must remain fail-soft
            errors += 1
    return {"scanned": scanned, "updated": updated, "errors": errors}
