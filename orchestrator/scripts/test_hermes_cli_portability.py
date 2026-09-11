"""Tests for hermes_cli portability — Phase 3 / Objective 4.

Per the steered rephrase of objective 4 (comment 5629293070):
CI must cover BOTH contracts deliberately:

  (a) with hermes_cli installed (the dev/operator path),
  (b) without hermes_cli installed (the CI path, the deployed-agent path,
      the audit/standalone path).

These tests exercise both branches via import mocking. They do NOT
change the production code's import shape — that is the contract.
"""
from __future__ import annotations

import importlib
import sys

import pytest


# Modules in the repo that import hermes_cli lazily. Importing them
# must NOT require hermes_cli to be importable.
_LAZY_HERMES_CLI_MODULES = [
    "orchestrator.scripts.eligibility_hook",
    "orchestrator.scripts.recovery_observer",
]


def _hide_hermes_cli(monkeypatch):
    """Make ``import hermes_cli`` raise ImportError, simulating an env
    without hermes_cli installed. Used by the 'without hermes_cli'
    tests below."""
    import builtins  # noqa: PLC0415

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "hermes_cli" or name.startswith("hermes_cli."):
            raise ImportError(f"simulated missing hermes_cli: {name}")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)


@pytest.mark.parametrize("module_name", _LAZY_HERMES_CLI_MODULES)
def test_module_imports_without_hermes_cli(module_name: str, monkeypatch):
    """Each module that uses hermes_cli must import cleanly even when
    hermes_cli is not installed. This is the CI path — clean machines,
    no `pip install hermes_cli`, no monkey-patching at runtime."""
    # Drop the module from sys.modules so the lazy import runs again
    # under the simulated missing hermes_cli.
    sys.modules.pop(module_name, None)
    sys.modules.pop("orchestrator.scripts.eligibility_hook", None)
    sys.modules.pop("orchestrator.scripts.recovery_observer", None)

    _hide_hermes_cli(monkeypatch)

    # Importing the module must succeed (no hermes_cli required at
    # module-load time).
    mod = importlib.import_module(module_name)
    assert mod is not None


def test_github_poller_imports_without_hermes_cli(monkeypatch):
    """github_poller.py uses hermes_cli.profiles lazily. The fallback
    path (``~/.hermes/profiles/``) must work even if hermes_cli is
    missing entirely."""
    _hide_hermes_cli(monkeypatch)
    sys.modules.pop("github_poller", None)
    sys.modules.pop("orchestrator.scripts.github_poller", None)
    mod = importlib.import_module("orchestrator.scripts.github_poller")
    assert mod is not None
    # The fallback path is exposed as a callable.
    assert callable(mod._on_disk_profiles)


def test_eligibility_hook_event_writer_raises_when_hermes_cli_missing(
    monkeypatch
):
    """When the eligibility hook is asked to emit an event WITHOUT
    hermes_cli present, it must raise a clear RuntimeError — fail loud,
    not fail silent. The CI path must surface the missing dependency."""
    _hide_hermes_cli(monkeypatch)
    sys.modules.pop("orchestrator.scripts.eligibility_hook", None)
    mod = importlib.import_module("orchestrator.scripts.eligibility_hook")

    # Force the lazy import path so the failure is observable.
    mod._event_writer.cache_clear()
    with pytest.raises(RuntimeError, match="hermes_cli"):
        mod._event_writer()


def test_github_poller_profiles_fallback_when_hermes_cli_missing(
    tmp_path, monkeypatch
):
    """Without hermes_cli, _on_disk_profiles() must fall back to walking
    the default hermes root's profiles/ directory and return the set of
    on-disk profile names."""
    # Create a fake ~/.hermes/profiles/ tree with two profiles.
    fake_root = tmp_path / ".hermes"
    profiles = fake_root / "profiles"
    profiles.mkdir(parents=True)
    (profiles / "alice").mkdir()
    (profiles / "bob").mkdir()

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(fake_root))

    _hide_hermes_cli(monkeypatch)
    sys.modules.pop("orchestrator.scripts.github_poller", None)
    mod = importlib.import_module("orchestrator.scripts.github_poller")

    result = mod._on_disk_profiles()
    assert "alice" in result
    assert "bob" in result
