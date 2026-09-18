from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

MODEL_ID = "typesafe-ai/jev"
SCHEMA = "traficlab_jev_shadow/v1"

_ALLOWED_FIELDS = {
    "task_id",
    "goal",
    "repository",
    "branch",
    "action",
    "changed_files_count",
    "tests_status",
    "ci_status",
    "blocker_summary",
    "reversible",
    "last_result",
    "reviewer_status",
    "retry_count",
    "protected_flags",
}

PROTECTED_FLAGS = {
    "merge_main",
    "destructive_mutation",
    "canonical_db_write",
    "source_media_write",
    "secrets_or_credentials",
    "provider_or_license_change",
    "payment_or_spend",
    "production_promotion",
    "irreversible_external_action",
}


@dataclass(frozen=True)
class TaskSnapshot:
    task_id: str = ""
    goal: str = ""
    repository: str = ""
    branch: str = ""
    action: str = ""
    changed_files_count: int = 0
    tests_status: str = "UNKNOWN"
    ci_status: str = "UNKNOWN"
    blocker_summary: str = ""
    reversible: bool = True
    last_result: str = ""
    reviewer_status: str = "UNKNOWN"
    retry_count: int = 0
    protected_flags: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "TaskSnapshot":
        filtered = {k: raw[k] for k in _ALLOWED_FIELDS if k in raw}
        flags = tuple(
            sorted(
                {
                    str(flag)
                    for flag in filtered.get("protected_flags", ())
                    if str(flag) in PROTECTED_FLAGS
                }
            )
        )
        return cls(
            task_id=str(filtered.get("task_id", ""))[:200],
            goal=str(filtered.get("goal", ""))[:2000],
            repository=str(filtered.get("repository", ""))[:300],
            branch=str(filtered.get("branch", ""))[:300],
            action=str(filtered.get("action", ""))[:120],
            changed_files_count=max(0, int(filtered.get("changed_files_count", 0) or 0)),
            tests_status=str(filtered.get("tests_status", "UNKNOWN"))[:120],
            ci_status=str(filtered.get("ci_status", "UNKNOWN"))[:120],
            blocker_summary=str(filtered.get("blocker_summary", ""))[:1000],
            reversible=bool(filtered.get("reversible", True)),
            last_result=str(filtered.get("last_result", ""))[:1000],
            reviewer_status=str(filtered.get("reviewer_status", "UNKNOWN"))[:120],
            retry_count=max(0, int(filtered.get("retry_count", 0) or 0)),
            protected_flags=flags,
        )

    def as_state(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ShadowDecision:
    schema: str
    model: str
    provider_status: str
    route: str | None
    route_confidence: float | None
    needs_review_probability: float | None
    blocker: str | None
    blocker_confidence: float | None
    continuation: str | None
    continuation_confidence: float | None
    risk_score: float | None
    hard_gate_override: bool
    may_control_execution: bool
    protected_flags: tuple[str, ...]
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def jev_questions() -> dict[str, dict[str, Any]]:
    """Typed questions sent together in one Jev evaluation."""
    return {
        "route": {
            "type": "choice",
            "instructions": "Which work lane best fits the current task state?",
            "criteria": {
                "code": "Implementation, patching, tests, debugging or software changes.",
                "research": "Investigation, documentation lookup, comparison or evidence gathering.",
                "review": "Independent verification, adversarial review or audit of an existing result.",
                "ops": "Runtime, deployment, host, service, process, recovery or operational work.",
                "other": "None of the other lanes is a good fit.",
            },
        },
        "needs_review": {
            "type": "boolean",
            "instructions": (
                "Does this safe reversible task need independent review before it can be "
                "accepted as complete? Ignore protected-action policy because code enforces it separately."
            ),
        },
        "blocker": {
            "type": "choice",
            "instructions": "What is the dominant blocker, if any?",
            "criteria": {
                "none": "No material blocker is present.",
                "missing_data": "Required evidence, input, file, identity or data is missing.",
                "permission": "Authorization, credentials or permissions block progress.",
                "provider": "External provider, API, quota, license or service availability blocks progress.",
                "scientific": "A material scientific/product truth question is unresolved.",
                "runtime": "A host, process, dependency or runtime failure blocks progress.",
                "other": "A real blocker exists but does not match the listed categories.",
            },
        },
        "continuation": {
            "type": "choice",
            "instructions": "What should Hermes do next for safe reversible work?",
            "criteria": {
                "continue": "Proceed to the next safe gate.",
                "retry": "Retry the current reversible operation after a bounded correction.",
                "review": "Send the candidate to an isolated reviewer before proceeding.",
                "stop": "Stop because continuing would be unsafe or unsupported.",
                "escalate": "Escalate because required authority or material information is unavailable.",
            },
        },
        "risk": {
            "type": "score",
            "instructions": "Rate operational risk of continuing the current safe reversible task.",
            "criteria": [
                "low: routine and easily reversible",
                "medium: some uncertainty but contained rollback exists",
                "high: material failure could affect important runtime or evidence",
                "critical: continuing could cross a protected or irreversible boundary",
            ],
        },
    }
