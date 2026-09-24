from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from jev_shadow.contracts import TaskSnapshot
from jev_shadow.engine import evaluate_shadow
from jev_shadow.provider import DecisionProvider, TypeSafeJevProvider

from .contracts import BRIDGE_SCHEMA, PROTOCOL_VERSION, BridgeResult, resolve_mode


def _request_digest(snapshot: TaskSnapshot) -> str:
    canonical = json.dumps(
        snapshot.as_state(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class FactoryA2ABridge:
    """Translate an A2A request into the existing JEV shadow decision plane.

    Important: this class has no action callback, shell runner, git writer,
    scheduler, merge path, or promotion hook. It can only return advisory
    evidence from evaluate_shadow().
    """

    def __init__(
        self,
        *,
        mode: str | None = None,
        provider: DecisionProvider | None = None,
    ) -> None:
        self.mode = resolve_mode(mode)
        self.provider = provider or TypeSafeJevProvider()

    def handle(self, raw_state: Mapping[str, Any]) -> BridgeResult:
        snapshot = TaskSnapshot.from_mapping(raw_state)
        digest = _request_digest(snapshot)

        if self.mode == "off":
            return BridgeResult(
                schema=BRIDGE_SCHEMA,
                protocol_version=PROTOCOL_VERSION,
                status="DISABLED",
                mode="off",
                task_id=snapshot.task_id,
                request_sha256=digest,
                error="A2A bridge is off; set TRAFICLAB_A2A_MODE=shadow to observe.",
            )

        decision = evaluate_shadow(snapshot.as_state(), provider=self.provider)
        return BridgeResult(
            schema=BRIDGE_SCHEMA,
            protocol_version=PROTOCOL_VERSION,
            status="OK" if decision.provider_status == "OK" else decision.provider_status,
            mode="shadow",
            advisory_only=True,
            may_control_execution=False,
            task_id=snapshot.task_id,
            request_sha256=digest,
            decision=decision.as_dict(),
            error=decision.error,
        )


def parse_a2a_text(text: str) -> dict[str, Any]:
    """Accept a JSON TaskSnapshot payload, or treat plain text as a goal."""
    stripped = (text or "").strip()
    if not stripped:
        return {"goal": "", "action": "A2A_ADVISORY_REQUEST"}

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return {"goal": stripped, "action": "A2A_ADVISORY_REQUEST"}

    if isinstance(payload, Mapping):
        return dict(payload)
    return {"goal": stripped, "action": "A2A_ADVISORY_REQUEST"}
