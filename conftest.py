"""Top-level pytest conftest for traficlab-factory.

Two responsibilities:
  1. ``pytest_plugins = []`` keeps pytest's plugin autodetect off, so
     we don't accidentally pull in host-environment plugins during CI.
  2. ``sys.path`` already includes the repo root (run from this dir),
     so ``import directive_watcher.*`` resolves without per-package
     conftest hacks (which pytest deprecates for non-top-level files).

Per Fix #6 from the Astra re-audit, pytest discovery now runs over the
FULL repo (no ``testpaths`` narrowing). The suites that execute are:

  - directive_watcher/tests/        — Phase 1 directive watcher
  - orchestrator/scripts/           — github_poller + astra_consult + …
  - control/tests/test_*.py         — anything that is a real pytest
                                       module. control/tests/test_adversarial.py
                                       is a STANDALONE runner (does
                                       ``sys.exit(0)``) and is excluded
                                       from pytest collection via
                                       ``control/tests/conftest.py``.
"""
from __future__ import annotations

pytest_plugins = []
