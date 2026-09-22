from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .engine import evaluate_shadow
from .provider import TypeSafeJevProvider

LOG = logging.getLogger("jev_shadow.runtime")


def directive_state(directive: Any) -> dict[str, Any]:
    protected = (
        ["human_go_real_required"]
        if bool(getattr(directive, "requires_human_go_real", False))
        else []
    )
    return {
        "task_id": str(getattr(directive, "directive_id", "")),
        "goal": str(getattr(directive, "scope", "")),
        "repository": str(getattr(directive, "repository", "")),
        "branch": str(getattr(directive, "target_branch", "")),
        "action": str(getattr(directive, "action", "")),
        "changed_files_count": 0,
        "tests_status": "PRE_DISPATCH",
        "ci_status": "UNKNOWN",
        "blocker_summary": "",
        "reversible": not bool(protected),
        "last_result": "",
        "reviewer_status": "UNKNOWN",
        "retry_count": 0,
        "protected_flags": protected,
    }


def record_directive_shadow_decision(
    directive: Any,
    evidence_dir: str,
) -> dict[str, Any]:
    """Evaluate a directive and persist advisory evidence without blocking work."""
    try:
        decision = evaluate_shadow(
            directive_state(directive),
            provider=TypeSafeJevProvider(),
        ).as_dict()
    except Exception as exc:  # noqa: BLE001
        decision = {
            "schema": "traficlab_jev_shadow/v2",
            "model": "jev-latest",
            "provider_status": "ERROR",
            "hard_gate_override": bool(
                getattr(directive, "requires_human_go_real", False)
            ),
            "may_control_execution": False,
            "error": f"{type(exc).__name__}: {str(exc)[:800]}",
        }

    if evidence_dir:
        try:
            path = Path(evidence_dir)
            path.mkdir(parents=True, exist_ok=True)
            (path / "jev_shadow.json").write_text(
                json.dumps(decision, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            LOG.warning("could not write Jev evidence: %s", exc)

    return decision
