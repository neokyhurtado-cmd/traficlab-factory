"""A2A v1.0 transport bridge for TrafficLab Factory.

This package is transport-only. It never owns scheduling, protected gates, or
product promotion. All decisions remain advisory and non-authoritative.
"""

from .bridge import FactoryA2ABridge
from .card import agent_card_document
from .contracts import BRIDGE_SCHEMA, PROTOCOL_VERSION, BridgeResult, resolve_mode

__all__ = [
    "BRIDGE_SCHEMA",
    "PROTOCOL_VERSION",
    "BridgeResult",
    "FactoryA2ABridge",
    "agent_card_document",
    "resolve_mode",
]
