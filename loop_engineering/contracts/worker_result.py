"""
Minimum worker result contract — every worker MUST return this structured shape,
not just prose.
"""
from __future__ import annotations
import json
import time
from typing import Optional, List
from enum import Enum
from dataclasses import dataclass, field, asdict


class WorkerResultStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_PROVEN = "NOT_PROVEN"
    BLOCKED = "BLOCKED"


@dataclass
class WorkerResult:
    NODE_ID: str
    ROLE: str
    INPUT_BASELINE: str
    CLAIM: str
    ACTION_TAKEN: str
    ARTIFACTS: List[str] = field(default_factory=list)
    TESTS: List[str] = field(default_factory=list)
    EVIDENCE: List[str] = field(default_factory=list)
    RESULT: str = WorkerResultStatus.NOT_PROVEN.value
    BLOCKER: Optional[str] = None
    NEXT_RECOMMENDATION: str = ""
    HEAD_BEFORE: Optional[str] = None
    HEAD_AFTER: Optional[str] = None
    TS: float = field(default_factory=time.time)

    def to_dict(self):
        return asdict(self)

    def to_json(self):
        return json.dumps(self.to_dict(), indent=2, default=str)

    def validate(self):
        required = ["NODE_ID","ROLE","INPUT_BASELINE","CLAIM","ACTION_TAKEN","RESULT"]
        for r in required:
            if not getattr(self, r):
                raise ValueError(f"WorkerResult missing required field: {r}")
        if self.RESULT not in WorkerResultStatus.__members__.values():
            raise ValueError(f"Invalid RESULT: {self.RESULT}")
        if self.RESULT == WorkerResultStatus.PASS.value and not self.EVIDENCE:
            raise ValueError("PASS requires at least one EVIDENCE entry (anti-false-closure)")
        return True


# Worker self-declaration rule: PASS requires evidence. No evidence = NOT_PROVEN, never PASS.
ANTI_FALSE_CLOSURE_RULE = (
    "PASS requires EVIDENCE. "
    "If no evidence, RESULT must be NOT_PROVEN, never PASS. "
    "If evidence shows the goal is impossible, RESULT must be BLOCKED."
)
