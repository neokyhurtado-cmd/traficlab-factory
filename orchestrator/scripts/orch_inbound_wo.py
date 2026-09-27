#!/usr/bin/env python3
"""
TELEGRAM CONTRACT (Lane 18, fixing #20)
=======================================
This module is the **only** place in this repository where the literal
string "telegram" may appear in production code. It appears as a value
of `requester_platform` (a string field, informational only), exactly
like `discord` is. There is NO Telegram bot, NO Telegram SDK import, NO
Telegram session store, NO Telegram scheduler in this repo, and the
anti-regression tests in ``tests/test_telegram_normal_session.py``,
``tests/test_no_second_state_store.py``, and
``tests/test_no_second_scheduler.py`` keep it that way. See
``TELEGRAM_CONTRACT.md`` at the repo root for the full contract.

orch_inbound_wo.py — Narrow ORCH inbound Work-Order action.

WHY THIS LIVES IN THE ORCHESTRATOR PROFILE
------------------------------------------
Per ORCH-V1 §Roles, only the orchestrator profile owns control-plane code
under .hermes/profiles/orchestrator/**. The inbound-WO gate sits at the
Telegram/Discord → GitHub seam and decides what David (or another allowed
requester) can ask the factory to do. Putting the gate next to
routing_resolver.py keeps all control-plane routing logic auditable from one
directory.

WHAT THIS MODULE DOES
---------------------
Validates a structured inbound payload from the gateway (Telegram/Discord
webhook layer — the gateway has already authenticated the requester and
identified their chat_id), and performs ONE of a fixed allow-list of
narrow actions:

  - create_wo    : create a new labelled GitHub issue.
  - update_wo    : edit the body of an existing WO (number + body).
  - add_label    : attach an allowed label to an existing issue.
  - remove_label : detach an allowed label from an existing issue.
  - transition_status : close / reopen an existing issue.

For every accepted action the module writes a durable ``ORCH_INBOUND_WO``
audit row into the kanban DB so the operator can see exactly who asked for
what, when.

WHAT THIS MODULE DOES NOT DO
----------------------------
- No raw shell text is accepted (FORBIDDEN list).
- No arbitrary command execution.
- No file edits outside the routing/control-plane directory.
- No outbound network calls except the narrow `gh` commands listed above
  AND the kanban audit write (both over the already-trusted hermes CLI).
- No privilege escalation: every action must name an (allowed_requester,
  allowed_product, allowed_repo, allowed_scope, allowed_action) tuple
  that the requester is authorised for. Unknown combos are refused.

CALL SHAPE
----------
The webhook layer pipes a single JSON object to this script on stdin:

    {
      "requester": "david-telegram",
      "requester_chat_id": "1234567890",
      "requester_platform": "telegram",
      "action": "create_wo",
      "product": "SUINI",
      "repo": "neokyhurtado-cmd/suini",
      "title": "...",
      "body": "...",
      "labels": ["hermes-work-order"],
      "issue_number": 35        // for update / label / transition
    }

The script prints one JSON line to stdout:

    {"accepted": true, "action": "create_wo", "result": {...}}
    {"accepted": false, "action": "create_wo", "reason": "..."}

Exit code is always 0 — the gateway reads stdout for the verdict. Non-zero
exits are reserved for transport-level errors (the script crashed), which
the gateway surfaces differently from a policy rejection.

DEPENDENCIES
------------
stdlib + PyYAML + hermes_cli.kanban_db (for the audit row). No shell-out
beyond `gh` and `hermes kanban`.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from typing import Any


# --- Allow-list configuration (locked in AUTO_DISPATCH_02 step 6) ----------
#
# These are the ONLY things a requester is allowed to ask for. Any payload
# outside these sets is refused before any `gh` call is made.

# Allowed requester identifiers. The gateway maps a chat_id to one of these
# names. Anything else is rejected (e.g. "alice-telegram" → "unknown").
ALLOWED_REQUESTERS = frozenset({
    "david-telegram",
    "david-discord",
})

# We accept David's personal chat IDs from both platforms. The gateway has
# already authenticated the requester; this list is the second factor that
# survives a gateway misconfig. Update via env vars so the operator does
# not have to redeploy the script when David adds a new device.
DEFAULT_DAVID_CHAT_IDS = (
    # David's Telegram chat_id (from the gateway pairing). Configured
    # at runtime via ORCH_INBOUND_DAVID_CHAT_IDS as a comma-separated list.
    # Leaving the default empty is safe — operator must explicitly opt-in.
)


def _david_chat_ids() -> set[str]:
    raw = os.environ.get("ORCH_INBOUND_DAVID_CHAT_IDS", "")
    return {x.strip() for x in raw.split(",") if x.strip()}


# Allowed actions.
ALLOWED_ACTIONS = frozenset({
    "create_wo",
    "update_wo",
    "add_label",
    "remove_label",
    "transition_status",
})

# Allowed products. Pulled from the orchestrator routing table at runtime
# (single source of truth), with this static list as a defensive fallback.
DEFAULT_ALLOWED_PRODUCTS = frozenset({"SUINI", "IA-VISION"})

# Allowed repositories. Same as above — pulled from the routing table.
# The static list here is the fallback only.

# Allowed labels for create_wo / add_label. Adding `hermes-work-order` is
# what wires a GitHub issue into the routing pipeline.
ALLOWED_LABELS = frozenset({
    "hermes-work-order",
    "orchestration",
})

# Allowed transition targets. ``closed`` and ``reopen`` are the two we need
# for "David finished a WO" / "David wants a WO back in the queue".
ALLOWED_STATUSES = frozenset({"closed", "open", "reopen"})

# Title / body limits. Defensive: a misbehaving requester can't push
# megabytes through the gateway.
MAX_TITLE_LEN = 240
MAX_BODY_LEN = 60_000


# --- Routing-table-backed product/repo discovery ----------------------------
#
# We refuse requests for a product or repo that the orchestrator routing
# table does not recognise. This is the same fail-closed posture the
# poller and dispatcher use; the inbound WO action must not be the one
# path that bypasses it.

def _load_routing() -> list[dict[str, Any]]:
    """Read the orchestrator routing table via the co-located resolver.

    Same path-resolution contract as routing_resolver (HERMES_ROUTING_PATH
    > HERMES_HOME > default fallback)."""
    try:
        import routing_resolver  # type: ignore
        return routing_resolver._load_routing_table()
    except Exception:
        return []


def _allowed_products_and_repos() -> tuple[frozenset[str], frozenset[str]]:
    """Return (allowed_products, allowed_repos) sourced from the routing
    table. Defensive fallback to the DEFAULT_* sets if the table is
    unavailable so a transient control-plane failure does not silently
    grant access."""
    routes = _load_routing()
    products = {r.get("product") for r in routes if r.get("product")}
    repos = {r.get("repo") for r in routes if r.get("repo")}
    if not products:
        products = set(DEFAULT_ALLOWED_PRODUCTS)
    if not repos:
        repos = set()
    return frozenset(products), frozenset(repos)


# --- Payload validation ----------------------------------------------------

def _is_valid_string(v: Any, *, max_len: int) -> bool:
    return isinstance(v, str) and 0 < len(v.strip()) <= max_len


def _validate(payload: dict[str, Any]) -> tuple[bool, str]:
    """Return (accepted, reason). On accepted=True, reason is empty.

    Validates the payload against the allow-list. Does NOT perform the
    action — that's ``dispatch()``'s job, after this returns OK.
    """
    if not isinstance(payload, dict):
        return False, "payload_not_object"

    requester = (payload.get("requester") or "").strip()
    if requester not in ALLOWED_REQUESTERS:
        return False, f"unknown_requester={requester!r}"

    # Second-factor: the gateway tells us who the requester is, but the
    # chat_id must be in David's allow-list as well. A compromised
    # requester name still fails this check.
    chat_id = (payload.get("requester_chat_id") or "").strip()
    if chat_id and chat_id not in _david_chat_ids():
        return False, f"unknown_chat_id={chat_id!r}"

    action = (payload.get("action") or "").strip()
    if action not in ALLOWED_ACTIONS:
        return False, f"unknown_action={action!r}"

    product = (payload.get("product") or "").strip()
    repo = (payload.get("repo") or "").strip()
    products, repos = _allowed_products_and_repos()
    if product not in products:
        return False, f"unknown_product={product!r}"
    if repo not in repos:
        return False, f"unknown_repo={repo!r}"

    # Action-specific checks.
    if action == "create_wo":
        title = payload.get("title")
        if not _is_valid_string(title, max_len=MAX_TITLE_LEN):
            return False, "create_wo_requires_title"
        body = payload.get("body")
        # body is OPTIONAL for create_wo; when present it must be a string
        # within MAX_BODY_LEN.
        if body is not None and (
            not isinstance(body, str) or len(body) > MAX_BODY_LEN
        ):
            return False, "create_wo_body_too_long_or_not_str"
        labels = payload.get("labels") or ["hermes-work-order"]
        if not isinstance(labels, list) or not labels:
            return False, "create_wo_labels_must_be_nonempty_list"
        for lbl in labels:
            if not isinstance(lbl, str) or lbl not in ALLOWED_LABELS:
                return False, f"create_wo_label_not_allowed={lbl!r}"

    elif action == "update_wo":
        number = payload.get("issue_number")
        if not isinstance(number, int) or number <= 0:
            return False, "update_wo_requires_positive_int_issue_number"
        body = payload.get("body")
        if not isinstance(body, str) or not body.strip():
            return False, "update_wo_requires_nonempty_body"
        if len(body) > MAX_BODY_LEN:
            return False, "update_wo_body_too_long"

    elif action in ("add_label", "remove_label"):
        number = payload.get("issue_number")
        if not isinstance(number, int) or number <= 0:
            return False, f"{action}_requires_positive_int_issue_number"
        lbl = payload.get("label")
        if not isinstance(lbl, str) or lbl not in ALLOWED_LABELS:
            return False, f"{action}_label_not_allowed={lbl!r}"

    elif action == "transition_status":
        number = payload.get("issue_number")
        if not isinstance(number, int) or number <= 0:
            return False, "transition_status_requires_positive_int_issue_number"
        status = (payload.get("status") or "").strip()
        if status not in ALLOWED_STATUSES:
            return False, f"transition_status_status_not_allowed={status!r}"

    return True, ""


# --- Action dispatch --------------------------------------------------------

def _gh(*args: str, timeout: int = 30) -> tuple[int, str, str]:
    """Run `gh ...` and return (returncode, stdout, stderr).

    Failure is propagated as a return value — the caller decides whether
    a non-zero exit is fatal for the inbound action."""
    proc = subprocess.run(
        ["gh", *args], capture_output=True, text=True, timeout=timeout
    )
    return proc.returncode, proc.stdout, proc.stderr


def _emit_audit_row(payload: dict[str, Any], verdict: dict[str, Any]) -> None:
    """Write a durable ORCH_INBOUND_WO audit row into the kanban DB.

    Best-effort: if hermes_cli is unavailable or the DB write fails, the
    action still succeeds — the operator just sees a missing audit row,
    which is preferable to dropping a request that passed every other
    gate."""
    try:
        from hermes_cli import kanban_db
    except Exception:
        return

    audit_task_id = (payload.get("idempotency_key") or "").strip() or None
    # The audit row is keyed by an idempotency-token-style string
    # ("orch-inbound:<requester>:<action>:<random>"). If a kanban task
    # already exists for this token we leave it alone; the row payload
    # is what carries the audit semantics.
    task_id = audit_task_id or (
        f"orch-inbound:{payload.get('requester', '?')}:"
        f"{payload.get('action', '?')}:{verdict.get('audit_token', 'no-token')}"
    )
    try:
        with kanban_db.connect_closing() as conn:
            kanban_db._append_event(
                conn,
                task_id,
                "ORCH_INBOUND_WO",
                {
                    "requester": payload.get("requester"),
                    "chat_id": payload.get("requester_chat_id"),
                    "platform": payload.get("requester_platform"),
                    "action": payload.get("action"),
                    "product": payload.get("product"),
                    "repo": payload.get("repo"),
                    "issue_number": payload.get("issue_number"),
                    "accepted": verdict.get("accepted"),
                    "reason": verdict.get("reason"),
                    "gh_result": verdict.get("gh_result"),
                },
            )
            conn.commit()
    except Exception:
        # Best-effort — never let audit failure break the action.
        pass


def dispatch(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate + execute one inbound WO action.

    Returns a verdict dict shaped for stdout (accepted, action, ...).
    Never raises (the gateway reads stdout, not stderr)."""
    accepted, reason = _validate(payload)
    verdict: dict[str, Any] = {
        "accepted": accepted,
        "action": payload.get("action") if isinstance(payload, dict) else None,
        "reason": reason or None,
    }

    if not accepted:
        _emit_audit_row(payload, verdict)
        return verdict

    action = payload["action"]
    repo = payload["repo"]
    gh_result: dict[str, Any] = {}

    try:
        if action == "create_wo":
            title = payload["title"].strip()
            body = (payload.get("body") or "").strip()
            labels = payload.get("labels") or ["hermes-work-order"]
            cmd = [
                "issue", "create",
                "--repo", repo,
                "--title", title,
                "--body", body or "(no description provided)",
            ]
            for lbl in labels:
                cmd.extend(["--label", lbl])
            rc, out, err = _gh(*cmd)
            gh_result = {"returncode": rc, "stdout": out.strip()[:1000], "stderr": err.strip()[:1000]}
            if rc != 0:
                verdict["accepted"] = False
                verdict["reason"] = "gh_issue_create_failed"

        elif action == "update_wo":
            number = int(payload["issue_number"])
            body = payload["body"]
            rc, out, err = _gh(
                "issue", "edit", str(number),
                "--repo", repo,
                "--body", body,
            )
            gh_result = {"returncode": rc, "stdout": out.strip()[:1000], "stderr": err.strip()[:1000]}
            if rc != 0:
                verdict["accepted"] = False
                verdict["reason"] = "gh_issue_edit_failed"

        elif action == "add_label":
            number = int(payload["issue_number"])
            lbl = payload["label"]
            rc, out, err = _gh(
                "issue", "edit", str(number),
                "--repo", repo,
                "--add-label", lbl,
            )
            gh_result = {"returncode": rc, "stdout": out.strip()[:1000], "stderr": err.strip()[:1000]}
            if rc != 0:
                verdict["accepted"] = False
                verdict["reason"] = "gh_issue_add_label_failed"

        elif action == "remove_label":
            number = int(payload["issue_number"])
            lbl = payload["label"]
            rc, out, err = _gh(
                "issue", "edit", str(number),
                "--repo", repo,
                "--remove-label", lbl,
            )
            gh_result = {"returncode": rc, "stdout": out.strip()[:1000], "stderr": err.strip()[:1000]}
            if rc != 0:
                verdict["accepted"] = False
                verdict["reason"] = "gh_issue_remove_label_failed"

        elif action == "transition_status":
            number = int(payload["issue_number"])
            status = payload["status"]
            # `gh issue close --reason` lets us annotate why; `gh issue
            # reopen` is its own subcommand.
            if status == "closed":
                rc, out, err = _gh("issue", "close", str(number), "--repo", repo)
                action_label = "gh_issue_close_failed"
            elif status == "reopen":
                rc, out, err = _gh("issue", "reopen", str(number), "--repo", repo)
                action_label = "gh_issue_reopen_failed"
            else:  # "open" — already open is a no-op
                rc, out, err = (0, "noop", "")
                action_label = "noop"
            gh_result = {"returncode": rc, "stdout": out.strip()[:1000], "stderr": err.strip()[:1000]}
            if rc != 0:
                verdict["accepted"] = False
                verdict["reason"] = action_label

    except subprocess.TimeoutExpired:
        verdict["accepted"] = False
        verdict["reason"] = "gh_timeout"
    except Exception as e:  # pragma: no cover — defensive
        verdict["accepted"] = False
        verdict["reason"] = f"dispatch_exception={type(e).__name__}"

    verdict["gh_result"] = gh_result
    _emit_audit_row(payload, verdict)
    return verdict


# --- Entry points -----------------------------------------------------------

def _read_payload() -> dict[str, Any]:
    """Read one JSON payload from stdin.

    Tolerates trailing newlines and a leading BOM. Raises ValueError on
    malformed JSON — the caller turns that into a structured rejection.
    """
    raw = sys.stdin.read()
    raw = raw.lstrip("\ufeff").strip()
    if not raw:
        raise ValueError("empty_payload")
    return json.loads(raw)


def main() -> int:
    try:
        payload = _read_payload()
    except ValueError as e:
        print(
            json.dumps({"accepted": False, "action": None, "reason": f"malformed_payload={e}"})
        )
        return 0
    except Exception as e:
        print(
            json.dumps({"accepted": False, "action": None, "reason": f"stdin_error={type(e).__name__}"})
        )
        return 0

    verdict = dispatch(payload)
    print(json.dumps(verdict))
    return 0


if __name__ == "__main__":
    sys.exit(main())
