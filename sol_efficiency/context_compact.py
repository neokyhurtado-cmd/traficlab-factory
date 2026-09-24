"""Semantic-boundary context checkpoints for long-running loops."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class ContextCheckpoint:
    schema: str
    loop_id: str
    goal_id: str
    state: str
    current_gate: str
    canonical_baseline: str
    completed_nodes: tuple[str, ...]
    failed_nodes: tuple[str, ...]
    blocked_nodes: tuple[str, ...]
    active_nodes: tuple[str, ...]
    last_material_event: str
    next_safe_action: str
    evidence_handles: tuple[str, ...] = field(default_factory=tuple)
    source_snapshot_sha: str = ""
    created_at: int = field(default_factory=lambda: int(time.time()))
    checkpoint_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ContextCompactor:
    """Persist only the live state needed to resume reasoning."""

    def __init__(self, root: str | os.PathLike[str] = ".sol_artifacts/context") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, path)
        finally:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass

    def compact(
        self,
        snapshot: Mapping[str, Any],
        *,
        evidence_handles: Iterable[str] = (),
    ) -> ContextCheckpoint:
        base = {
            "schema": "SOL_CONTEXT_CHECKPOINT_V1",
            "loop_id": str(snapshot.get("LOOP_ID", "")),
            "goal_id": str(snapshot.get("GOAL_ID", "")),
            "state": str(snapshot.get("STATE", "")),
            "current_gate": str(snapshot.get("CURRENT_GATE", "")),
            "canonical_baseline": str(snapshot.get("CANONICAL_BASELINE", "")),
            "completed_nodes": tuple(snapshot.get("COMPLETED_NODES", ())),
            "failed_nodes": tuple(snapshot.get("FAILED_NODES", ())),
            "blocked_nodes": tuple(snapshot.get("BLOCKED_NODES", ())),
            "active_nodes": tuple(snapshot.get("ACTIVE_NODES", ())),
            "last_material_event": str(snapshot.get("LAST_MATERIAL_EVENT", "")),
            "next_safe_action": str(snapshot.get("NEXT_SAFE_ACTION", "")),
            "evidence_handles": tuple(dict.fromkeys(evidence_handles)),
            "source_snapshot_sha": str(snapshot.get("SNAPSHOT_SHA", "")),
            "created_at": int(time.time()),
        }
        canonical = json.dumps(base, sort_keys=True, separators=(",", ":"), default=str)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        checkpoint = ContextCheckpoint(**base, checkpoint_sha256=digest)
        path = self.root / f"{checkpoint.loop_id or 'unknown'}.json"
        self._atomic_write(
            path,
            json.dumps(checkpoint.to_dict(), sort_keys=True, indent=2, default=str).encode("utf-8"),
        )
        return checkpoint
