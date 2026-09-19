#!/usr/bin/env python3
"""
eligibility.py — Pre-spawn eligibility gate for the kanban dispatcher.

WHY THIS LIVES IN THE ORCHESTRATOR PROFILE
------------------------------------------
Per ORCH-V1 §Roles, only the orchestrator profile owns control-plane code
under .hermes/profiles/orchestrator/**. The eligibility gate sits on the
dispatcher's `ready -> running` transition (between `claim_task` and
`spawn_fn`) and makes deny/allow decisions that depend on the orchestrator's
routing table and the on-disk profile set — both orchestrator-controlled
state. Putting the gate next to `routing_resolver.py` keeps all
control-plane routing logic auditable from one directory and prevents
silent drift across profiles.

WHAT THIS MODULE DOES
---------------------
Exposes one function, ``check(task, resolver_out, assignees_on_disk)``,
that the dispatcher's pre-spawn hook calls for every Work Order it
considers claiming. Returns an ``EligibilityResult`` with three fields:
  - ``allowed`` (bool): True to spawn, False to block.
  - ``denial_reason`` (str | None): structured, machine-readable reason
    when ``allowed`` is False. Always starts with one of the locked
    contract reason tokens so downstream tools can switch on the prefix.
  - ``event_payload`` (dict | None): the WO_ROUTING_DENIED event payload
    the dispatcher should emit when ``allowed`` is False. None when allowed.

ELIGIBILITY CHECKS (locked in SUINI#35.AD-2)
--------------------------------------------
Run in order. First failure wins; later checks are not evaluated so a
task blocked by E1 never also pays the cost of E3/E6 lookups.

  E1. assignee is set on the task dict.
  E2. assignee profile is ON_DISK (in `assignees_on_disk`).
  E3. resolve_route(repo, assignee).allowed == True (delegated to
      routing_resolver.resolve_route; this module trusts its decision).
  E4. per-profile concurrency cap not exceeded (deferred — see below).
  E5. host-wide concurrency cap not exceeded (deferred — see below).
  E6. (Ashley only) task body contains `READ_ONLY: true`; if not, deny
      with ASHLEY_SCOPE_VIOLATION.

E4/E5 are NOT deny conditions — they are DEFER conditions. A capped task
must remain in `ready` (not become `blocked`) so the next dispatcher tick
picks it up when capacity frees. The dispatcher already tracks these in
``DispatchResult.skipped_per_profile_capped``; the eligibility gate
exposes a separate ``deferred`` flag so the caller can record the defer
without touching this module's allow/deny contract.

FAILURE → EVENT EMISSION
------------------------
Per AUTO_DISPATCH_CONTRACT §5, every denial emits a WO_ROUTING_DENIED
event with shape:

    {
      "kind": "WO_ROUTING_DENIED",
      "task_id": "<id>",
      "reason": "<PRODUCT_OWNERSHIP_MISMATCH|ASSIGNEE_NOT_ON_DISK|
                  ALREADY_CLAIMED|UNKNOWN_REPO|ASHLEY_SCOPE_VIOLATION>",
      "context": {"repo": ..., "assignee": ..., "product": ...}
    }

The hook (``eligibility_hook.pre_spawn_check``) writes this event into
the kanban ``events`` table; this module only shapes the payload.

DEPENDENCIES
------------
stdlib + PyYAML only (re-uses the same resolver import as
routing_resolver.py). No Hermes venv lock-in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# --- Locked contract reason tokens (AUTO_DISPATCH_CONTRACT §5) --------------
# These are the only strings allowed in ``EligibilityResult.denial_reason``
# at the prefix. Sub-cases append a colon + descriptor so consumers can
# both switch on the kind AND read a precise cause (mirrors the resolver's
# ``PRODUCT_OWNERSHIP_MISMATCH: assignee=<X>`` pattern).
REASON_PRODUCT_OWNERSHIP_MISMATCH = "PRODUCT_OWNERSHIP_MISMATCH"
REASON_ASSIGNEE_NOT_ON_DISK = "ASSIGNEE_NOT_ON_DISK"
REASON_ALREADY_CLAIMED = "ALREADY_CLAIMED"
REASON_UNKNOWN_REPO = "UNKNOWN_REPO"
REASON_ASHLEY_SCOPE_VIOLATION = "ASHLEY_SCOPE_VIOLATION"

# Sentinel for cap-deferred (E4/E5) — NOT a deny reason.
REASON_DEFERRED_CAP = "DEFERRED_CAP"

# E1 sub-tag (the contract's reason pipe-list does not have a literal
# MISSING_ASSIGNEE entry; we surface it as PRODUCT_OWNERSHIP_MISMATCH
# with a precise descriptor, matching the resolver's colon-suffix style).
_MISSING_ASSIGNEE_DESCRIPTOR = "missing_assignee"
_UNKNOWN_ASSIGNEE_DESCRIPTOR = "assignee_not_routed"


@dataclass(frozen=True)
class EligibilityResult:
    """Outcome of a single eligibility check.

    Attributes:
        allowed: True to spawn, False to block (or defer — see deferred).
        deferred: True when the cap was hit (E4/E5). When True, ``allowed``
            is also False (the task is NOT claimable THIS tick), but no
            WO_ROUTING_DENIED event is emitted — the task stays `ready`
            and the dispatcher's existing
            ``DispatchResult.skipped_per_profile_capped`` counter carries
            the operator-visible signal. Distinct from a real denial so
            the caller can pick the right downstream behaviour.
        denial_reason: Structured reason string when ``allowed`` is False
            and ``deferred`` is False. Always starts with one of the
            locked contract reason tokens. None when allowed=True.
        event_payload: WO_ROUTING_DENIED event payload (per §5) when the
            caller should emit one. None when allowed=True or when
            deferred=True (defer is not an event).
        checked: List of eligibility-check ids that ran, in order.
            Useful for telemetry + debugging ("did we even get to E3?").
    """

    allowed: bool
    deferred: bool = False
    denial_reason: str | None = None
    event_payload: dict[str, Any] | None = None
    checked: list[str] = field(default_factory=list)


def _make_event(
    task: dict[str, Any],
    reason: str,
    resolver_out: Any | None,
) -> dict[str, Any]:
    """Build the WO_ROUTING_DENIED event payload (per §5 contract).

    The contract specifies ``context`` keys: repo, assignee, product.
    Extraction rules:
      - ``task_id``, ``repo``, ``assignee`` come from the task dict only.
        We do NOT backfill assignee from the resolver — the resolver's
        ``assignee`` is the EXPECTED assignee from the table, which is
        a different fact and would mislead the operator reading the
        audit log.
      - ``product`` comes from the resolver when available (the resolver
        is the source of truth for what the table says the product is).
        Falls back to ``None`` when the resolver didn't run (e.g. E1
        failed first), which is the correct signal — "we couldn't
        determine the product because we never got to E3".
    """
    task_id = task.get("id") or task.get("task_id") or "<unknown>"
    repo = task.get("repo") or task.get("repo_or_unmapped")
    assignee = task.get("assignee")
    if isinstance(assignee, str):
        assignee = assignee.strip() or None
    product = getattr(resolver_out, "product", None) if resolver_out is not None else None

    return {
        "kind": "WO_ROUTING_DENIED",
        "task_id": task_id,
        "reason": reason,
        "context": {
            "repo": repo,
            "assignee": assignee,
            "product": product,
        },
    }


def _ashley_route(resolver_out: Any | None) -> bool:
    """True if the resolver says this task is an Ashley-routed task."""
    if resolver_out is None:
        return False
    product = getattr(resolver_out, "product", None)
    return product == "ASHLEY"


def _body_has_read_only(task: dict[str, Any]) -> bool:
    """True if the task body declares ``READ_ONLY: true``.

    Accepts a few common shapes the dispatcher / task-creation path uses:
      - body["READ_ONLY"] == True
      - body["read_only"] == True
      - "READ_ONLY: true" appears in body["body"] text
      - body flags list contains "READ_ONLY"
    """
    if not isinstance(task, dict):
        return False
    body = task.get("body")
    if not isinstance(body, dict):
        return False
    if body.get("READ_ONLY") is True or body.get("read_only") is True:
        return True
    raw = body.get("body") or body.get("text") or ""
    if isinstance(raw, str) and "READ_ONLY: true" in raw:
        return True
    flags = body.get("flags") or []
    if isinstance(flags, (list, tuple, set)) and "READ_ONLY" in flags:
        return True
    return False


def check(
    task: dict[str, Any],
    resolver_out: Any | None,
    assignees_on_disk: set[str],
) -> EligibilityResult:
    """Run E1→E6 against a task and return the resulting gate decision.

    Args:
        task: The kanban task dict. Must carry ``id`` (or ``task_id``)
            and ``assignee`` (E1 checks both). May carry ``repo`` /
            ``repo_or_unmapped`` and a ``body`` dict — body is consulted
            only for E6.
        resolver_out: ``RouteDecision`` from routing_resolver.resolve_route
            for this task's repo+assignee. May be None if E3 wasn't run
            yet (e.g. E1 failed before the resolver was called) — the
            function is defensive about this.
        assignees_on_disk: Set of profile names whose directory exists
            on disk. The dispatcher fetches this via
            ``hermes kanban assignees --json`` and filters on
            ``on_disk == true`` before passing it in. The hook does NOT
            call the CLI itself — that's a side effect we want kept out
            of the gate so tests are hermetic.

    Returns:
        EligibilityResult. The caller:
          - spawns the worker when ``allowed`` is True
          - marks the task ``blocked`` with the denial_reason and emits
            ``event_payload`` when ``allowed`` is False and
            ``deferred`` is False
          - increments ``DispatchResult.skipped_per_profile_capped`` and
            leaves the task in ``ready`` when ``deferred`` is True
    """
    checked: list[str] = []

    # --- E1: assignee is set -------------------------------------------------
    checked.append("E1")
    assignee = (task.get("assignee") or "").strip() if isinstance(task, dict) else ""
    if not assignee:
        reason = f"{REASON_PRODUCT_OWNERSHIP_MISMATCH}: {_MISSING_ASSIGNEE_DESCRIPTOR}"
        return EligibilityResult(
            allowed=False,
            denial_reason=reason,
            event_payload=_make_event(task, reason, resolver_out),
            checked=checked,
        )

    # --- E2: assignee profile is ON_DISK -------------------------------------
    checked.append("E2")
    if assignees_on_disk is None or assignee not in assignees_on_disk:
        reason = REASON_ASSIGNEE_NOT_ON_DISK
        return EligibilityResult(
            allowed=False,
            denial_reason=reason,
            event_payload=_make_event(task, reason, resolver_out),
            checked=checked,
        )

    # --- E3: resolve_route.allowed == True -----------------------------------
    checked.append("E3")
    # If the caller passes resolver_out=None, treat that as "resolver
    # didn't run / wasn't applicable" and skip E3 rather than deny. The
    # production hook (``eligibility_hook.pre_spawn_check``) ALWAYS
    # supplies a real resolver (or a denial-shaped sentinel) so this
    # branch only fires in ad-hoc CLI / one-liner usage where the
    # caller is asserting "I trust the inputs". When the caller wants
    # the gate to deny-on-unknown they can pass a denied RouteDecision
    # explicitly — that's what the production denial path does.
    if resolver_out is not None:
        resolver_allowed = bool(getattr(resolver_out, "allowed", False))
        if not resolver_allowed:
            # Prefer the resolver's own denial_reason if it produced one; the
            # contract requires the prefix be PRODUCT_OWNERSHIP_MISMATCH for
            # routing-table failures, and that's exactly what the resolver
            # emits. We only re-shape when the resolver didn't run.
            existing = getattr(resolver_out, "denial_reason", None)
            if existing and existing.startswith(REASON_PRODUCT_OWNERSHIP_MISMATCH):
                reason = existing
            elif existing and existing.startswith(REASON_UNKNOWN_REPO):
                reason = existing
            else:
                reason = (
                    f"{REASON_PRODUCT_OWNERSHIP_MISMATCH}: {_UNKNOWN_ASSIGNEE_DESCRIPTOR}"
                )
            return EligibilityResult(
                allowed=False,
                denial_reason=reason,
                event_payload=_make_event(task, reason, resolver_out),
                checked=checked,
            )

    # --- E4/E5: cap not exceeded ---------------------------------------------
    # This module doesn't fetch live running counts (the dispatcher does
    # that and passes the cap verdict via `task["_cap_exceeded"]`). We
    # only check the flag here so the caller's defer behaviour is honored.
    checked.append("E4")
    checked.append("E5")
    if task.get("_cap_exceeded") is True:
        # Cap is a DEFER, not a DENY. No WO_ROUTING_DENIED event per §4 of
        # the contract (E4/E5 reuse the existing
        # DispatchResult.skipped_per_profile_capped counter).
        return EligibilityResult(
            allowed=False,
            deferred=True,
            denial_reason=None,
            event_payload=None,
            checked=checked,
        )

    # --- E6: Ashley must be READ_ONLY ----------------------------------------
    checked.append("E6")
    # E6 only fires when the resolver ran and identified the task as
    # Ashley. If no resolver was supplied we can't tell what product
    # this is, so we skip E6 (matches the E3 skip semantics — the
    # production hook always supplies a real resolver).
    if resolver_out is not None and _ashley_route(resolver_out) and not _body_has_read_only(task):
        reason = REASON_ASHLEY_SCOPE_VIOLATION
        return EligibilityResult(
            allowed=False,
            denial_reason=reason,
            event_payload=_make_event(task, reason, resolver_out),
            checked=checked,
        )

    # All checks passed.
    return EligibilityResult(
        allowed=True,
        checked=checked,
    )


if __name__ == "__main__":
    # Minimal CLI for ad-hoc debugging; the real consumer is the hook.
    import argparse
    import json
    import sys

    ap = argparse.ArgumentParser(description="Run the eligibility gate against a task dict.")
    ap.add_argument("--task-id", default="t_demo")
    ap.add_argument("--assignee", default="orchestrator")
    ap.add_argument("--repo", default=None)
    ap.add_argument(
        "--read-only",
        action="store_true",
        help="Inject READ_ONLY: true into body (for Ashley happy path).",
    )
    ap.add_argument(
        "--assignees-on-disk",
        default="orchestrator,default",
        help="Comma-separated profile names considered ON_DISK.",
    )
    args = ap.parse_args()

    task = {
        "id": args.task_id,
        "assignee": args.assignee,
        "repo": args.repo,
        "body": {"READ_ONLY": True} if args.read_only else {},
    }
    on_disk = {a.strip() for a in args.assignees_on_disk.split(",") if a.strip()}

    # When the resolver isn't supplied, fabricate a permissive one for
    # the happy-path CLI demo. Production callers always pass the real one.
    from routing_resolver import RouteDecision  # type: ignore

    resolver_out = RouteDecision(
        allowed=True,
        assignee=args.assignee,
        product="ASHLEY" if args.assignee == "default" else "SUINI",
        capabilities=["read"] if args.assignee == "default" else ["write"],
    )

    result = check(task, resolver_out, on_disk)
    print(json.dumps(result, default=str, indent=2))
    sys.exit(0 if result.allowed else 2)
