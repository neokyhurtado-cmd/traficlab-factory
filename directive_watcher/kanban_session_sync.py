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

This module closes the gap by reading the latest terminal
``task_events`` row for the directive's kanban task and writing the
matching state onto the ``SessionRecord`` through the dispatcher's
``update_session()`` seam.

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
    session all return ``False`` rather than raising — the watcher tick
    must never crash because the observation layer is down.
  - **Single-write per transition.** We only call
    ``dispatcher.update_session`` when we actually have a transition to
    record; otherwise the function returns ``False`` and leaves the
    in-memory + on-disk record untouched.

Wire-up
-------
The handler calls this function once per dispatch via
``sync_session_from_kanban_event``, only when ``HERMES_KANBAN_DB`` is
set (opt-in: installations without a kanban DB are not broken).
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Optional

from directive_watcher.orch_dispatch import (
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
    """Find the latest terminal task_event for the given directive.

    Joins ``tasks.idempotency_key = 'directive:<id>'`` against
    ``task_events`` and returns the row with the highest ``created_at``
    whose kind is in ``KIND_TO_STATE`` or is ``spawned`` (with a
    ``worker_pid`` payload). Returns ``None`` when no row matches.

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
    """Advance the SessionRecord to match the kanban task's latest event.

    Returns ``True`` when the session was mutated, ``False`` when there
    was nothing to do (unknown session, no event, event already
    reflected on the session, or non-terminal event).

    Opt-in: when either ``kanban_db_path`` or the resolved
    ``session_log`` is missing/empty the function returns ``False``
    immediately. Installations without a kanban DB or JSONL sidecar are
    not affected.

    Mapping:

      - ``completed`` payload  → ``state=DONE``, with ``tests_summary``
        and ``evidence_uri`` taken from the payload when present.
      - ``failed``    payload  → ``state=FAILED``, with ``evidence_uri``
        taken from the payload when present.
      - ``spawned`` (with worker_pid) → ``state=RUNNING``.
      - Anything else (heartbeat, commented, …) → no-op.

    Idempotency: if the session is already in the target state, ``False``
    is returned and the sidecar is not rewritten.
    """
    # Resolve opt-in knobs FIRST so the directive lookup uses the same
    # path the sync will write to.
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
    return True
