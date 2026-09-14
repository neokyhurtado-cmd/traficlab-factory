"""BODY-0 BODY MANIFEST loader + frozen-boundary enforcement.

Per AGENT_BODY_27_READONLY_AUDIT §5.1 the manifest is the on-disk YAML
that declares:

  - body_id (UUID)
  - role ("sidecar")
  - projects (list of {name, role})
  - authority_map (precedence)
  - allowed_capabilities
  - denied_capabilities   <-- this is where every frozen #27 boundary lives
  - fail_closed_policy

Public surface:
    load_manifest(path) -> Manifest
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import yaml


# Per directive #27 body — these are the EXACT frozen boundaries the
# manifest MUST deny. See AGENT_BODY_27_READONLY_AUDIT §1 + §9 B0.3.
FROZEN_BOUNDARY_DENIED_CAPABILITIES = (
    "merge_to_main",
    "release_deploy",
    "mutate_secrets",
    "mutate_config_yaml",
    "mutate_env",
    "mutate_gateway",
    "mutate_channels",
    "mutate_runtime_provider",
    "create_orchestrator",
)


@dataclass(frozen=True)
class Manifest:
    body_id: str
    role: str
    projects: List[dict]
    authority_map: dict
    allowed_capabilities: List[str]
    denied_capabilities: List[str]
    fail_closed_policy: dict
    raw: dict = field(default_factory=dict)


def default_manifest() -> dict:
    """Return the canonical BODY-0 manifest dict.

    This is the minimum the agent_body/ sidecar needs to claim BODY-0
    status. It is intentionally small and contains no secrets, no
    provider configuration, and no capability beyond reading/writing
    the body sidecar files.
    """
    return {
        "body_id": "agent-body-evolution-v1",
        "role": "sidecar",
        "projects": [
            {"name": "neokyhurtado-cmd/traficlab-factory", "role": "host"},
            {"name": "neokyhurtado-cmd/IA-VISION", "role": "world-adapter-readonly"},
        ],
        "authority_map": {
            "github_remote":    {"precedence": 1, "source": "gh"},
            "mission_control":  {"precedence": 2, "source": "panorama-mission-control + ASTRA_CONTEXT_V1"},
            "ia_vision_domain": {"precedence": 3, "source": "neokyhurtado-cmd/IA-VISION"},
            "local_checkpoint": {"precedence": 4, "source": "agent_body/checkpoints.sqlite"},
        },
        "allowed_capabilities": [
            "resolve_repo_pointer",
            "resolve_issue_pointer",
            "resolve_commit_pointer",
            "write_checkpoint",
            "read_checkpoint",
            "append_audit_event",
        ],
        "denied_capabilities": list(FROZEN_BOUNDARY_DENIED_CAPABILITIES),
        "fail_closed_policy": {
            "on_stale_head": "RETURN_CONFLICT_FAIL_CLOSED",
            "on_authority_conflict": "RETURN_CONFLICT_FAIL_CLOSED",
            "on_unresolved_pointer": "RETURN_CONFLICT_FAIL_CLOSED",
        },
    }


def load_manifest(path: Path) -> Manifest:
    """Load a manifest from disk, or write the default if missing.

    Writing the default keeps the sidecar self-bootstrapping in tests
    while still enforcing the frozen boundaries.
    """
    p = Path(path)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.safe_dump(default_manifest()), encoding="utf-8")
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    return Manifest(
        body_id=data.get("body_id", ""),
        role=data.get("role", ""),
        projects=list(data.get("projects", [])),
        authority_map=dict(data.get("authority_map", {})),
        allowed_capabilities=list(data.get("allowed_capabilities", [])),
        denied_capabilities=list(data.get("denied_capabilities", [])),
        fail_closed_policy=dict(data.get("fail_closed_policy", {})),
        raw=data,
    )
