"""Skill Fabric — read-only derived graph adapter (STUB in SCAFFOLD state).

V1 issue #51 section E requires that Graphify / Understand-Anything are
evaluated for codebase visualization as READ-ONLY over product repos
during canary. They MUST NOT become a second canonical DB, vector DB,
or knowledge base. Generated graph/index is DERIVED CACHE / EVIDENCE
only, with provenance back to repo/path/SHA.

This module is a SCAFFOLD stub; the SHADOW canary in G4 will activate
the real adapter behind a feature flag.
"""
from __future__ import annotations

from pathlib import Path


class GraphAdapterNotActive(Exception):
    """Raised when the graph adapter is invoked before SHADOW activation.

    Per issue #51 section E, the graph adapter is READ-ONLY SHADOW only.
    Activation requires:
      - upstream SHA pinned
      - intake gates PASS
      - SHADOW canary PASS with at least one repo (per G4)
      - registry row in mode=SHADOW
    """


def build_graph(repo_path: Path) -> None:
    """SCAFFOLD stub. Raises until SHADOW canary activates this adapter."""
    raise GraphAdapterNotActive(
        f"graph adapter not active; repo_path={repo_path}. "
        "Activate via G4 SHADOW canary before invoking build_graph."
    )
