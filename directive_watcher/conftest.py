"""pytest discovery + sys.path shim for the directive_watcher package.

We add the repo root to ``sys.path`` so ``import directive_watcher.*``
resolves when the test files are collected by a test runner that does
not install the package. This mirrors the pattern used by the
``orchestrator/scripts/test_*.py`` files.
"""
from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# PyYAML is only needed for the CLI config loader. We treat it as a
# hard requirement for the full test suite.
import pytest

pytest_plugins = []  # keep this explicit so we don't accidentally pull in
                      # unrelated plugins from the host environment
