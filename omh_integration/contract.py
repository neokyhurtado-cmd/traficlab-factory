"""OMH integration boundary for TraficLab Factory.

Oh My Hermes is an optional operating layer inside Hermes Control Room.
It never becomes the durable authority for transport, scheduling, worktrees,
project memory, product state or protected human gates.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

OMH_VERSION = "2.0.3"
OMH_REF = "47ab4e27682337c031e08b73ae6c1a42eb69b7f7"
OMH_WHEEL_SHA256 = "8b0eccddb0cfe38364881b0f5b3e61f8eb13cc0d761519b73958e356e87f754f"

CANONICAL_AUTHORITIES = {
    "human_front_door": "HERMES_CONTROL_ROOM_IN_ORCA",
    "worktree_owner": "ORCA",
    "directive_wake_owner": "NEXO_GITHUB_WATCHER",
    "transport_owner": "EXISTING_SINGLE_HERMES_GATEWAY",
    "execution_truth": "GITHUB",
    "knowledge_authority": "OBSIDIAN_PANORAMA",
    "product_state": "TRAFFICLAB_CONTROL",
    "independent_critic": "JUPITER",
}

FORBIDDEN_OMH_OWNERSHIP = {
    "worktree_owner",
    "directive_wake_owner",
    "transport_owner",
    "execution_truth",
    "knowledge_authority",
    "product_state",
    "independent_critic",
}

OMH_EXECUTION_STATES = {
    "running",
    "progress_stalled",
    "awaiting_input",
    "permission_blocked",
    "account_limit",
    "data_missing",
    "failed",
    "verified",
}


@dataclass(frozen=True)
class OmhUnitObservation:
    state: str
    fresh_evidence: bool = False
    result_record_present: bool = False
    validated_result: bool = False
    reason: str | None = None


def map_omh_state(obs: OmhUnitObservation) -> str:
    """Map OMH execution state to factory evidence semantics."""
    if obs.state not in OMH_EXECUTION_STATES:
        return "NOT_PROVEN"

    if obs.state == "running":
        return "RUNNING_CONFIRMED" if obs.fresh_evidence else "PROGRESS_STALLED"
    if obs.state == "progress_stalled":
        return "PROGRESS_STALLED"
    if obs.state in {"awaiting_input", "permission_blocked", "data_missing"}:
        return "BLOCKED"
    if obs.state == "account_limit":
        return "BLOCKED_EXTERNAL"
    if obs.state == "failed":
        return "FAIL"
    if obs.state == "verified":
        if obs.result_record_present and obs.validated_result:
            return "PASS"
        return "NOT_PROVEN"
    return "NOT_PROVEN"


def authority_violations(candidate: Mapping[str, str]) -> list[str]:
    """Return canonical authority collisions introduced by a candidate config."""
    violations: list[str] = []
    for key, expected in CANONICAL_AUTHORITIES.items():
        actual = candidate.get(key, expected)
        if key in FORBIDDEN_OMH_OWNERSHIP and actual != expected:
            violations.append(f"{key}: expected={expected} actual={actual}")
    return violations


@dataclass
class CanaryObservation:
    omh_ref: str
    doctor_ok: bool
    hermes_smoke_ok: bool
    global_hermes_config_unchanged: bool
    new_scheduler: bool = False
    new_listener: bool = False
    transport_owner_mutated: bool = False
    canonical_db_writes: int = 0
    source_media_writes: int = 0
    worktree_owner: str = "ORCA"
    knowledge_authority: str = "OBSIDIAN_PANORAMA"
    directive_wake_owner: str = "NEXO_GITHUB_WATCHER"
    independent_critic: str = "JUPITER"
    rollback_ready: bool = True
    worker_states: list[OmhUnitObservation] = field(default_factory=list)


def evaluate_canary(obs: CanaryObservation) -> dict[str, Any]:
    """Fail-closed compatibility verdict for live Control Room adoption."""
    findings: list[str] = []

    if obs.omh_ref != OMH_REF:
        findings.append("OMH_REF_MISMATCH")
    if not obs.doctor_ok:
        findings.append("OMH_DOCTOR_FAIL")
    if not obs.hermes_smoke_ok:
        findings.append("HERMES_SMOKE_FAIL")
    if not obs.global_hermes_config_unchanged:
        findings.append("GLOBAL_HERMES_CONFIG_MUTATED")
    if obs.new_scheduler:
        findings.append("SECOND_SCHEDULER_FORBIDDEN")
    if obs.new_listener:
        findings.append("NEW_LISTENER_FORBIDDEN")
    if obs.transport_owner_mutated:
        findings.append("TRANSPORT_OWNER_MUTATED")
    if obs.canonical_db_writes:
        findings.append("CANONICAL_DB_WRITE_FORBIDDEN")
    if obs.source_media_writes:
        findings.append("SOURCE_MEDIA_WRITE_FORBIDDEN")
    if obs.worktree_owner != "ORCA":
        findings.append("WORKTREE_OWNER_COLLISION")
    if obs.knowledge_authority != "OBSIDIAN_PANORAMA":
        findings.append("MEMORY_AUTHORITY_COLLISION")
    if obs.directive_wake_owner != "NEXO_GITHUB_WATCHER":
        findings.append("DIRECTIVE_WAKE_COLLISION")
    if obs.independent_critic != "JUPITER":
        findings.append("JUPITER_INDEPENDENCE_LOST")
    if not obs.rollback_ready:
        findings.append("ROLLBACK_NOT_READY")

    mapped = [map_omh_state(x) for x in obs.worker_states]
    if obs.worker_states and not any(x == "PASS" for x in mapped):
        findings.append("NO_VERIFIED_WORKER_RESULT")

    return {
        "verdict": "PASS" if not findings else "FAIL",
        "findings": findings,
        "worker_states": mapped,
        "omh_version": OMH_VERSION,
        "omh_ref": obs.omh_ref,
    }
