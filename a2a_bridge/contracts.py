from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

BRIDGE_SCHEMA = "traficlab_a2a_bridge/v1"
PROTOCOL_VERSION = "1.0"
_ALLOWED_MODES = frozenset({"off", "shadow"})


def resolve_mode(value: str | None = None) -> str:
    """Resolve A2A mode.

    Deliberately supports only OFF and SHADOW. There is no ENFORCE transport
    mode: A2A may carry advisory tasks but may never gain execution authority.
    """
    mode = (value or os.getenv("TRAFICLAB_A2A_MODE", "off")).strip().lower()
    if mode not in _ALLOWED_MODES:
        raise ValueError("TRAFICLAB_A2A_MODE must be one of: off, shadow")
    return mode


@dataclass(frozen=True)
class BridgeResult:
    schema: str = BRIDGE_SCHEMA
    protocol_version: str = PROTOCOL_VERSION
    status: str = "DISABLED"
    mode: str = "off"
    advisory_only: bool = True
    may_control_execution: bool = False
    task_id: str = ""
    request_sha256: str = ""
    decision: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
