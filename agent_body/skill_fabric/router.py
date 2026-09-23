"""Skill Fabric — task-scoped router.

The router returns the SMALLEST set of skills that match a task intent.
It does NOT inject all skill text into every bootstrap (per issue #51
section C, requirement 4: "loads only those skill instructions on demand").

SCAFFOLD state: zero external skills registered, so the router returns
[] for every intent. Canonical Hermes/Factory behavior is preserved.
"""
from __future__ import annotations

from typing import Iterable, List, Set

from .registry import Mode, SkillEntry


def route(
    intent: str,
    entries: Iterable[SkillEntry],
    project_id: str,
) -> List[SkillEntry]:
    """Return the smallest relevant skill subset for the intent.

    Rules:
      - Only ACTIVE or SHADOW skills are candidates.
      - CATALOG is discovery-only and never auto-loaded.
      - BLOCKED is never loaded.
      - CANDIDATE is never loaded (awaiting activation evidence).
      - `allowed_projects` must include the current project_id (or "*").
      - SHADOW is only loaded for canary tasks (intent starts with "shadow:").
    """
    selected: List[SkillEntry] = []
    intent_lower = intent.lower().strip()
    is_canary = intent_lower.startswith("shadow:")

    for e in entries:
        if e.mode not in (Mode.ACTIVE, Mode.SHADOW):
            continue
        if e.mode == Mode.SHADOW and not is_canary:
            continue
        if "*" not in e.allowed_projects and project_id not in e.allowed_projects:
            continue
        # Capability overlap (word-level overlap; SCAFFOLD heuristic).
        intent_tokens: Set[str] = set(
            t for t in intent_lower.replace(":", " ").split() if len(t) >= 3
        )
        cap_tokens: Set[str] = set()
        for cap in e.capabilities:
            cap_tokens.update(t for t in cap.lower().split() if len(t) >= 3)
        if intent_tokens & cap_tokens:
            selected.append(e)
    return selected


def empty_routing(entries: Iterable[SkillEntry]) -> bool:
    """True iff no external skill would be loaded for any intent."""
    return all(e.mode in (Mode.BLOCKED, Mode.CANDIDATE, Mode.CATALOG) for e in entries)
