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
from sol_efficiency import ContextCompactor, EvidenceReducer, ObservationPack


class LoopEngine:
    def __init__(
        self,
        contract: LoopContractV1,
        snapshot_path: Optional[str] = None,
        *,
        sol_mode: Optional[str] = None,
        sol_root: Optional[str] = None,
        sol_threshold_bytes: int = 4096,
    ):
        self.contract = contract
        self.snapshot_path = snapshot_path or f".loop_snapshots/{contract.fields['LOOP_ID']}.json"
        os.makedirs(os.path.dirname(self.snapshot_path), exist_ok=True)
        self.iteration = 0
        self.completed_nodes: list[str] = []
        self.failed_nodes: list[str] = []
        self.blocked_nodes: list[str] = []
        self.active_nodes: list[str] = []

        self.sol_mode = (sol_mode or os.getenv("TRAFICLAB_SOL_MODE", "off")).strip().lower()
        if self.sol_mode not in {"off", "shadow", "enforce"}:
            raise ValueError("sol_mode must be one of: off, shadow, enforce")
        self._sol_handles: list[str] = []
        self._sol_metrics = {
            "mode": self.sol_mode,
            "observations_packed": 0,
            "original_bytes": 0,
            "compact_bytes": 0,
            "verified_findings": 0,
        }
        self._sol_pack = None
        self._sol_reducer = None
        self._sol_compactor = None
        if self.sol_mode != "off":
            root = sol_root or os.getenv("TRAFICLAB_SOL_ROOT", ".sol_artifacts")
            self._sol_pack = ObservationPack(
                os.path.join(root, "observations"),
                threshold_bytes=sol_threshold_bytes,
            )
            self._sol_reducer = EvidenceReducer(self._sol_pack)
            self._sol_compactor = ContextCompactor(os.path.join(root, "context"))

    def can_continue(self) -> bool:
        """Hard continuation rule per directive."""
        eligible = self.contract.fields.get("ELIGIBLE_NODES", [])
        blocked = self.contract.fields.get("BLOCKED_NODES", [])
        state = self.contract.state
        if state in {LoopState.DONE, LoopState.BLOCKED_EXTERNAL, LoopState.CANCELLED}:
            return False
        if state == LoopState.WAITING_HARD_STOP:
            return False
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
        snap["SOL_EFFICIENCY"] = dict(self._sol_metrics)
        if self._sol_compactor is not None:
            checkpoint = self._sol_compactor.compact(
                snap, evidence_handles=self._sol_handles
            )
            snap["SOL_CONTEXT_CHECKPOINT"] = checkpoint.to_dict()
        with open(self.snapshot_path, "w") as f:
            json.dump(snap, f, indent=2, default=str)

    def _optimize_evidence(self, result: WorkerResult) -> None:
        if self._sol_pack is None or self._sol_reducer is None:
            return
        optimized: list[str] = []
        for index, entry in enumerate(result.EVIDENCE):
            if not isinstance(entry, str) or not self._sol_pack.should_pack(entry):
                optimized.append(entry)
                continue
            digest = self._sol_reducer.reduce(
                entry, label=f"{result.NODE_ID}:evidence:{index}"
            )
            compact = digest.compact_text()
            self._sol_handles.append(digest.observation.handle)
            self._sol_metrics["observations_packed"] += 1
            self._sol_metrics["original_bytes"] += len(entry.encode("utf-8"))
            self._sol_metrics["compact_bytes"] += len(compact.encode("utf-8"))
            self._sol_metrics["verified_findings"] += sum(
                1 for finding in digest.findings if finding.verified
            )
            optimized.append(compact if self.sol_mode == "enforce" else entry)
        if self.sol_mode == "enforce":
            result.EVIDENCE[:] = optimized

    def recall_evidence(
        self,
        handle: str,
        *,
        start_line: int = 1,
        end_line: Optional[int] = None,
    ) -> str:
        if self._sol_pack is None:
            raise RuntimeError("evidence recall requires shadow or enforce mode")
        return self._sol_pack.recall(
            handle, start_line=start_line, end_line=end_line
        )

    def ingest_worker_result(self, result: WorkerResult) -> None:
        """Update loop state from a worker result. Anti-false-closure rule enforced."""
        result.validate()
        self._optimize_evidence(result)
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
        self.persist_snapshot()

    def classify_stop_condition(self) -> Optional[StopCondition]:
        """Returns the first matching stop condition, or None if AUTO_CONTINUE."""
        if self.contract.state == LoopState.DONE:
            return StopCondition.GOAL_ACCEPTANCE_SATISFIED
        if self.contract.state == LoopState.BLOCKED_EXTERNAL:
            return StopCondition.EXTERNAL_MISSING_BLOCKER
        return None


def make_loop_id(goal_id: str) -> str:
    return f"loop_{goal_id}_{uuid.uuid4().hex[:8]}"
