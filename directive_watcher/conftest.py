"""pytest discovery + sys.path shim for the directive_watcher package.

We add the repo root to ``sys.path`` so ``import directive_watcher.*``
resolves when the test files are collected by a test runner that does
not install the package. This mirrors the pattern used by the
``orchestrator/scripts/test_*.py`` files.

Per pytest's pytest_plugins-in-non-top-level-conftest deprecation, we
do NOT declare ``pytest_plugins`` here — that variable must live in a
top-level conftest at the repo root (see ``conftest.py`` there).
"""
from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
