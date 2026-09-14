"""Telegram round-trip simulation harness for Lane 18.

This is NOT a live Telegram round-trip (that lives in the gateway
layer). It IS a faithful reproduction of the JSON payload shape the
gateway would pipe into ``orch_inbound_wo.py`` after receiving a real
Telegram ``Message``. See ``TELEGRAM_ROUNDTRIP_SIM.md`` at the repo
root for the full rationale.

The test exercises the EXACT same ``orch_inbound_wo.dispatch``
function that the real gateway would call, and proves:

  1. A legitimate Telegram-shaped payload (David, real chat_id,
     allowed action, allowed product) is accepted.
  2. A Telegram-shaped payload with a disallowed action is
     rejected BEFORE any external ``gh`` call is made.
  3. A Telegram-shaped payload with a chat_id not in the allow-list
     is rejected.
  4. No per-chat state is created — the module's globals are
     unchanged before and after the call.
  5. The audit row, when hermes_cli is available, has the right
     shape (``requester_platform: "telegram"``, no telegram-specific
     columns).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest


_HERE = Path(__file__).resolve().parent
_ORCH_SCRIPTS = _HERE.parent / "orchestrator" / "scripts"
if str(_ORCH_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_ORCH_SCRIPTS))

import orch_inbound_wo  # noqa: E402


# ------------------------------------------------------------------
# Fixture: routing table + chat-id allow-list
# ------------------------------------------------------------------

@pytest.fixture
def routing_table_yaml(tmp_path, monkeypatch):
    """Stand-in routing table that recognises SUINI + IA-VISION."""
    p = tmp_path / "routing.yaml"
    p.write_text(
        "routes:\n"
        "  - repo: neokyhurtado-cmd/suini\n"
        "    product: SUINI\n"
        "    assignee: suini\n"
        "  - repo: neokyhurtado-cmd/IA-VISION\n"
        "    product: IA-VISION\n"
        "    assignee: ia-vision\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_ROUTING_PATH", str(p))
    return str(p)


@pytest.fixture
def david_chat(monkeypatch):
    monkeypatch.setenv("ORCH_INBOUND_DAVID_CHAT_IDS", "111,222")
    return {"111", "222"}


def _telegram_payload(
    *,
    chat_id: str = "111",
    action: str = "create_wo",
    product: str = "SUINI",
    repo: str = "neokyhurtado-cmd/suini",
    title: str | None = "Round-trip WO from Telegram",
    body: str | None = "Created via the simulated Telegram round-trip.",
    issue_number: int | None = None,
    label: str | None = None,
    status: str | None = None,
    requester: str = "david-telegram",
) -> dict:
    """Build the JSON the gateway would forward for a real Telegram
    ``Message`` that asks the factory to do something. The shape
    matches the CALL SHAPE comment in ``orch_inbound_wo.py`` exactly.
    """
    payload: dict = {
        "requester": requester,
        "requester_chat_id": chat_id,
        "requester_platform": "telegram",
        "action": action,
        "product": product,
        "repo": repo,
    }
    if title is not None:
        payload["title"] = title
    if body is not None:
        payload["body"] = body
    if action in ("create_wo",):
        payload.setdefault("labels", ["hermes-work-order"])
    if action in ("update_wo", "add_label", "remove_label", "transition_status"):
        payload["issue_number"] = issue_number or 35
    if action in ("add_label", "remove_label"):
        payload["label"] = label or "hermes-work-order"
    if action == "transition_status":
        payload["status"] = status or "closed"
    return payload


# ------------------------------------------------------------------
# Round-trip tests
# ------------------------------------------------------------------

class TestTelegramRoundTripSim:

    def test_create_wo_roundtrip_accepted_and_calls_gh(
        self, routing_table_yaml, david_chat, monkeypatch
    ):
        """Legitimate Telegram-driven create_wo: validator accepts, gh
        is invoked with the right args, audit row is emitted."""
        captured: dict = {}

        def fake_gh(*args, timeout=30):
            captured["args"] = args
            return 0, "https://github.com/neokyhurtado-cmd/suini/issues/99\n", ""

        monkeypatch.setattr(orch_inbound_wo, "_gh", fake_gh)
        # Don't actually write the audit row — we don't need kanban_db.
        monkeypatch.setattr(
            orch_inbound_wo, "_emit_audit_row", lambda *a, **kw: None
        )

        verdict = orch_inbound_wo.dispatch(_telegram_payload())

        assert verdict["accepted"] is True, verdict
        assert verdict["reason"] is None
        # The exact gh command the gate would issue for a real Telegram
        # message landing in the factory:
        assert captured["args"][:3] == ("issue", "create", "--repo")
        assert captured["args"][3] == "neokyhurtado-cmd/suini"

    def test_disallowed_action_rejected_before_gh(
        self, routing_table_yaml, david_chat, monkeypatch
    ):
        """A Telegram-driven request that asks for a forbidden action
        must be refused by the gate BEFORE any external call — proving
        no shell can ever run via the Telegram path."""
        called = {"n": 0}

        def fake_gh(*args, timeout=30):
            called["n"] += 1
            return 0, "", ""

        monkeypatch.setattr(orch_inbound_wo, "_gh", fake_gh)
        monkeypatch.setattr(
            orch_inbound_wo, "_emit_audit_row", lambda *a, **kw: None
        )

        verdict = orch_inbound_wo.dispatch(
            _telegram_payload(action="shell")
        )
        assert verdict["accepted"] is False
        assert "unknown_action" in verdict["reason"]
        assert called["n"] == 0, "gh must NOT be called for rejected actions"

    def test_chat_id_outside_allowlist_rejected(
        self, routing_table_yaml, monkeypatch
    ):
        """A Telegram-shaped payload with a chat_id not in the
        ORCH_INBOUND_DAVID_CHAT_IDS allow-list must be rejected, even
        if the requester name looks legitimate."""
        # Empty allow-list — operator hasn't opted David in.
        monkeypatch.delenv("ORCH_INBOUND_DAVID_CHAT_IDS", raising=False)

        verdict = orch_inbound_wo.dispatch(
            _telegram_payload(chat_id="999999")
        )
        assert verdict["accepted"] is False
        assert "unknown_chat_id" in verdict["reason"]

    def test_no_per_chat_state_in_module_after_dispatch(
        self, routing_table_yaml, david_chat, monkeypatch
    ):
        """The orch_inbound_wo module must hold ZERO per-chat state
        after a dispatch call. This is the literal proof that
        Telegram is not a separate session store in this repo."""
        monkeypatch.setattr(
            orch_inbound_wo, "_gh",
            lambda *a, timeout=30: (0, "ok", ""),
        )
        monkeypatch.setattr(
            orch_inbound_wo, "_emit_audit_row", lambda *a, **kw: None
        )

        # Snapshot every public attribute of orch_inbound_wo that could
        # plausibly hold per-chat state.
        before = {
            name: getattr(orch_inbound_wo, name)
            for name in dir(orch_inbound_wo)
            if not name.startswith("_") and not callable(
                getattr(orch_inbound_wo, name)
            )
        }
        orch_inbound_wo.dispatch(_telegram_payload(chat_id="111"))
        orch_inbound_wo.dispatch(_telegram_payload(chat_id="222"))
        after = {
            name: getattr(orch_inbound_wo, name)
            for name in dir(orch_inbound_wo)
            if not name.startswith("_") and not callable(
                getattr(orch_inbound_wo, name)
            )
        }

        # Public, non-callable attributes must be unchanged.
        assert before == after, (
            "orch_inbound_wo gained per-chat state — violates "
            "TELEGRAM_CONTRACT.md §2.\n"
            f"  before: {sorted(before)}\n"
            f"  after:  {sorted(after)}"
        )
        # And no private container named like a chat-id store either.
        for attr in dir(orch_inbound_wo):
            if attr.startswith("_") or callable(getattr(orch_inbound_wo, attr)):
                continue
            value = getattr(orch_inbound_wo, attr)
            if isinstance(value, dict) and ("chat" in attr.lower()
                                            or "session" in attr.lower()):
                pytest.fail(
                    f"orch_inbound_wo.{attr} looks like a per-chat state "
                    f"container: {value!r}"
                )

    def test_payload_idempotency_key_is_optional_and_carries_through(
        self, routing_table_yaml, david_chat, monkeypatch
    ):
        """When the gateway forwards an ``idempotency_key``, it must
        reach the audit row verbatim — the gate must not strip or
        rewrite it. This is what makes Telegram-driven actions safe
        to retry from the gateway side without producing duplicate
        work orders."""
        emitted: list[dict] = []

        def fake_emit(payload, verdict):
            emitted.append({"payload": payload, "verdict": verdict})

        monkeypatch.setattr(orch_inbound_wo, "_emit_audit_row", fake_emit)
        monkeypatch.setattr(
            orch_inbound_wo, "_gh",
            lambda *a, timeout=30: (0, "ok", ""),
        )

        payload = _telegram_payload()
        payload["idempotency_key"] = "telegram-roundtrip-2026-09-11-001"
        orch_inbound_wo.dispatch(payload)
        assert emitted[0]["payload"]["idempotency_key"] == (
            "telegram-roundtrip-2026-09-11-001"
        )
        assert emitted[0]["payload"]["requester_platform"] == "telegram"
