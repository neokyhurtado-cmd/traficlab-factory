"""Single Kanban dispatch primitive — the ONLY real implementation of
"talk to the Kanban CLI".

Why this module exists
----------------------
Phase 2 of the directive watcher (see traficlab-factory#18) shipped two
parallel subprocess pipelines that both spawned ``hermes kanban create``:

  - ``orchestrator/scripts/github_poller.py::create_kanban_task``
  - ``directive_watcher/orch_dispatch.py::OrchestratorDispatcher._invoke_kanban``

The Phase 3 directive (comment 5629246987, locked by David in
comment 5629293070) froze the architecture as:

    ONE KANBAN PRIMITIVE  —  the single real implementation
    MULTIPLE ADAPTERS     —  allowed (per the steer)

Adaptors like ``OrchestratorDispatcher`` survive because they handle the
domain work (resolve Directive → payload, persist SessionRecord, return
DispatchResult). But the actual ``hermes kanban create`` subprocess call
must live in ONE place. This module is that place.

Both adapters (Work Order path + directive path) call
``dispatch_to_kanban(payload, idempotency_key)`` and only differ on the
idempotency_key prefix (``github:<repo>#<issue>`` vs
``directive:<DIRECTIVE_ID>``). Same payload contract → same kanban call
shape → single source of truth.
"""
from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Mapping


# Public payload shape — both adapters produce a Mapping with these keys.
# Keeping the shape small and explicit prevents drift between the two
# call sites; if a future adapter wants a richer body it can extend the
# mapping without changing this primitive.
REQUIRED_PAYLOAD_KEYS = frozenset({
    "title", "body", "assignee", "parent_task_id",
})


def _validate_payload(payload: Mapping[str, Any]) -> None:
    """Fail-closed payload check. Callers that omit required keys must
    not silently produce malformed kanban calls."""
    missing = REQUIRED_PAYLOAD_KEYS - set(payload.keys())
    if missing:
        raise ValueError(
            f"dispatch_to_kanban payload missing required keys: "
            f"{sorted(missing)}"
        )
    if not isinstance(payload.get("title"), str) or not payload["title"].strip():
        raise ValueError("dispatch_to_kanban payload.title must be a non-empty string")
    if not isinstance(payload.get("body"), str):
        raise ValueError("dispatch_to_kanban payload.body must be a string")
    if not isinstance(payload.get("assignee"), str) or not payload["assignee"].strip():
        raise ValueError("dispatch_to_kanban payload.assignee must be a non-empty string")


def dispatch_to_kanban(
    payload: Mapping[str, Any],
    idempotency_key: str,
    *,
    kanban_bin: str | None = None,
    timeout_seconds: int = 60,
) -> str:
    """Invoke ``hermes kanban create`` and return the task_id.

    This is the SINGLE real implementation of "talk to the kanban CLI".
    Both the Work Order adapter (``orchestrator/scripts/github_poller.py``)
    and the directive adapter (``directive_watcher/orch_dispatch.py``) call
    this function with different ``idempotency_key`` values. There must
    never be a second ``subprocess.run([..., "hermes", "kanban", "create", ...])``
    in the repo.

    Args:
        payload: dict-like with at least ``title``, ``body``, ``assignee``,
            ``parent_task_id``. Adapters build it from their domain object
            (Directive or Work Order) and pass it in unchanged.
        idempotency_key: the dedup key the kanban CLI uses. Convention:
            ``github:<repo>#<issue>`` for WOs,
            ``directive:<DIRECTIVE_ID>`` for directives.
        kanban_bin: override the ``hermes`` binary path (tests use this).
        timeout_seconds: subprocess timeout.

    Returns:
        The ``id`` field of the kanban CLI's JSON response.

    Raises:
        ValueError: on malformed payload.
        RuntimeError: on subprocess failure or malformed CLI output.
    """
    _validate_payload(payload)
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise ValueError(
            f"dispatch_to_kanban idempotency_key must be a non-empty string, "
            f"got {idempotency_key!r}"
        )

    bin_path = kanban_bin or os.environ.get("HERMES_KANBAN_BIN") or "hermes"
    cmd = [
        bin_path, "kanban", "create", payload["title"],
        "--body", payload["body"],
        "--assignee", payload["assignee"],
        "--parent", payload["parent_task_id"],
        "--idempotency-key", idempotency_key,
        "--json",
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout_seconds
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"hermes kanban create failed for {idempotency_key} "
            f"(exit {proc.returncode}): {proc.stderr.strip()[:300]}"
        )
    try:
        result = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"could not parse kanban JSON for {idempotency_key}: {e}"
        ) from e
    return str(result.get("id") or "")
