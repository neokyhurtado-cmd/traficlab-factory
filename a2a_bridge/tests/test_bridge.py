from __future__ import annotations

from a2a_bridge.bridge import FactoryA2ABridge, parse_a2a_text
from a2a_bridge.card import agent_card_document
from a2a_bridge.contracts import resolve_mode
from a2a_bridge.server import validate_bind_policy
from jev_shadow.provider import ProviderResult


class FakeProvider:
    def evaluate(self, *, state, questions):
        return ProviderResult(
            "OK",
            {
                "route": {"choice": "review", "confidence": 0.9},
                "needs_review": {"noul": 0.8},
                "blocker": {"choice": "none", "confidence": 0.9},
                "continuation": {"choice": "review", "confidence": 0.9},
                "risk": {"score": 1.0},
            },
            {"model": "jev-test"},
        )


def test_default_mode_is_off(monkeypatch):
    monkeypatch.delenv("TRAFICLAB_A2A_MODE", raising=False)
    assert resolve_mode() == "off"
    result = FactoryA2ABridge(provider=FakeProvider()).handle({"task_id": "t1"})
    assert result.status == "DISABLED"
    assert result.may_control_execution is False


def test_shadow_is_advisory_only():
    result = FactoryA2ABridge(mode="shadow", provider=FakeProvider()).handle(
        {
            "task_id": "t2",
            "goal": "audit IA-VISION",
            "action": "READ_ONLY",
            "protected_flags": ["merge_main"],
        }
    )
    assert result.mode == "shadow"
    assert result.status == "OK"
    assert result.advisory_only is True
    assert result.may_control_execution is False
    assert result.decision["hard_gate_override"] is True
    assert result.decision["may_control_execution"] is False


def test_enforce_mode_does_not_exist():
    try:
        resolve_mode("enforce")
    except ValueError as exc:
        assert "off, shadow" in str(exc)
    else:
        raise AssertionError("enforce must not be accepted")


def test_secret_like_arbitrary_fields_do_not_affect_digest():
    bridge = FactoryA2ABridge(mode="shadow", provider=FakeProvider())
    a = bridge.handle({"task_id": "t3", "goal": "audit", "api_key": "SECRET"})
    b = bridge.handle({"task_id": "t3", "goal": "audit", "api_key": "DIFFERENT"})
    assert a.request_sha256 == b.request_sha256


def test_plain_text_becomes_bounded_goal():
    payload = parse_a2a_text("audit the current branch")
    assert payload["goal"] == "audit the current branch"
    assert payload["action"] == "A2A_ADVISORY_REQUEST"


def test_json_payload_is_accepted():
    payload = parse_a2a_text('{"task_id":"abc","action":"READ_ONLY"}')
    assert payload == {"task_id": "abc", "action": "READ_ONLY"}


def test_agent_card_targets_v1_and_shadow_skill():
    card = agent_card_document("http://127.0.0.1:8787")
    interface = card["supportedInterfaces"][0]
    assert interface["protocolVersion"] == "1.0"
    assert interface["protocolBinding"] == "JSONRPC"
    assert card["skills"][0]["id"] == "jev_shadow_audit"
    assert "shadow" in card["skills"][0]["tags"]


def test_non_loopback_bind_requires_explicit_opt_in():
    validate_bind_policy("127.0.0.1")
    try:
        validate_bind_policy("0.0.0.0")
    except RuntimeError as exc:
        assert "Refusing non-loopback" in str(exc)
    else:
        raise AssertionError("remote bind must require explicit opt-in")
