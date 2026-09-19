#!/usr/bin/env python3
"""
routing_resolver.py — Read-path wrapper around the orchestrator routing table.

WHY THIS LIVES IN THE ORCHESTRATOR PROFILE (next to github_poller.py)
--------------------------------------------------------------------
Per ORCH-V1 §Roles, the only profile authorised to write control-plane files
under .hermes/profiles/orchestrator/** is HERMES-ORCH. The routing table
(~/.hermes/profiles/orchestrator/config/routing.yaml) is the single source of
truth for repo → product → assignee routing, so the resolver that reads it
must live in the same profile as the file it reads. Putting it here next to
github_poller.py — the only other orchestrator-owned routing logic — keeps all
control-plane routing code co-located and auditable from one directory.

WHAT THIS MODULE DOES
---------------------
Exposes one function, ``resolve_route(repo, task_assignee)``, that the
dispatcher tick calls for every Work-Order it considers claiming. It returns a
``RouteDecision`` (allowed/denied, expected assignee, product, capabilities,
max_runtime_seconds, denial_reason).

PATH RESOLUTION (locked in WO-ORCH-AUTODISPATCH-02 step 3)
----------------------------------------------------------
Three precedence tiers, evaluated in order:
  1. ``HERMES_ROUTING_PATH`` environment variable, when set and non-empty —
     lets a test or one-off script point at a fixture file without touching
     the production control-plane file.
  2. ``HERMES_HOME`` + ``config/routing.yaml`` — every cron tick inside the
     orchestrator profile has ``HERMES_HOME`` set to that profile's root
     (``~/.hermes/profiles/orchestrator``), so the resolver reads the
     profile-local file.
  3. Fallback: the script's own location — ``<here>/../config/routing.yaml``
     (i.e. ``scripts/routing_resolver.py → ../config/routing.yaml``). This
     means even a misconfigured env that erases ``HERMES_HOME`` still lands
     on the orchestrator profile's table rather than the global default.

The fallback (3) is what AUTO_DISPATCH_02 called the "default-path bug":
previously the fallback resolved relative to the script's parent dir only,
which DID land on the profile-local file when HERMES_HOME was unset, but
broke for any caller that imported this module from a different cwd (e.g.
``hermes kanban dispatch --json`` invoked from /tmp). Tier 2 makes that
profile-explicit; tier 3 keeps a sane behaviour when no env is set.

DECISION PRECEDENCE (locked in SUINI#35.AD-1, do NOT change without David GO)
-----------------------------------------------------------------------------
1. Match the incoming ``repo`` against route entries that have a ``repo:`` key.
   First match wins. (Repo-less entries like ASHLEY are matched only when the
   repo is explicitly empty/None.)
2. If a route is matched AND ``task_assignee`` is non-None and disagrees with
   the matched ``assignee:`` → DENY with reason
   ``PRODUCT_OWNERSHIP_MISMATCH: assignee=<X> product=<Y> expected=<Z>``.
3. If no repo matches → DENY with reason
   ``PRODUCT_OWNERSHIP_MISMATCH: repo=<X>``. NEVER silently fall back to
   ``kanban.default_assignee`` — that fallback exists only for explicitly
   unmapped legacy tasks, not for unknown repos that may map in the future.

DEPENDENCIES
------------
stdlib + PyYAML only. No Hermes venv lock-in.

USAGE
-----
    from routing_resolver import resolve_route
    decision = resolve_route("neokyhurtado-cmd/suini", None)
    if decision.allowed:
        ...dispatch to decision.assignee ...
    else:
        ...block the task with decision.denial_reason ...
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import yaml


# --- Path resolution ---------------------------------------------------------
# Tier 1: HERMES_ROUTING_PATH override (tests, fixtures, one-offs).
# Tier 2: HERMES_HOME/config/routing.yaml — the normal cron path.
# Tier 3: <script-dir>/../config/routing.yaml — keeps the resolver usable
#          even if HERMES_HOME is unset (e.g. invoked from a tmpdir shell).

_HERE = os.path.dirname(os.path.abspath(__file__))


def _resolve_default_path() -> str:
    """Return the routing.yaml path per the 3-tier precedence (see module doc)."""
    override = os.environ.get("HERMES_ROUTING_PATH")
    if override and override.strip():
        return override.strip()
    home = os.environ.get("HERMES_HOME")
    if home and home.strip():
        return os.path.join(home.strip(), "config", "routing.yaml")
    # Fallback: walk up from this script to the orchestrator profile root.
    return os.path.join(_HERE, "..", "config", "routing.yaml")


# Module-level default, evaluated lazily so test fixtures that patch the env
# AFTER import are still respected on the first resolve_route() call.
def _get_default_path() -> str:
    return _resolve_default_path()


@dataclass(frozen=True)
class RouteDecision:
    """Outcome of a routing-table lookup.

    Attributes:
        allowed: True if the task may proceed; False if it must be blocked.
        assignee: Profile to dispatch to (None when denied or no match).
        product: Product code (SUINI / IA-VISION / ASHLEY) when matched.
        capabilities: List of capability strings granted by the route
            (e.g. ["write"], ["read"]). Empty list when denied.
        max_runtime_seconds: Per-task runtime cap from the route (None when
            the route doesn't set one or when denied).
        denial_reason: Structured human-readable reason when allowed=False.
            Always starts with ``PRODUCT_OWNERSHIP_MISMATCH:`` per the
            contract so downstream tools can parse it.
        matched: The route entry dict that was matched, or None.
    """

    allowed: bool
    assignee: str | None = None
    product: str | None = None
    capabilities: list[str] = field(default_factory=list)
    max_runtime_seconds: int | None = None
    denial_reason: str | None = None
    matched: dict[str, Any] | None = None


def _load_routing_table(path: str | None = None) -> list[dict[str, Any]]:
    """Load and minimally-validate the routing.yaml file.

    Raises FileNotFoundError if the file is missing — the dispatcher must
    hard-fail rather than silently fall back, because a missing routing table
    means control-plane ownership has drifted.
    """
    p = path if path is not None else _get_default_path()
    with open(p, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    routes = data.get("routes")
    if not isinstance(routes, list):
        raise ValueError(f"routing.yaml at {p} has no 'routes:' list")
    return routes


def _match_route(routes: list[dict[str, Any]], repo: str | None) -> dict[str, Any] | None:
    """Return the first route whose ``repo`` matches ``repo`` exactly.

    Routes without a ``repo`` key (e.g. ASHLEY) are matched only when
    ``repo`` is None/empty — they are product-only fallback routes that
    intentionally don't claim any particular repo.
    """
    target = (repo or "").strip()
    for r in routes:
        rrepo = (r.get("repo") or "").strip()
        if rrepo and rrepo == target:
            return r
    # No repo match. If the caller passed None and there is exactly one
    # product-only route (e.g. ASHLEY), use it. This is intentional: a repo-less
    # task (e.g. an ad-hoc kanban card) hits the read-only canary.
    if not target:
        product_only = [r for r in routes if not (r.get("repo") or "").strip()]
        if len(product_only) == 1:
            return product_only[0]
    return None


def resolve_route(repo: str | None, task_assignee: str | None) -> RouteDecision:
    """Resolve a repo + optional pre-set task assignee to a RouteDecision.

    Args:
        repo: ``owner/name`` of the source GitHub repo, or None for repo-less
            kanban tasks.
        task_assignee: The ``assignee`` field already present on the kanban
            task (may be None for newly-created tasks). When set and it
            disagrees with the routing table, the resolver DENIES — table
            wins, operator override requires David GO.

    Returns:
        RouteDecision. Always inspect ``allowed`` first; on False the
        ``denial_reason`` is what the dispatcher should record as the
        blocked-task reason.
    """
    routes = _load_routing_table()
    matched = _match_route(routes, repo)

    if matched is None:
        # R1: UNKNOWN repo -> DENY. Never auto-fallback to default_assignee
        # when the product might be known but the repo isn't mapped.
        return RouteDecision(
            allowed=False,
            denial_reason=f"PRODUCT_OWNERSHIP_MISMATCH: repo={repo}",
            matched=None,
        )

    expected_assignee = matched.get("assignee")
    product = matched.get("product")

    # R3 (task_assignee mismatch): table wins.
    if task_assignee and expected_assignee and task_assignee != expected_assignee:
        return RouteDecision(
            allowed=False,
            assignee=expected_assignee,
            product=product,
            denial_reason=(
                f"PRODUCT_OWNERSHIP_MISMATCH: assignee={task_assignee} "
                f"product={product} expected={expected_assignee}"
            ),
            matched=matched,
        )

    return RouteDecision(
        allowed=True,
        assignee=expected_assignee,
        product=product,
        capabilities=list(matched.get("capabilities") or []),
        max_runtime_seconds=matched.get("max_runtime_seconds"),
        matched=matched,
    )


def current_routing_path() -> str:
    """Return the routing.yaml path that the next resolve_route() call would
    load. Useful for diagnostics and the explicit-path tests.
    """
    return _get_default_path()


if __name__ == "__main__":
    # Minimal CLI for ad-hoc checks; the real consumer is the dispatcher.
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="Resolve a repo against the orchestrator routing table.")
    ap.add_argument("--repo", default=None, help="owner/name of the source repo (omit for repo-less tasks)")
    ap.add_argument("--task-assignee", default=None, help="assignee already set on the task (if any)")
    ap.add_argument("--routing-path", default=None, help="override routing.yaml path (mostly for tests)")
    ap.add_argument("--show-path", action="store_true", help="print the routing.yaml path the resolver would load and exit")
    args = ap.parse_args()

    if args.show_path:
        print(current_routing_path())
        sys.exit(0)

    if args.routing_path:
        # Allow tests / one-offs to point at a fixture file by overriding the
        # default path used by _load_routing_table via a tiny monkey-patch.
        import routing_resolver as _self

        _self._load_routing_table = lambda path=None: _self._load_routing_table(args.routing_path)

    decision = resolve_route(args.repo, args.task_assignee)
    print(decision)
    sys.exit(0 if decision.allowed else 2)
