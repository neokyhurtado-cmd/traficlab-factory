#!/usr/bin/env python3
"""
test_routing_resolver.py — Unit tests for routing_resolver.resolve_route.

Covers the contract cases from SUINI#35.AD-1 plus the path-resolution cases
locked in WO-ORCH-AUTODISPATCH-02 step 3:
  - Explicit HERMES_ROUTING_PATH override wins over HERMES_HOME.
  - HERMES_HOME + config/routing.yaml works (the cron path).
  - Default fallback (no env) lands on <script-dir>/../config/routing.yaml.

Plus all four SUINI#35.AD-1 contract cases:
  1. Known repo (ia-vision, suini) -> resolves correctly.
  2. Unknown repo -> denial with PRODUCT_OWNERSHIP_MISMATCH.
  3. Task_assignee mismatch with table -> denial.
  4. ASHLEY route -> read-only, max_runtime_seconds=1800.

Run with:
    python -m pytest ~/.hermes/profiles/orchestrator/scripts/test_routing_resolver.py -v
"""

from __future__ import annotations

import os
import sys

import pytest

# Make sure the resolver module is importable when this file is run directly
# (e.g. `python test_routing_resolver.py`) or via pytest from any CWD.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import routing_resolver  # noqa: E402


# --- Fixtures ---------------------------------------------------------------

# Canonical good routing.yaml reflecting AUTO_DISPATCH_02 reality:
# ia-vision and suini now have REAL target profiles.
GOOD_ROUTING_YAML = (
    "routes:\n"
    "  - repo: neokyhurtado-cmd/suini\n"
    "    product: SUINI\n"
    "    assignee: suini\n"
    "    capabilities: [write]\n"
    "    max_runtime_seconds: 3600\n"
    "  - repo: neokyhurtado-cmd/IA-VISION\n"
    "    product: IA-VISION\n"
    "    assignee: ia-vision\n"
    "    capabilities: [write]\n"
    "    max_runtime_seconds: 3600\n"
    "  - product: ASHLEY\n"
    "    assignee: default\n"
    "    capabilities: [read]\n"
    "    max_runtime_seconds: 1800\n"
)


@pytest.fixture
def routing_path(tmp_path, monkeypatch):
    """Write a known-good routing.yaml into tmp_path and point the resolver at it.

    The resolver uses a module-level default path. We monkey-patch
    ``_load_routing_table`` so it reads our fixture file regardless of where
    the real routing.yaml lives on the test machine. This keeps tests
    hermetic and free of side effects on the real control-plane file.
    """
    p = tmp_path / "routing.yaml"
    p.write_text(GOOD_ROUTING_YAML, encoding="utf-8")

    # Capture the real loader up-front so the closure doesn't recurse via
    # the patched module attribute.
    real_loader = routing_resolver._load_routing_table

    def _loader(path=None):
        return real_loader(str(p))

    monkeypatch.setattr(routing_resolver, "_load_routing_table", _loader)
    return str(p)


# --- Case 1: known repos ----------------------------------------------------

def test_known_repo_suini_resolves_to_real_suini_profile(routing_path):
    """AUTO_DISPATCH_02: SUINI routes to the real `suini` profile (not orchestrator)."""
    decision = routing_resolver.resolve_route("neokyhurtado-cmd/suini", None)
    assert decision.allowed is True
    assert decision.assignee == "suini"
    assert decision.product == "SUINI"
    assert decision.capabilities == ["write"]
    assert decision.max_runtime_seconds == 3600
    assert decision.denial_reason is None


def test_known_repo_ia_vision_resolves_to_real_ia_vision_profile(routing_path):
    """AUTO_DISPATCH_02: IA-VISION routes to the real `ia-vision` profile (not orchestrator)."""
    decision = routing_resolver.resolve_route("neokyhurtado-cmd/IA-VISION", None)
    assert decision.allowed is True
    assert decision.assignee == "ia-vision"
    assert decision.product == "IA-VISION"
    assert decision.capabilities == ["write"]
    assert decision.max_runtime_seconds == 3600
    assert decision.denial_reason is None


# --- Case 2: unknown repo -> PRODUCT_OWNERSHIP_MISMATCH ----------------------

def test_unknown_repo_denied_with_product_ownership_mismatch(routing_path):
    decision = routing_resolver.resolve_route("unknown/repo", None)
    assert decision.allowed is False
    assert decision.denial_reason == "PRODUCT_OWNERSHIP_MISMATCH: repo=unknown/repo"
    # Denied decisions must not leak any routing hints.
    assert decision.assignee is None
    assert decision.product is None
    assert decision.capabilities == []


# --- Case 3: task_assignee disagrees with table -> denied -------------------

def test_task_assignee_mismatch_denied(routing_path):
    """When the task pre-declares an assignee that disagrees with the table,
    the table wins — denial with PRODUCT_OWNERSHIP_MISMATCH."""
    decision = routing_resolver.resolve_route("neokyhurtado-cmd/suini", "default")
    assert decision.allowed is False
    assert decision.assignee == "suini"  # expected assignee still surfaces
    assert decision.product == "SUINI"
    assert decision.denial_reason == (
        "PRODUCT_OWNERSHIP_MISMATCH: assignee=default product=SUINI expected=suini"
    )


def test_task_assignee_match_is_allowed(routing_path):
    """Sanity: when the table says `suini` and the task already says `suini`,
    we still allow (not deny). Confirms we don't deny equal."""
    decision = routing_resolver.resolve_route("neokyhurtado-cmd/suini", "suini")
    assert decision.allowed is True
    assert decision.assignee == "suini"
    assert decision.product == "SUINI"


def test_ia_vision_assignee_mismatch_denied(routing_path):
    """If a task claims assignee=orchestrator for an IA-VISION repo, the table
    says ia-vision → DENY with PRODUCT_OWNERSHIP_MISMATCH. This is the
    double-claim guard that prevents a future suini/ia-vision vs orchestrator
    race from silently re-routing."""
    decision = routing_resolver.resolve_route(
        "neokyhurtado-cmd/IA-VISION", "orchestrator"
    )
    assert decision.allowed is False
    assert decision.assignee == "ia-vision"
    assert decision.denial_reason == (
        "PRODUCT_OWNERSHIP_MISMATCH: assignee=orchestrator product=IA-VISION expected=ia-vision"
    )


# --- Case 4: ASHLEY is read-only with max_runtime_seconds=1800 -------------

def test_ashley_route_is_read_only_with_1800s_cap(routing_path):
    # ASHLEY has no repo key — a repo-less task (None) is the entry point.
    decision = routing_resolver.resolve_route(None, None)
    assert decision.allowed is True
    assert decision.assignee == "default"
    assert decision.product == "ASHLEY"
    assert decision.capabilities == ["read"]
    assert decision.max_runtime_seconds == 1800


def test_ashley_route_keeps_read_only_even_when_assignee_supplied(routing_path):
    # When the table says ASHLEY + default and the task also says default,
    # still read-only — the capability comes from the route, not the caller.
    decision = routing_resolver.resolve_route(None, "default")
    assert decision.allowed is True
    assert decision.capabilities == ["read"]
    assert decision.max_runtime_seconds == 1800


# --- Defensive: missing/malformed routing table must hard-fail --------------

def test_missing_routing_table_raises(tmp_path, monkeypatch):
    """A missing routing.yaml is a control-plane drift signal — hard-fail,
    not silent fallback. The dispatcher must refuse to claim any task if it
    can't read the table."""
    missing = str(tmp_path / "no_such_file.yaml")

    real_loader = routing_resolver._load_routing_table

    def _loader(path=None):
        return real_loader(missing)

    monkeypatch.setattr(routing_resolver, "_load_routing_table", _loader)
    with pytest.raises(FileNotFoundError):
        routing_resolver.resolve_route("neokyhurtado-cmd/suini", None)


def test_malformed_routing_table_raises(tmp_path, monkeypatch):
    """A routing.yaml without a `routes:` list is also a hard error."""
    bad = tmp_path / "bad.yaml"
    bad.write_text("not_routes: []\n", encoding="utf-8")

    real_loader = routing_resolver._load_routing_table

    def _loader(path=None):
        return real_loader(str(bad))

    monkeypatch.setattr(routing_resolver, "_load_routing_table", _loader)
    with pytest.raises(ValueError, match="no 'routes:' list"):
        routing_resolver.resolve_route("neokyhurtado-cmd/suini", None)


# --- Path resolution (AUTO_DISPATCH_02 step 3) -------------------------------

class TestPathResolution:
    """Three precedence tiers for the routing.yaml path:

      1. HERMES_ROUTING_PATH env var wins (tests, fixtures, one-offs).
      2. HERMES_HOME/config/routing.yaml is the normal cron path.
      3. Default fallback: <script-dir>/../config/routing.yaml.
    """

    def _write(self, path, content=GOOD_ROUTING_YAML):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def test_explicit_hermes_routing_path_wins(
        self, tmp_path, monkeypatch
    ):
        """Tier 1: HERMES_ROUTING_PATH env var beats HERMES_HOME and the fallback."""
        explicit = tmp_path / "fixture.yaml"
        home_yaml = tmp_path / "home.yaml"
        self._write(str(explicit))
        self._write(str(home_yaml))

        monkeypatch.setenv("HERMES_ROUTING_PATH", str(explicit))
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))

        assert routing_resolver.current_routing_path() == str(explicit)

    def test_hermes_home_default_path(
        self, tmp_path, monkeypatch
    ):
        """Tier 2: with HERMES_HOME set and no override, the resolver reads
        HERMES_HOME/config/routing.yaml — the orchestrator-profile cron path."""
        monkeypatch.delenv("HERMES_ROUTING_PATH", raising=False)
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))

        assert routing_resolver.current_routing_path() == os.path.join(
            str(tmp_path), "config", "routing.yaml"
        )

    def test_default_fallback_uses_script_relative_path(
        self, tmp_path, monkeypatch
    ):
        """Tier 3: with no env vars, the resolver falls back to
        <script-dir>/../config/routing.yaml (orchestrator profile-local)."""
        monkeypatch.delenv("HERMES_ROUTING_PATH", raising=False)
        monkeypatch.delenv("HERMES_HOME", raising=False)

        expected = os.path.normpath(
            os.path.join(_HERE, "..", "config", "routing.yaml")
        )
        assert os.path.normpath(routing_resolver.current_routing_path()) == expected

    def test_hermes_routing_path_empty_string_is_ignored(
        self, tmp_path, monkeypatch
    ):
        """An empty override should not crash — it's treated as 'unset' and
        the resolver falls through to tier 2/3."""
        monkeypatch.setenv("HERMES_ROUTING_PATH", "")
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))

        assert routing_resolver.current_routing_path() == os.path.join(
            str(tmp_path), "config", "routing.yaml"
        )

    def test_hermes_routing_path_whitespace_is_ignored(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("HERMES_ROUTING_PATH", "   ")
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))

        assert routing_resolver.current_routing_path() == os.path.join(
            str(tmp_path), "config", "routing.yaml"
        )

    def test_resolver_loads_via_hermes_routing_path(
        self, tmp_path, monkeypatch
    ):
        """End-to-end: HERMES_ROUTING_PATH points at a fixture; resolve_route
        uses it without anyone patching _load_routing_table."""
        fixture = tmp_path / "fixture.yaml"
        self._write(str(fixture))
        monkeypatch.setenv("HERMES_ROUTING_PATH", str(fixture))
        monkeypatch.delenv("HERMES_HOME", raising=False)

        decision = routing_resolver.resolve_route(
            "neokyhurtado-cmd/suini", None
        )
        assert decision.allowed is True
        assert decision.assignee == "suini"
        assert decision.product == "SUINI"

    def test_resolver_loads_via_hermes_home(
        self, tmp_path, monkeypatch
    ):
        """End-to-end: HERMES_HOME + config/routing.yaml loads and resolves."""
        self._write(os.path.join(str(tmp_path), "config", "routing.yaml"))
        monkeypatch.delenv("HERMES_ROUTING_PATH", raising=False)
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))

        decision = routing_resolver.resolve_route(
            "neokyhurtado-cmd/IA-VISION", None
        )
        assert decision.allowed is True
        assert decision.assignee == "ia-vision"
        assert decision.product == "IA-VISION"
