"""Skill Fabric V1 — package init.

V1 SCAFFOLD state (skill-fabric-v1-implant-20260922-01).

Public surface:

    from agent_body.skill_fabric import (
        Mode, SkillEntry,
        validate_entry, load_registry, find_skill,
        route, empty_routing,
        resolve, ConflictResolution,
        build_graph, GraphAdapterNotActive,
    )

No external skill is registered in V1 SCAFFOLD state. Adding candidates
requires the G0 audit + G1-G5 gates per issue #51.
"""
from .registry import (
    ACCEPTED_SPDX_LICENSES,
    Mode,
    SkillEntry,
    find_skill,
    load_registry,
    sha256_text,
    validate_entry,
)
from .router import empty_routing, route
from .conflict import ConflictResolution, resolve
from .graph_adapter import GraphAdapterNotActive, build_graph

__all__ = [
    "ACCEPTED_SPDX_LICENSES",
    "Mode",
    "SkillEntry",
    "find_skill",
    "load_registry",
    "sha256_text",
    "validate_entry",
    "route",
    "empty_routing",
    "ConflictResolution",
    "resolve",
    "GraphAdapterNotActive",
    "build_graph",
]

__version__ = "0.1.0-implant-20260922-01"
