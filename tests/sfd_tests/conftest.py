"""Pytest conftest for tests/sfd_tests/.

Adds the repo root to sys.path so ``from single_front_door.intake import …``
resolves during pytest collection, regardless of where pytest is invoked.

This mirrors the pattern used by orchestrator/scripts/test_*.py and keeps
the SINGLE-FRONT-DOOR-01 adapter discoverable without changing the
repo's existing pytest rootdir (which already lives at the repo root).

NB: the test directory is named ``sfd_tests`` (not ``single_front_door``)
to avoid pytest's namespace-package collision with the real
``single_front_door/`` package at the repo root.
"""

from __future__ import annotations

import sys
from pathlib import Path

# tests/sfd_tests/conftest.py → repo root is parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
