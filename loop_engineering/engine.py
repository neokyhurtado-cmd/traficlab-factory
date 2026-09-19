"""
Loop engine — drives the LoopState machine through allowed transitions,
dispatches workers via the existing orchestrator primitives, and emits
durable snapshots for resume/recovery.

This is the V0 LOOP_ENGINEERING_V1 engine. It does NOT replace the existing
orchestrator — it composes with it.
"""
from __future__ import annotations
import json
import os
import time
import uuid
import hashlib
from typing import Optional, Callable, Dict, Any

from .contracts.loop_contract import (
    LoopContractV1, LoopState, ALLOWED_TRANSITIONS, StopCondition, HARD_CONTINUATION_RULE
)
from .contracts.worker_result import WorkerResult, WorkerResultStatus, ANTI_FALSE_CLOSURE_RULE


class LoopEngine:
    def __init__(self, contract: LoopContractV1, snapshot_path: Optional[str] = None):
        self.contract = contract
        self.snapshot_path = snapshot_path or f".loop_snapshots/{contract.fields['LOOP_ID']}.json"
        os.makedirs(os.path.dirname(self.snapshot_path), exist_ok=True)
        self.iteration = 0
        self.completed_nodes: list[str] = []
        self.failed_nodes: list[str] = []
        self.blocked_nodes: list[str] = []
        self.active_nodes: list[str] = []

    def can_continue(self) -> bool:
        """Hard continuation rule per directive."""
        eligible = self.contract.fields.get("ELIGIBLE_NODES", [])
        blocked = self.contract.fields.get("BLOCKED_NODES", [])
        state = self.contract.state
        if state in {LoopState.DONE, LoopState.BLOCKED_EXTERNAL, LoopState.CANCELLED}:
            return False
        # If state is WAITING_HARD_STOP, must wait for owner
        if state == LoopState.WAITING_HARD_STOP:
            return False
        # If eligible work exists and no hard-stop is firing, continue
        return len(eligible) > 0 and len(blocked) == 0

    def transition(self, new_state: LoopState) -> None:
        self.contract.transition(new_state)
        self.persist_snapshot()

    def persist_snapshot(self) -> None:
        snap = self.contract.snapshot()
        snap["COMPLETED_NODES"] = self.completed_nodes
        snap["FAILED_NODES"] = self.failed_nodes
        snap["BLOCKED_NODES"] = self.blocked_nodes
        snap["ACTIVE_NODES"] = self.active_nodes
        snap["ITERATION"] = self.iteration
        with open(self.snapshot_path, "w") as f:
            json.dump(snap, f, indent=2, default=str)

    def ingest_worker_result(self, result: WorkerResult) -> None:
        """Update loop state from a worker result. Anti-false-closure rule enforced."""
        # Validate the result first
        result.validate()
        if result.RESULT == WorkerResultStatus.PASS.value:
            if result.NODE_ID not in self.completed_nodes:
                self.completed_nodes.append(result.NODE_ID)
            if result.NODE_ID in self.active_nodes:
                self.active_nodes.remove(result.NODE_ID)
        elif result.RESULT == WorkerResultStatus.FAIL.value:
            if result.NODE_ID not in self.failed_nodes:
                self.failed_nodes.append(result.NODE_ID)
            if result.NODE_ID in self.active_nodes:
                self.active_nodes.remove(result.NODE_ID)
        elif result.RESULT == WorkerResultStatus.BLOCKED.value:
            if result.NODE_ID not in self.blocked_nodes:
                self.blocked_nodes.append(result.NODE_ID)
            if result.NODE_ID in self.active_nodes:
                self.active_nodes.remove(result.NODE_ID)
        # NOT_PROVEN: stays active, no progress, evidence gathering needed
        self.persist_snapshot()

    def classify_stop_condition(self) -> Optional[StopCondition]:
        """Returns the first matching stop condition, or None if AUTO_CONTINUE."""
        # Check goal acceptance
        if self.contract.state == LoopState.DONE:
            return StopCondition.GOAL_ACCEPTANCE_SATISFIED
        # Check blocked
        if self.contract.state == LoopState.BLOCKED_EXTERNAL:
            return StopCondition.EXTERNAL_MISSING_BLOCKER
        # Other stop conditions require external signaling — return None here
        # so the engine knows to continue.
        return None


def make_loop_id(goal_id: str) -> str:
    return f"loop_{goal_id}_{uuid.uuid4().hex[:8]}"
