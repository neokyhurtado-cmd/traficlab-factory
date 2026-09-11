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

import importlib.util
import sys
import types

pytest_plugins = []


# P0 #4 — hermes_cli detection that does NOT shadow real installs.
#
# The pre-existing fixture ``fixture_profiles`` in
# orchestrator/scripts/test_github_poller.py calls
# ``monkeypatch.setattr("hermes_cli.profiles.list_profile_names", ...)``
# unconditionally on collection. pytest's MonkeyPatch.derive_importpath
# resolves the dotted path by calling ``importlib.import_module("hermes_cli")``
# BEFORE consulting ``raising=False``, so on a stock CI runner (where
# hermes_cli is not installed) the fixture errors out at collection time.
#
# The fix: register a stub ``hermes_cli`` package in ``sys.modules`` at
# conftest import time.
#
# Astra re-audit (PR #19 comment 5629796729) flagged the previous gate
# ``"hermes_cli" not in sys.modules`` as WRONG: that gate asks the
# IMPORT HISTORY, not the installation state. On an operator host where
# hermes_cli is installed but pytest loads conftest BEFORE anything
# imports hermes_cli, the broken gate registers the stub anyway —
# shadowing the real package for the entire pytest session, so every
# later ``import hermes_cli.foo`` resolves to a fake.
#
# The correct gate is importlib.util.find_spec, which asks the import
# system whether the module is on disk (i.e. installable) regardless of
# whether anything has imported it yet. Behaviour:
#
#   hermes_cli installed  → find_spec returns a real spec → no stub.
#   hermes_cli absent     → find_spec returns None        → register stub.
#
# This keeps the pre-existing fixture_profiles path working on stock CI
# (where hermes_cli is absent) without shadowing real installs on
# operator hosts (where hermes_cli is present). Behaviour is exercised
# by test_hermes_cli_detection.py.

if importlib.util.find_spec("hermes_cli") is None:
    _profiles = types.ModuleType("hermes_cli.profiles")

    def list_profile_names():
        return []

    _profiles.list_profile_names = list_profile_names

    _kanban_db = types.ModuleType("hermes_cli.kanban_db")
    _kanban_db.event = lambda *a, **kw: None

    class _NullCtx:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def commit(self):
            pass

    _kanban_db.connect_closing = lambda: _NullCtx()
    _kanban_db._append_event = lambda *a, **kw: None

    _root = types.ModuleType("hermes_cli")
    _root.profiles = _profiles
    _root.kanban_db = _kanban_db

    sys.modules["hermes_cli"] = _root
    sys.modules["hermes_cli.profiles"] = _profiles
    sys.modules["hermes_cli.kanban_db"] = _kanban_db
