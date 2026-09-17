"""
LOOP_CONTRACT_V1 — Machine-validatable schema for the autonomous goal loop.

Layered on top of MACROTURN_CONTRACT_V1 (existing in traficlab-factory).
Each field is required unless marked optional.
"""
from __future__ import annotations
import json
import time
import hashlib
from typing import Optional, List, Dict, Any
from enum import Enum


class LoopState(str, Enum):
    """Loop state machine — explicit, finite, no impossible transitions."""
    INTAKE = "INTAKE"
    SYNCING = "SYNCING"
    PLANNING = "PLANNING"
    DISPATCHING = "DISPATCHING"
    RUNNING = "RUNNING"
    COLLECTING = "COLLECTING"
    VERIFYING = "VERIFYING"
    SYNTHESIZING = "SYNTHESIZING"
    REPLANNING = "REPLANNING"
    WAITING_HARD_STOP = "WAITING_HARD_STOP"
    DONE = "DONE"
    BLOCKED_EXTERNAL = "BLOCKED_EXTERNAL"
    CANCELLED = "CANCELLED"


# Allowed state transitions (whitelist). Anything else fails closed.
ALLOWED_TRANSITIONS = {
    LoopState.INTAKE:        {LoopState.SYNCING, LoopState.CANCELLED},
    LoopState.SYNCING:       {LoopState.PLANNING, LoopState.WAITING_HARD_STOP, LoopState.BLOCKED_EXTERNAL, LoopState.CANCELLED},
    LoopState.PLANNING:      {LoopState.DISPATCHING, LoopState.DONE, LoopState.WAITING_HARD_STOP, LoopState.CANCELLED, LoopState.REPLANNING},
    LoopState.DISPATCHING:   {LoopState.RUNNING, LoopState.WAITING_HARD_STOP, LoopState.BLOCKED_EXTERNAL, LoopState.CANCELLED},
    LoopState.RUNNING:       {LoopState.COLLECTING, LoopState.WAITING_HARD_STOP, LoopState.BLOCKED_EXTERNAL, LoopState.CANCELLED},
    LoopState.COLLECTING:    {LoopState.VERIFYING, LoopState.WAITING_HARD_STOP, LoopState.CANCELLED},
    LoopState.VERIFYING:     {LoopState.SYNTHESIZING, LoopState.REPLANNING, LoopState.WAITING_HARD_STOP, LoopState.CANCELLED},
    LoopState.SYNTHESIZING:  {LoopState.PLANNING, LoopState.REPLANNING, LoopState.DONE, LoopState.WAITING_HARD_STOP, LoopState.CANCELLED},
    LoopState.REPLANNING:    {LoopState.PLANNING, LoopState.CANCELLED, LoopState.WAITING_HARD_STOP},
    LoopState.WAITING_HARD_STOP: {LoopState.PLANNING, LoopState.CANCELLED, LoopState.DISPATCHING, LoopState.RUNNING, LoopState.COLLECTING, LoopState.VERIFYING, LoopState.SYNTHESIZING},
    LoopState.DONE:          set(),  # terminal
    LoopState.BLOCKED_EXTERNAL: set(),  # terminal
    LoopState.CANCELLED:     set(),  # terminal
}


class LoopContractV1:
    """Versioned, machine-validatable loop contract."""

    REQUIRED_FIELDS = [
        "LOOP_ID",
        "GOAL_ID",
        "GOAL_OBJECTIVE",
        "SOURCE_OF_TRUTH",
        "CANONICAL_BASELINE",
        "TRIGGER",
        "CURRENT_ITERATION",
        "CURRENT_GATE",
        "DEPENDENCY_GRAPH",
        "ACTIVE_NODES",
        "ELIGIBLE_NODES",
        "BLOCKED_NODES",
        "ACTIVE_WRITERS",
        "READ_ONLY_WORKERS",
        "RESOURCE_OWNERS",
        "STATE_SNAPSHOT_REF",
        "BRAIN_CONTEXT_REF",
        "LAST_MATERIAL_EVENT",
        "NEXT_SAFE_ACTION",
        "VERIFY_POLICY",
        "STOP_CONDITIONS",
        "ESCALATION_CONDITIONS",
        "CHECKPOINT_POLICY",
        "FINAL_ACCEPTANCE",
    ]

    def __init__(self, **fields):
        missing = [f for f in self.REQUIRED_FIELDS if f not in fields]
        if missing:
            raise ValueError(f"LOOP_CONTRACT_V1 missing required fields: {missing}")
        self.fields = fields
        self.state = LoopState.INTAKE
        self.history = [{"state": self.state.value, "ts": time.time()}]

    @classmethod
    def from_json(cls, j: str) -> "LoopContractV1":
        d = json.loads(j)
        obj = cls(**d)
        if "STATE" in d:
            obj.transition(LoopState(d["STATE"]))
        return obj

    def to_dict(self) -> Dict[str, Any]:
        out = dict(self.fields)
        out["STATE"] = self.state.value
        out["HISTORY"] = self.history
        return out

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)

    def transition(self, new_state: LoopState) -> None:
        if new_state not in ALLOWED_TRANSITIONS[self.state]:
            raise ValueError(
                f"Illegal transition: {self.state.value} -> {new_state.value}. "
                f"Allowed from {self.state.value}: {[s.value for s in ALLOWED_TRANSITIONS[self.state]]}"
            )
        self.state = new_state
        self.history.append({"state": new_state.value, "ts": time.time()})

    def snapshot(self) -> Dict[str, Any]:
        """Return a durable snapshot of the current state (for resume/recovery)."""
        snap = self.to_dict()
        snap["SNAPSHOT_TS"] = time.time()
        snap["SNAPSHOT_SHA"] = hashlib.sha256(
            json.dumps(snap, sort_keys=True, default=str).encode()
        ).hexdigest()
        return snap


class StopCondition(str, Enum):
    """The 8 stop conditions per directive LOOP-ENGINEERING-V1-20260917-01."""
    MERGE_RELEASE_PRODUCTION = "merge_release_production"
    SECRET_TOKEN_PROVIDER_LICENSE = "secret_token_provider_license"
    DESTRUCTIVE_CANONICAL_MUTATION = "destructive_canonical_mutation"
    PUBLIC_NETWORK_SECURITY = "public_network_security"
    PHYSICAL_PAIRING_DEVICE = "physical_pairing_device"
    MATERIAL_PRODUCT_SCIENTIFIC_DECISION = "material_product_scientific_decision"
    EXTERNAL_MISSING_BLOCKER = "external_missing_blocker"
    GOAL_ACCEPTANCE_SATISFIED = "goal_acceptance_satisfied"


# Hard continuation rule per directive
HARD_CONTINUATION_RULE = (
    "IF safe eligible work exists "
    "AND no HUMAN_GO_REAL boundary is reached "
    "AND no resource/ownership collision exists "
    "THEN AUTO_CONTINUE = REQUIRED"
)
