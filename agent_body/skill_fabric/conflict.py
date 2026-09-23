"""Skill Fabric — deterministic conflict resolver.

Rule 1 (canonical Factory wins) is the only rule fully implemented in
SCAFFOLD state. Rule 2 (between-external conflict) and rule 3
(structural redefinition) are stubbed and will land with the G3
adversarial test suite.

Canonical authority hierarchy (mirrors issue #51):

    GitHub durable truth
    > TrafficLab Factory policies / authority
    > Agent Body capability boundaries
    > project contracts
    > external skill instructions
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional

from .registry import SkillEntry


@dataclass(frozen=True)
class ConflictResolution:
    winner: Optional[SkillEntry]
    losers: List[SkillEntry]
    reason: str

    @property
    def canonical_factory_won(self) -> bool:
        return self.winner is None and self.reason.startswith("CANONICAL_FACTORY_WINS")


def resolve(
    selected: Iterable[SkillEntry],
    factory_directive: str,
) -> ConflictResolution:
    """Resolve conflicts between the loaded skill subset.

    `factory_directive` is the canonical Factory policy statement for the
    current task scope. Any skill whose instruction contradicts it loses
    by Rule 1.
    """
    selected_list = list(selected)
    if not selected_list:
        return ConflictResolution(
            winner=None, losers=[], reason="CANONICAL_FACTORY_WINS: empty skill subset"
        )

    # Rule 1: canonical Factory wins against any skill conflict.
    # SCAFFOLD heuristic: any skill whose declared `conflicts` includes
    # "__FACTORY_CANONICAL__" is treated as contradicting Factory.
    factory_token = "__FACTORY_CANONICAL__"
    losers: List[SkillEntry] = []
    winners: List[SkillEntry] = []
    for s in selected_list:
        if factory_token in s.conflicts:
            losers.append(s)
        else:
            winners.append(s)

    # Rule 2/3 stubs (will land with G3 adversarial tests).
    # For now, if multiple winners remain, surface as conflict unresolved.
    if len(winners) > 1:
        return ConflictResolution(
            winner=None,
            losers=[],
            reason=(
                "RULE_2_STUB: multiple winners need explicit conflict declaration; "
                f"candidates={[w.id for w in winners]}"
            ),
        )

    if len(winners) == 1:
        return ConflictResolution(
            winner=winners[0],
            losers=losers,
            reason=f"SINGLE_WINNER:{winners[0].id}",
        )

    # All loaded skills lost to Factory.
    return ConflictResolution(
        winner=None,
        losers=losers,
        reason=(
            "CANONICAL_FACTORY_WINS: "
            + ",".join(s.id for s in losers)
            + " rejected; Factory directive "
            + factory_directive[:120]
        ),
    )
