"""BODY-1 authority conflict resolver.

Per AGENT_BODY_27_READONLY_AUDIT §3 + §7: when multiple authoritative
sources disagree, apply the precedence map from
policies/authority-hierarchy.md WITHOUT model judgment.

Precedence (frozen):
    github_remote > mission_control > ia_vision_domain > local_checkpoint
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

PRECEDENCE = (
    "github_remote",
    "mission_control",
    "ia_vision_domain",
    "local_checkpoint",
)


@dataclass(frozen=True)
class AuthorityClaim:
    source: str
    value: str
    freshness: int  # unix_ts


@dataclass(frozen=True)
class AuthorityVerdict:
    winner_source: Optional[str]
    winner_value: Optional[str]
    fail_closed: bool
    reason: str


def apply_precedence(claims: List[AuthorityClaim], domain: str) -> AuthorityVerdict:
    """Pick the winner from the highest-precedence source present.

    Pure lookup — no model judgment, no heuristics, no majority vote.
    """
    by_source = {c.source: c for c in claims}
    for src in PRECEDENCE:
        if src in by_source:
            winner = by_source[src]
            return AuthorityVerdict(
                winner_source=winner.source,
                winner_value=winner.value,
                fail_closed=False,
                reason=f"precedence[{src}] applies for domain {domain!r}",
            )
    return AuthorityVerdict(
        winner_source=None,
        winner_value=None,
        fail_closed=True,
        reason=f"no source matches precedence map for domain {domain!r}",
    )
