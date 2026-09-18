"""Jev shadow decision plane for Hermes.

This package is advisory-only. It must never authorize protected actions or
change execution control in shadow mode.
"""

from .engine import evaluate_shadow
from .contracts import ShadowDecision, TaskSnapshot

__all__ = ["evaluate_shadow", "ShadowDecision", "TaskSnapshot"]
