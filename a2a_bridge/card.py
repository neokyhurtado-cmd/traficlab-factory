from __future__ import annotations

from typing import Any

from .contracts import PROTOCOL_VERSION


def _endpoint(public_url: str) -> str:
    return public_url.rstrip("/") + "/a2a"


def agent_card_document(public_url: str) -> dict[str, Any]:
    """SDK-free representation used for contract tests and documentation."""
    description = (
        "TrafficLab Factory advisory bridge. Accepts bounded task state and "
        "returns JEV shadow evidence. It cannot execute, merge, promote, delete, "
        "or cross owner gates."
    )
    return {
        "name": "TrafficLab Factory JEV Shadow",
        "description": description,
        "version": "1.0.0",
        "supportedInterfaces": [
            {
                "protocolBinding": "JSONRPC",
                "url": _endpoint(public_url),
                "protocolVersion": PROTOCOL_VERSION,
            }
        ],
        "capabilities": {"streaming": True},
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": [
            {
                "id": "jev_shadow_audit",
                "name": "JEV shadow audit",
                "description": (
                    "Evaluate routing, blockers, review need, continuation and risk "
                    "without controlling execution."
                ),
                "inputModes": ["text/plain", "application/json"],
                "outputModes": ["application/json"],
                "tags": ["traficlab", "jev", "audit", "shadow", "read-only"],
                "examples": [
                    '{"task_id":"audit-1","goal":"audit IA-VISION","action":"READ_ONLY"}'
                ],
            }
        ],
    }


def build_sdk_agent_card(public_url: str):
    """Build the official A2A SDK AgentCard lazily.

    Keeping imports lazy means the factory's existing runtime remains unchanged
    unless the optional `a2a` extra is explicitly installed.
    """
    try:
        from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
    except ImportError as exc:  # pragma: no cover - exercised in deployment
        raise RuntimeError(
            'A2A runtime dependencies are not installed. Install with: pip install -e ".[a2a]"'
        ) from exc

    doc = agent_card_document(public_url)
    skill_doc = doc["skills"][0]
    return AgentCard(
        name=doc["name"],
        description=doc["description"],
        version=doc["version"],
        default_input_modes=doc["defaultInputModes"],
        default_output_modes=doc["defaultOutputModes"],
        capabilities=AgentCapabilities(streaming=True),
        supported_interfaces=[
            AgentInterface(
                protocol_binding="JSONRPC",
                url=_endpoint(public_url),
                protocol_version=PROTOCOL_VERSION,
            )
        ],
        skills=[
            AgentSkill(
                id=skill_doc["id"],
                name=skill_doc["name"],
                description=skill_doc["description"],
                input_modes=skill_doc["inputModes"],
                output_modes=skill_doc["outputModes"],
                tags=skill_doc["tags"],
                examples=skill_doc["examples"],
            )
        ],
    )
