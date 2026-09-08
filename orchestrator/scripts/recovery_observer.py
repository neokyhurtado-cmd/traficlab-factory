#!/usr/bin/env python3
"""
recovery_observer.py — RECOVERY_REQUIRED observer (cron-driven, no_agent).

WHY THIS LIVES IN THE ORCHESTRATOR PROFILE
------------------------------------------
Per ORCH-V1 §Roles, only the orchestrator profile owns control-plane code
under ~/.hermes/profiles/orchestrator/**. The RECOVERY_REQUIRED signal is a
panel-side concern (it tells the operator "this task needs eyes, not just a
re-claim"), so the observer that emits it must live here.

WHAT THIS MODULE DOES
---------------------
Walks the kanban DB on every cron tick, finds tasks whose heartbeat/claim
shows them as stuck beyond ``recovery_required_event_after_seconds`` (default
1800s), and for each:

  1. Marks the task ``blocked`` with a structured reason whose prefix
     ``RECOVERY_REQUIRED:`` is the panel-side discriminator (per
     AUTO_DISPATCH_CONTRACT §3). The DB ``block_kind`` column is left NULL
     because RECOVERY_REQUIRED is not in VALID_BLOCK_KINDS — the prefix on
     ``reason`` is canonical.
  2. Appends a human-readable comment so the panel surfaces the cause.
  3. Emits a ``RECOVERY_REQUIRED`` event row with the §5 payload shape:
     ``{task_id, last_seen=<iso8601>, owner=<profile>}``.

The three writes are idempotent at the per-tick level: a 60m event-based
short-circuit prevents comment flooding when the same task gets
reclaim-and-recovered in a tight loop (Locked Decision 5).

The actual dispatcher reclaim path is NOT touched (Locked Decision 6 /
FORBIDDEN list). detect_stale_running / release_stale_claims continue to
reclaim stale claims to ``ready``; this observer only marks the task for
human review.

STDOUT CONTRACT (no_agent cron job)
-----------------------------------
- One ``recovery_required <task_id>`` line per RECOVERY_REQUIRED emitted.
- Empty stdout if nothing to emit (silent cron tick).
- Errors -> stderr (visible in cron log, never blocks the cron schedule).

FAILURE MODE
------------
Any exception escaping ``_emit_for_task`` is logged and the loop moves on
to the next task so one bad row doesn't strand the rest. We exit 0 even on
partial failures; the next tick will retry whatever transient error hit.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any, Iterable, Optional


# --- Constants tied to AUTO_DISPATCH_CONTRACT -------------------------------
# Locked Decisions 1 + 3 + 5: these are NOT to be re-derived by future
# workers. If the contract moves, the new values land here in one place.

#: Prefix on ``reason`` that the panel uses to render RECOVERY_REQUIRED
#: distinctly from generic BLOCKED. Per AUTO_DISPATCH_CONTRACT §3.
RECOVERY_REASON_PREFIX = "RECOVERY_REQUIRED:"

#: ISO-8601 UTC timestamp of the moment this observer decided the task was
#: stuck. Embedded in both the structured reason and the event payload.
#: Computed per emit (see ``_format_reason`` / ``_format_event_payload``).

#: Idempotency window — skip a task if a RECOVERY_REQUIRED event was emitted
#: for it within the last N seconds. Per Locked Decision 5.
IDEMPOTENCY_WINDOW_SECONDS = 60 * 60  # 60m

#: Default threshold for "this task has been stale too long". Overridden by
#: ``kanban.auto_dispatch.recovery_required_event_after_seconds`` when that
#: config key is present. Per AUTO_DISPATCH_CONTRACT §6.
DEFAULT_RECOVERY_AFTER_SECONDS = 1800  # 30m


def log(msg: str) -> None:
    """Log to stderr so it lands in the cron log without polluting stdout
    (stdout is reserved for ``recovery_required <id>`` delivery lines)."""
    print(msg, file=sys.stderr, flush=True)


# --- Config ----------------------------------------------------------------

def _read_recovery_after_seconds() -> int:
    """Read ``kanban.auto_dispatch.recovery_required_event_after_seconds``
    from the active config, falling back to :data:`DEFAULT_RECOVERY_AFTER_SECONDS`.

    Defensive: any error (missing config, malformed YAML, missing key)
    degrades to the default. We never crash a cron tick on a config glitch.
    """
    try:
        import yaml  # noqa: WPS433 - lazy import to keep startup cheap
    except ImportError:
        return DEFAULT_RECOVERY_AFTER_SECONDS

    hermes_home = os.environ.get("HERMES_HOME") or os.path.expanduser(
        os.path.join("~", ".hermes")
    )
    config_path = os.path.join(hermes_home, "config.yaml")
    if not os.path.exists(config_path):
        return DEFAULT_RECOVERY_AFTER_SECONDS
    try:
        with open(config_path, "r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError) as exc:
        log(f"warn: could not read {config_path}: {exc}; using default")
        return DEFAULT_RECOVERY_AFTER_SECONDS

    try:
        value = int(
            cfg["kanban"]["auto_dispatch"]["recovery_required_event_after_seconds"]
        )
    except (KeyError, TypeError, ValueError):
        return DEFAULT_RECOVERY_AFTER_SECONDS
    if value <= 0:
        return DEFAULT_RECOVERY_AFTER_SECONDS
    return value


# --- DB helpers ------------------------------------------------------------
# Imported lazily so the module is importable (for tests) without hermes_cli
# having to be on sys.path in unusual envs — same pattern as
# eligibility_hook.py.

def _db():
    """Lazy importer for hermes_cli.kanban_db. Raises RuntimeError when
    hermes_cli is missing, which the caller treats as a per-task error
    (logged, not fatal)."""
    try:
        from hermes_cli import kanban_db
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(f"hermes_cli.kanban_db not importable: {exc}") from exc
    return kanban_db


def _find_stale_tasks(window_seconds: int) -> list[dict[str, Any]]:
    """Return the rows that are candidates for RECOVERY_REQUIRED.

    Per Locked Decision 3, the query mirrors what the spec dictates:

        SELECT task_id, assignee, claim_lock, claim_expires, started_at,
               worker_pid, last_heartbeat_at
        FROM tasks
        WHERE status = 'ready'
          AND claim_expires IS NOT NULL
          AND claim_expires < now() - <window>

    The spec's SQL is the contract; even though the current reclaim path
    clears ``claim_expires`` on transition ``running -> ready`` (so this
    query is naturally empty in steady state), we honour it verbatim so a
    future reclaim variant that leaves ``claim_expires`` populated — or the
    manual test path that AC-4 explicitly describes (set claim_expires in
    the past on a scratch task) — lights up correctly.

    Defensive: ``last_heartbeat_at`` is also surfaced so the event payload
    can carry an accurate ``last_seen``. We do NOT require it to be set —
    a claim with no heartbeat is the canonical "stuck" signal.
    """
    kb = _db()
    cutoff = int(time.time()) - window_seconds
    with kb.connect_closing() as conn:
        rows = conn.execute(
            """
            SELECT id, assignee, claim_lock, claim_expires, started_at,
                   worker_pid, last_heartbeat_at
              FROM tasks
             WHERE status = 'ready'
               AND claim_expires IS NOT NULL
               AND claim_expires < ?
            """,
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]


def _already_recovered_recently(task_id: str, window_seconds: int) -> bool:
    """Idempotency check per Locked Decision 5.

    True iff a ``RECOVERY_REQUIRED`` event was emitted for ``task_id``
    within the last ``window_seconds``. Prevents comment flooding when a
    task gets reclaim-and-recovered in a tight loop.
    """
    kb = _db()
    cutoff = int(time.time()) - window_seconds
    with kb.connect_closing() as conn:
        row = conn.execute(
            "SELECT MAX(created_at) AS last_at FROM task_events "
            "WHERE task_id = ? AND kind = 'RECOVERY_REQUIRED'",
            (task_id,),
        ).fetchone()
    if row is None or row["last_at"] is None:
        return False
    return int(row["last_at"]) >= cutoff


def _format_reason(task: dict[str, Any], now_epoch: int) -> str:
    """Build the structured reason string for ``block_task``.

    Format per Locked Decision 1:
        RECOVERY_REQUIRED: last_heartbeat=<iso8601> owner=<profile> worker_pid=<pid> lost_since=<seconds>

    ``last_heartbeat`` is the task's last_heartbeat_at (or "" if never
    recorded — that's a legitimate "stuck from the start" signal).
    ``lost_since`` is the elapsed seconds since the claim expired
    (claim_expires is in the past, so this is always >= 0).
    """
    last_hb = task.get("last_heartbeat_at")
    if last_hb:
        last_hb_iso = (
            datetime.fromtimestamp(int(last_hb), tz=timezone.utc).isoformat(
                timespec="seconds"
            )
        )
    else:
        last_hb_iso = ""
    claim_expires = int(task.get("claim_expires") or now_epoch)
    lost_since = max(0, now_epoch - claim_expires)
    owner = task.get("assignee") or "<unknown>"
    worker_pid = task.get("worker_pid") or ""
    return (
        f"{RECOVERY_REASON_PREFIX} "
        f"last_heartbeat={last_hb_iso} "
        f"owner={owner} "
        f"worker_pid={worker_pid} "
        f"lost_since={lost_since}"
    )


def _format_event_payload(
    task: dict[str, Any], now_epoch: int
) -> dict[str, Any]:
    """Build the §5 event payload: {task_id, last_seen, owner}."""
    last_hb = task.get("last_heartbeat_at")
    if last_hb:
        last_seen_iso = (
            datetime.fromtimestamp(int(last_hb), tz=timezone.utc).isoformat(
                timespec="seconds"
            )
        )
    else:
        last_seen_iso = ""
    return {
        "task_id": task["id"],
        "last_seen": last_seen_iso,
        "owner": task.get("assignee") or "",
    }


def _block_with_reason(task_id: str, reason: str) -> bool:
    """Mark ``task_id`` blocked with the structured ``reason`` (kind=NULL).

    Returns True iff the transition succeeded. We tolerate
    "task not in a blockable state" as a non-error (another writer already
    acted on it): the event emission is the durable signal regardless.
    """
    kb = _db()
    with kb.connect_closing() as conn:
        return kb.block_task(conn, task_id, reason=reason, kind=None)


def _add_comment(task_id: str, body: str) -> None:
    """Append a human-readable comment row.

    Best-effort: a comment-write failure is logged but does not abort the
    RECOVERY_REQUIRED emission (the structured ``reason`` already records
    the cause on the task itself).
    """
    kb = _db()
    author = os.environ.get("HERMES_ACTOR_PROFILE") or "recovery_observer"
    with kb.connect_closing() as conn:
        kb.add_comment(conn, task_id, author, body)


def _emit_event(task_id: str, payload: dict[str, Any]) -> None:
    """Append a RECOVERY_REQUIRED row to ``task_events``.

    Uses ``kanban_db._append_event`` — the same primitive every internal
    caller uses to write event rows. We can't reach for a public ``event()``
    helper because none is exported (verified against the live
    ``hermes_cli.kanban_db`` namespace).
    """
    kb = _db()
    with kb.connect_closing() as conn:
        with kb.write_txn(conn):
            kb._append_event(
                conn,
                task_id,
                "RECOVERY_REQUIRED",
                payload,
            )


# --- Per-task driver --------------------------------------------------------

def _emit_for_task(
    task: dict[str, Any],
    *,
    idempotency_window: int = IDEMPOTENCY_WINDOW_SECONDS,
) -> Optional[str]:
    """Drive the three-step RECOVERY_REQUIRED emission for one task.

    Returns the ``task_id`` iff emission happened (so the caller can print
    ``recovery_required <id>``), else None.
    """
    task_id = task["id"]

    # Idempotency short-circuit (Locked Decision 5): skip silently when a
    # RECOVERY_REQUIRED event already exists within the window.
    if _already_recovered_recently(task_id, idempotency_window):
        return None

    now_epoch = int(time.time())
    reason = _format_reason(task, now_epoch)
    payload = _format_event_payload(task, now_epoch)

    # Step 1: structured block. We don't fail the whole emission if the
    # block transition is rejected (task may have moved on between our
    # SELECT and UPDATE); the event row is still the durable signal.
    blocked_ok = _block_with_reason(task_id, reason)

    # Step 2: human-readable comment. Mirrors the spec's "kanban_comment"
    # call so the panel renders a readable cause line.
    comment_body = (
        f"RECOVERY_REQUIRED: no heartbeat for > "
        f"{max(0, now_epoch - int(task.get('claim_expires') or now_epoch))}s "
        f"on owner={task.get('assignee') or '<unknown>'}. "
        f"Worker PID {task.get('worker_pid') or '<none>'}; "
        f"blocked_ok={blocked_ok}. "
        f"David: review `hermes kanban show {task_id}` and `kanban unblock "
        f"{task_id}` after triage."
    )
    try:
        _add_comment(task_id, comment_body)
    except Exception as exc:  # noqa: BLE001 - best-effort
        log(f"warn: comment write failed for {task_id}: {exc}")

    # Step 3: RECOVERY_REQUIRED event row. This is the durable audit signal.
    _emit_event(task_id, payload)
    return task_id


# --- Entry point ------------------------------------------------------------

def main(
    *,
    window_seconds: Optional[int] = None,
    idempotency_window: int = IDEMPOTENCY_WINDOW_SECONDS,
) -> int:
    """Run one observer tick.

    Args:
        window_seconds: Override the staleness threshold (test hook).
            ``None`` means read from config; 0 disables the check.
        idempotency_window: Override the dedup window (test hook).

    Returns:
        Process exit code. Always 0: cron shouldn't be marked failed for a
        single transient DB hiccup — the next tick retries.
    """
    if window_seconds is None:
        window_seconds = _read_recovery_after_seconds()
    if window_seconds <= 0:
        # Disabled (e.g. ``recovery_required_event_after_seconds: 0`` in
        # config). Stay silent.
        return 0

    try:
        stale = _find_stale_tasks(window_seconds)
    except Exception as exc:  # noqa: BLE001 - log and exit 0
        log(f"warn: stale-task query failed: {exc}")
        return 0

    for task in stale:
        try:
            emitted = _emit_for_task(
                task, idempotency_window=idempotency_window
            )
        except Exception as exc:  # noqa: BLE001 - per-task isolation
            log(f"warn: emit failed for {task.get('id')}: {exc}")
            continue
        if emitted:
            print(f"recovery_required {emitted}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
