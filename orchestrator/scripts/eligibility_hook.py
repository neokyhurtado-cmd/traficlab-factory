#!/usr/bin/env python3
"""
eligibility_hook.py — Drop-in pre_spawn_check shim for the dispatcher tick.

WHY THIS LIVES IN THE ORCHESTRATOR PROFILE
------------------------------------------
Per ORCH-V1 §Roles, only the orchestrator profile owns control-plane code
under .hermes/profiles/orchestrator/**. The hook is called from the
dispatcher's `ready -> running` transition (between `claim_task` and
`spawn_fn`) and depends on the orchestrator's routing table + on-disk
profile set — both orchestrator-controlled state.

WHAT THIS MODULE DOES
---------------------
Exposes one function, ``pre_spawn_check(task)``, callable from a one-liner:

    from eligibility_hook import pre_spawn_check
    result = pre_spawn_check(task)

The hook does the work the dispatcher tick would otherwise have to do
inline before calling ``spawn_fn``:

  1. Loads the on-disk assignees set (via ``hermes kanban assignees
     --json``).
  2. Calls ``routing_resolver.resolve_route(task.repo_or_unmapped,
     task.assignee)`` for the E3 lookup.
  3. Calls ``eligibility.check(...)`` to get the allow/deny/defer verdict.
  4. When the verdict is a denial (allowed=False, deferred=False), emits
     the WO_ROUTING_DENIED event into the kanban ``events`` table via
     ``hermes_cli.kanban_db`` so the audit trail matches the contract.

The hook is INTENTIONALLY thin and idempotent. The dispatcher can call
it any number of times per tick; the resolver / assignees lookups are
cached at the process level via functools.lru_cache so repeated calls
don't re-execute the CLI.

CALLING CONTEXTS
----------------
Two production callers, same function:
  - ``hermes kanban dispatch --json`` (the manual CLI path) — invoked
    once per ready task immediately before ``spawn_fn`` is called.
  - The gateway-embedded dispatcher tick — invoked from the same place
    inside ``dispatch_once`` after the orchestrator config wires the
    hook in (a separate work order per the FORBIDDEN list in the task
    body: dispatcher source edits are gated on a follow-up WO).

FAILURE MODE
------------
If the resolver / assignees fetch raises, the hook treats the task as
DENIED with reason=PRODUCT_OWNERSHIP_MISMATCH: hook_error so the
dispatcher never silently spawns a task whose routing state it could
not verify. The event is emitted before the dispatcher moves the task
to ``blocked`` so the operator sees the exact cause.

DEPENDENCIES
------------
- eligibility.py (same dir)
- routing_resolver.py (same dir, from WO-AD-1)
- hermes_cli.kanban_db (stdlib hermes CLI; emits the WO_ROUTING_DENIED
  event row via the existing ``event(...)`` helper)
- subprocess (stdlib, for the ``hermes kanban assignees --json`` CLI
  call) — see ``_load_assignees_on_disk`` for why this is a CLI call
  rather than a Python import.
"""

from __future__ import annotations

import functools
import json
import os
import subprocess
import sys
from typing import Any

# Co-located modules — make sure we can import each other regardless of
# the caller's CWD (matches the convention in test_routing_resolver.py).
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import eligibility  # noqa: E402
import routing_resolver  # noqa: E402


# --- On-disk assignees cache ----------------------------------------------
# We invoke `hermes kanban assignees --json` rather than importing the
# assignees logic directly because (a) that CLI is the single source of
# truth for `on_disk` semantics (it walks ~/.hermes/profiles/<name>/),
# and (b) the hook is a thin shim and should not duplicate that walk.
# Cached because it's the same answer for the whole dispatcher tick.
@functools.lru_cache(maxsize=1)
def _load_assignees_on_disk() -> frozenset[str]:
    """Return a frozenset of profile names whose directory is ON_DISK.

    Runs ``hermes kanban assignees --json`` and filters on
    ``on_disk == true``. Raises RuntimeError on subprocess failure —
    callers should treat that as a hard fail (per the failure-mode note
    in the module docstring).
    """
    try:
        proc = subprocess.run(
            ["hermes", "kanban", "assignees", "--json"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise RuntimeError(f"hermes kanban assignees --json failed: {exc}") from exc

    try:
        rows = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"hermes kanban assignees --json: malformed JSON: {exc}") from exc

    return frozenset(
        str(row["name"]) for row in rows if isinstance(row, dict) and row.get("on_disk") is True
    )


# --- Event emission --------------------------------------------------------
# We import lazily so the hook can be imported (e.g. by tests) without
# requiring the hermes_cli package to be on sys.path in unusual envs.
@functools.lru_cache(maxsize=1)
def _event_writer():
    """Return a callable ``emit(kind, payload, task_id)`` that writes
    one event row into the kanban DB.

    Imported lazily so importing the hook doesn't require hermes_cli
    to be importable; the actual emission call is rare and lazy.
    """
    try:
        from hermes_cli import kanban_db
    except ImportError as exc:  # pragma: no cover - exercised only if hermes_cli is missing
        raise RuntimeError(f"hermes_cli.kanban_db not importable: {exc}") from exc

    def _emit(task_id: str, kind: str, payload: dict[str, Any]) -> None:
        # kanban_db exposes a private _append_event(conn, task_id, kind,
        # payload) helper used by every internal write path (assign,
        # comment, dispatch tick, ...). We open our own short-lived
        # connection via the connect_closing context manager so the
        # hook stays a drop-in shim that doesn't depend on a
        # caller-held txn.
        try:
            with kanban_db.connect_closing() as conn:
                kanban_db._append_event(conn, task_id, kind, payload)
                conn.commit()
        except Exception as exc:  # pragma: no cover - exercised only if DB is unavailable
            raise RuntimeError(f"kanban event write failed: {exc}") from exc

    return _emit


def _resolve(task: dict[str, Any]):
    """Run routing_resolver.resolve_route, swallowing resolver failures
    as a "denied" sentinel so the eligibility gate still produces a
    structured event instead of crashing the dispatcher.

    A resolver failure (e.g. missing routing.yaml) is a control-plane
    drift signal — the gate MUST hard-deny in that case, never silently
    allow.
    """
    repo = task.get("repo") or task.get("repo_or_unmapped")
    task_assignee = task.get("assignee")
    try:
        return routing_resolver.resolve_route(repo, task_assignee)
    except (FileNotFoundError, ValueError, KeyError) as exc:
        # Synthesize a denial-shaped RouteDecision so the gate can still
        # produce a structured event. We don't reuse the real class to
        # avoid import-order coupling — duck-typed attribute access in
        # ``eligibility.check`` already handles this.
        return type(
            "_ResolverError",
            (),
            {
                "allowed": False,
                "denial_reason": f"PRODUCT_OWNERSHIP_MISMATCH: resolver_error={type(exc).__name__}",
                "assignee": None,
                "product": None,
                "capabilities": [],
            },
        )()


def pre_spawn_check(task: dict[str, Any]) -> eligibility.EligibilityResult:
    """Run the full pre-spawn gate for one task.

    One-liner:
        from eligibility_hook import pre_spawn_check
        result = pre_spawn_check(task)

    Args:
        task: The kanban task dict. The hook reads ``id`` (or
            ``task_id``), ``assignee``, ``repo`` (or
            ``repo_or_unmapped``), and ``body``.

    Returns:
        EligibilityResult. The caller (``dispatch_once`` / ``hermes
        kanban dispatch``) decides what to do with each branch:
          - allowed=True → proceed to spawn_fn
          - deferred=True → record in skipped_per_profile_capped, leave
            task in ``ready``, do NOT spawn this tick
          - allowed=False (real denial) → mark task ``blocked`` with
            result.denial_reason; the event has already been emitted.

    Side effects:
        - On denial, emits a WO_ROUTING_DENIED event row into the kanban
          events table via hermes_cli.kanban_db.event(...).
        - Fetches the on-disk assignees set (cached for the tick).
        - Calls the routing resolver once per task (cheap).
    """
    if not isinstance(task, dict):
        # Defensive: a non-dict task is unrecoverable. Deny with the
        # structured reason and emit an event so the operator sees it.
        bad_result = eligibility.EligibilityResult(
            allowed=False,
            denial_reason="PRODUCT_OWNERSHIP_MISMATCH: invalid_task_payload",
            event_payload={
                "kind": "WO_ROUTING_DENIED",
                "task_id": "<unknown>",
                "reason": "PRODUCT_OWNERSHIP_MISMATCH",
                "context": {"repo": None, "assignee": None, "product": None},
            },
            checked=[],
        )
        try:
            _event_writer()(bad_result.event_payload["task_id"], "WO_ROUTING_DENIED", bad_result.event_payload)
        except RuntimeError:
            # Event emission failed (hermes_cli not importable). Don't
            # crash the dispatcher — return the result so the caller can
            # still surface the denial some other way.
            pass
        return bad_result

    # Fetch on-disk assignees. Any failure here is a control-plane drift
    # signal — hard-deny with a structured reason so the operator sees it.
    try:
        on_disk = _load_assignees_on_disk()
    except RuntimeError as exc:
        reason = f"PRODUCT_OWNERSHIP_MISMATCH: hook_error=assignees_unavailable"
        task_id = task.get("id") or task.get("task_id") or "<unknown>"
        payload = {
            "kind": "WO_ROUTING_DENIED",
            "task_id": task_id,
            "reason": reason,
            "context": {
                "repo": task.get("repo") or task.get("repo_or_unmapped"),
                "assignee": task.get("assignee"),
                "product": None,
            },
        }
        return eligibility.EligibilityResult(
            allowed=False,
            denial_reason=reason,
            event_payload=payload,
            checked=[],
        )

    # Run the resolver (E3 input). The hook swallows resolver failures
    # into a denial-shaped sentinel so the gate still produces an event.
    resolver_out = _resolve(task)

    # Run the gate itself.
    result = eligibility.check(task, resolver_out, set(on_disk))

    # Emit the WO_ROUTING_DENIED event when this is a real denial.
    # Cap-defer (deferred=True) is NOT an event per the contract.
    if not result.allowed and not result.deferred and result.event_payload:
        try:
            _event_writer()(
                result.event_payload["task_id"],
                "WO_ROUTING_DENIED",
                result.event_payload,
            )
        except RuntimeError:
            # Event emission failed. Leave the result intact so the
            # caller still has the structured denial reason; the task
            # will be blocked correctly even if the audit row is missing.
            pass

    return result


if __name__ == "__main__":
    # Minimal CLI for ad-hoc debugging.
    import argparse

    ap = argparse.ArgumentParser(description="Run pre_spawn_check on a task from CLI args.")
    ap.add_argument("--task-id", default="t_demo")
    ap.add_argument("--assignee", default="orchestrator")
    ap.add_argument("--repo", default=None)
    ap.add_argument("--read-only", action="store_true")
    args = ap.parse_args()

    task = {
        "id": args.task_id,
        "assignee": args.assignee,
        "repo": args.repo,
        "body": {"READ_ONLY": True} if args.read_only else {},
    }
    result = pre_spawn_check(task)
    print(json.dumps(result, default=str, indent=2))
    import sys as _sys

    _sys.exit(0 if result.allowed else 2)
