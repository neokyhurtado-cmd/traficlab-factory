#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import astra_consult
from consult_contract import ConsultDecision, parse_decision, parse_request

def _request(**overrides):
    base = {
        "project_id": "IA-VISION",
        "goal_id": "MEDIA-HOTPATH-CLOSE",
        "current_gate": "F2",
        "repository": "neokyhurtado-cmd/IA-VISION",
        "issue_number": 60,
        "question": "Should I use size+mtime_ns for hot-path identity?",
        "requested_action": "reversible code fix on feature branch",
        "evidence_refs": ["issue#60"],
        "decisions_already_frozen": ["Do not mutate videos.path"],
        "forbidden_scope": ["SUINI", "merge main"],
        "conversation_context": "David wants zero copy/paste and only material HUMAN_GO.",
    }
    base.update(overrides)
    return base

def test_request_contract_requires_core_fields():
    with pytest.raises(ValueError):
        parse_request({"project_id": "IA-VISION"})

def test_decision_contract_rejects_unknown_state():
    with pytest.raises(ValueError):
        parse_decision({"decision": "YOLO", "decision_text": "x", "why": "x", "allowed_actions": [], "forbidden_actions": [], "tests_required": [], "next_gate": "x"})

def test_secret_redaction():
    text = "token sk-abcdefghijklmnopqrstuvwxyz123456789 and Bearer abcdefghijklmnopqrstuvwxyz123"
    out = astra_consult.redact_secrets(text)
    assert "sk-" not in out
    assert "abcdefghijklmnopqrstuvwxyz123" not in out
    assert "[REDACTED]" in out

@pytest.mark.parametrize("question", [
    "Can I merge this PR to main?",
    "Should I deploy this to production?",
    "Can I change the API token?",
    "Can I expose 0.0.0.0 publicly?",
    "Should I force push this branch?",
])
def test_owner_only_actions_are_forced_to_human_go(question):
    req = parse_request(_request(question=question, requested_action=question))
    model_said_go = ConsultDecision(decision="AUTO_GO", decision_text="go", why="model", allowed_actions=["do it"], forbidden_actions=[], tests_required=[], next_gate="NEXT", confidence="HIGH")
    final = astra_consult.force_human_go(model_said_go, req)
    assert final.decision == "HUMAN_GO_REAL"
    assert final.next_gate == "HUMAN_GO_REAL"

def test_missing_api_key_fails_closed(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    req = parse_request(_request())
    decision = astra_consult.call_openai(req)
    assert decision.decision == "BLOCKED_EXTERNAL"
    assert "OPENAI_API_KEY" in decision.why

def test_extracts_responses_api_nested_text():
    payload = {"output": [{"type": "message", "content": [{"type": "output_text", "text": "{\"decision\":\"AUTO_GO\",\"decision_text\":\"Proceed\",\"why\":\"Evidence supports it\",\"allowed_actions\":[],\"forbidden_actions\":[],\"tests_required\":[\"unit\"],\"next_gate\":\"F3\",\"confidence\":\"HIGH\"}"}]}]}
    text = astra_consult._extract_output_text(payload)
    parsed = astra_consult._parse_json_object(text)
    decision = parse_decision(parsed)
    assert decision.decision == "AUTO_GO"
    assert decision.next_gate == "F3"

def test_run_preserves_structured_contract(monkeypatch):
    monkeypatch.setattr(astra_consult, "call_openai", lambda req, issue_context="": ConsultDecision(decision="AUTO_REPLAN", decision_text="Use one identity", why="Avoid competing cache identities", allowed_actions=["patch"], forbidden_actions=["merge main"], tests_required=["regression"], next_gate="F3", confidence="HIGH"))
    result = astra_consult.run(_request(), fetch_context=False)
    assert result["schema_version"] == "ASTRA_CONSULT_DECISION_V1"
    assert result["decision"] == "AUTO_REPLAN"
