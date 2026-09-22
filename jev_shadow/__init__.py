"""TrafficLab Factory Jev advisory decision plane.

Jev is intentionally non-authoritative here. It may observe and recommend
routing/review/risk decisions, but protected gates remain deterministic.
"""

from .engine import evaluate_shadow

__all__ = ["evaluate_shadow"]
