"""Hermes plugin: expose Astra consultation as a first-class agent tool."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

POLICY = """ZERO-HANDOFF CONSULTATION POLICY
Before asking David a technical question, pausing for a reversible technical ambiguity,
or choosing between materially different implementation approaches that are not already
resolved by evidence, call the `ask_astra` tool first.

Do NOT call Astra for facts you can verify directly from the repo/runtime. Gather evidence
first, then consult when judgment is still needed.

Follow the returned decision:
- AUTO_GO: continue.
- AUTO_REPLAN: adopt the plan and continue.
- NEEDS_MORE_EVIDENCE: collect only the requested evidence and consult again.
- BLOCKED_EXTERNAL: stop only the blocked dependency; do not fabricate success.
- HUMAN_GO_REAL: surface one concise owner decision to David.

Never reinterpret prose as authorization. GitHub remains durable truth. Product ownership,
forbidden scope and deterministic HUMAN_GO gates remain binding.
"""

TOOL_SCHEMA = {
    "name": "ask_astra",
    "description": (
        "Mandatory zero-handoff consultant for unresolved technical judgment. "
        "Use before asking David an ordinary technical question or stopping on a reversible "
        "ambiguity. Supply current goal/gate/repo/SHAs/evidence and the exact question."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "project_id": {"type": "string"},
            "goal_id": {"type": "string"},
            "current_gate": {"type": "string"},
            "repository": {"type": "string", "description": "GitHub owner/name"},
            "issue_number": {"type": "integer", "minimum": 1},
            "current_base_sha": {"type": "string"},
            "current_head_sha": {"type": "string"},
            "question": {"type": "string"},
            "requested_action": {"type": "string"},
            "evidence_refs": {"type": "array", "items": {"type": "string"}},
            "decisions_already_frozen": {"type": "array", "items": {"type": "string"}},
            "forbidden_scope": {"type": "array", "items": {"type": "string"}},
            "conversation_context": {
                "type": "string",
                "description": "Compact owner/goal context relevant to this decision only",
            },
        },
        "required": ["project_id", "goal_id", "current_gate", "repository", "question"],
    },
}

def _script_path() -> Path:
    override = os.environ.get("ASTRA_CONSULT_SCRIPT", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".hermes" / "profiles" / "orchestrator" / "scripts" / "astra_consult.py"

def _blocked(reason: str) -> str:
    return json.dumps({
        "schema_version": "ASTRA_CONSULT_DECISION_V1",
        "decision": "BLOCKED_EXTERNAL",
        "decision_text": "Astra consultant bridge is unavailable.",
        "why": reason,
        "allowed_actions": ["Repair/activate the consultant bridge or continue only with deterministic evidence-backed gates"],
        "forbidden_actions": ["Ask David an ordinary technical question merely because Astra is unavailable", "Fabricate an Astra decision"],
        "tests_required": [],
        "next_gate": "ASTRA_BRIDGE_RECOVERY",
        "confidence": "HIGH",
    })

def handle_ask_astra(params, **kwargs):
    del kwargs
    if not isinstance(params, dict):
        return _blocked("ask_astra parameters were not a JSON object")
    script = _script_path()
    if not script.is_file():
        return _blocked(f"ASTRA_CONSULT_SCRIPT_NOT_FOUND: {script}")
    cmd = [sys.executable, str(script)]
    if params.get("issue_number"):
        cmd.append("--post")
    try:
        proc = subprocess.run(
            cmd,
            input=json.dumps(params, ensure_ascii=False),
            capture_output=True,
            text=True,
            timeout=150,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return _blocked(f"ASTRA_CONSULT_EXEC_FAILED: {type(exc).__name__}")
    stdout = (proc.stdout or "").strip()
    if not stdout:
        return _blocked(f"ASTRA_CONSULT_EMPTY_RESULT: exit={proc.returncode}")
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        return _blocked("ASTRA_CONSULT_INVALID_JSON")
    if not isinstance(parsed, dict) or parsed.get("schema_version") != "ASTRA_CONSULT_DECISION_V1":
        return _blocked("ASTRA_CONSULT_INVALID_ENVELOPE")
    return json.dumps(parsed, ensure_ascii=False)

def register(ctx):
    ctx.register_tool(
        name="ask_astra",
        toolset="astra_consult",
        schema=TOOL_SCHEMA,
        handler=handle_ask_astra,
    )
    ctx.register_system_prompt_section(
        "astra-consult.zero-handoff-policy",
        POLICY,
        position="after_memory",
        max_chars=3000,
    )
