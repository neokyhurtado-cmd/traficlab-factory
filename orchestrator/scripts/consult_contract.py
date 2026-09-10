#!/usr/bin/env python3
"""Typed contract for Hermes -> Astra consultation.

This module is intentionally provider-neutral. It validates the request and
the returned decision so Hermes never treats free-form prose as authorization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DECISIONS = {
    "AUTO_GO",
    "AUTO_REPLAN",
    "NEEDS_MORE_EVIDENCE",
    "BLOCKED_EXTERNAL",
    "HUMAN_GO_REAL",
}

REQUIRED_REQUEST_FIELDS = (
    "project_id",
    "goal_id",
    "current_gate",
    "repository",
    "question",
)

@dataclass(frozen=True)
class ConsultRequest:
    project_id: str
    goal_id: str
    current_gate: str
    repository: str
    question: str
    issue_number: int | None = None
    current_base_sha: str | None = None
    current_head_sha: str | None = None
    evidence_refs: list[str] = field(default_factory=list)
    decisions_already_frozen: list[str] = field(default_factory=list)
    forbidden_scope: list[str] = field(default_factory=list)
    conversation_context: str = ""
    requested_action: str = ""

@dataclass(frozen=True)
class ConsultDecision:
    decision: str
    decision_text: str
    why: str
    allowed_actions: list[str]
    forbidden_actions: list[str]
    tests_required: list[str]
    next_gate: str
    confidence: str = "MEDIUM"

def _text(value: Any, field_name: str, *, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{field_name} is required")
    return value

def _str_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise ValueError(f"{field_name} must be a list[str]")
    return [x.strip() for x in value if x.strip()]

def parse_request(data: dict[str, Any]) -> ConsultRequest:
    if not isinstance(data, dict):
        raise ValueError("request must be a JSON object")
    for name in REQUIRED_REQUEST_FIELDS:
        _text(data.get(name), name, required=True)
    issue_number = data.get("issue_number")
    if issue_number is not None:
        if isinstance(issue_number, bool) or not isinstance(issue_number, int) or issue_number < 1:
            raise ValueError("issue_number must be a positive integer")
    return ConsultRequest(
        project_id=_text(data.get("project_id"), "project_id", required=True),
        goal_id=_text(data.get("goal_id"), "goal_id", required=True),
        current_gate=_text(data.get("current_gate"), "current_gate", required=True),
        repository=_text(data.get("repository"), "repository", required=True),
        question=_text(data.get("question"), "question", required=True),
        issue_number=issue_number,
        current_base_sha=_text(data.get("current_base_sha"), "current_base_sha") or None,
        current_head_sha=_text(data.get("current_head_sha"), "current_head_sha") or None,
        evidence_refs=_str_list(data.get("evidence_refs"), "evidence_refs"),
        decisions_already_frozen=_str_list(data.get("decisions_already_frozen"), "decisions_already_frozen"),
        forbidden_scope=_str_list(data.get("forbidden_scope"), "forbidden_scope"),
        conversation_context=_text(data.get("conversation_context"), "conversation_context"),
        requested_action=_text(data.get("requested_action"), "requested_action"),
    )

def parse_decision(data: dict[str, Any]) -> ConsultDecision:
    if not isinstance(data, dict):
        raise ValueError("decision must be a JSON object")
    decision = _text(data.get("decision"), "decision", required=True).upper()
    if decision not in DECISIONS:
        raise ValueError(f"unsupported decision: {decision}")
    confidence = _text(data.get("confidence"), "confidence").upper() or "MEDIUM"
    if confidence not in {"LOW", "MEDIUM", "HIGH"}:
        raise ValueError("confidence must be LOW|MEDIUM|HIGH")
    return ConsultDecision(
        decision=decision,
        decision_text=_text(data.get("decision_text"), "decision_text", required=True),
        why=_text(data.get("why"), "why", required=True),
        allowed_actions=_str_list(data.get("allowed_actions"), "allowed_actions"),
        forbidden_actions=_str_list(data.get("forbidden_actions"), "forbidden_actions"),
        tests_required=_str_list(data.get("tests_required"), "tests_required"),
        next_gate=_text(data.get("next_gate"), "next_gate", required=True),
        confidence=confidence,
    )

def decision_to_dict(decision: ConsultDecision) -> dict[str, Any]:
    return {
        "schema_version": "ASTRA_CONSULT_DECISION_V1",
        "decision": decision.decision,
        "decision_text": decision.decision_text,
        "why": decision.why,
        "allowed_actions": decision.allowed_actions,
        "forbidden_actions": decision.forbidden_actions,
        "tests_required": decision.tests_required,
        "next_gate": decision.next_gate,
        "confidence": decision.confidence,
    }
