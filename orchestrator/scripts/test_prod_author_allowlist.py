#!/usr/bin/env python3
"""
SEGURO A — PROD_AUTHOR_ALLOWLIST (PR #19 closeout, Phase 4 re-audit).

The Phase 3 closeout closed the CLI-side separation (--env=prod|test with
explicit --author-allowlist file). But production does NOT enter via the
CLI: it enters via the cron-driven `orchestrator/scripts/github_poller.py
→ run_directive_tick()`. That path was hardcoding
``frozenset({"astra", "neokyhurtado-cmd"})`` (comment 5630425864).

These tests are the biters:

  - PROD path with file present + author `neokyhurtado-cmd` → ADMITTED.
  - PROD path with file present + author `astra` → DENIED (astra is
    intentionally NOT in the prod allowlist — production must only
    accept directives from David).
  - PROD path with file MISSING → FAIL-CLOSED (MissingProdAllowlistError
    + non-zero exit). The handler MUST propagate and the poller MUST
    surface a non-zero return code (no silent default to the old hardcode).
  - The CLI and the poller share the same loader function (single source
    of truth).

Run with::

    python -m pytest orchestrator/scripts/test_prod_author_allowlist.py -v
"""
from __future__ import annotations

import pathlib
import os
import sys
import textwrap
from pathlib import Path
from unittest import mock

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import github_poller  # noqa: E402
import directive_watcher.allowlist_loader as allowlist_loader  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

PROD_AUTHORS_FILENAME = "authors.prod.yaml"


def _write_prod_authors(tmp_path: Path, authors: list[str]) -> Path:
    """Write a prod author allowlist file and return its path."""
    p = tmp_path / PROD_AUTHORS_FILENAME
    p.parent.mkdir(parents=True, exist_ok=True)
    body = "allowlisted_authors:\n" + "".join(f"  - {a}\n" for a in authors)
    p.write_text(body, encoding="utf-8")
    return p


@pytest.fixture
def fake_routing(monkeypatch, tmp_path):
    """A routing.yaml with the single repo we test against."""
    content = (
        "routes:\n"
        "  - repo: neokyhurtado-cmd/traficlab-factory\n"
        "    product: TRAFICLAB\n"
        "    assignee: orchestrator\n"
        "    capabilities: [write]\n"
    )
    p = tmp_path / "routing.yaml"
    p.write_text(content, encoding="utf-8")
    monkeypatch.setenv("HERMES_ROUTING_PATH", str(p))
    monkeypatch.setattr(
        "hermes_cli.profiles.list_profile_names",
        lambda: ["orchestrator"],
        raising=False,
    )
    return p


@pytest.fixture
def stub_orch_tick(monkeypatch):
    """Stub the downstream ``WatcherHandler.tick`` so we don't need the
    full directive-handler machinery for the prod-author test surface.
    The poller must still BUILD the AllowlistConfig (the contract under
    test) and call the loader correctly; we just short-circuit dispatch.
    """
    from directive_watcher.handler import TickSummary

    captured = {"allowlist": None, "called": 0}

    def fake_handler_init(self, **kwargs):
        captured["allowlist"] = kwargs.get("allowlist")
        # Capture the args but skip the real __init__ side effects so
        # the test stays hermetic.

    monkeypatch.setattr(
        "directive_watcher.handler.WatcherHandler.__init__",
        fake_handler_init,
    )

    def fake_tick(self, repos, **kw):
        captured["called"] += 1
        return TickSummary(polled_repos=list(repos))

    monkeypatch.setattr(
        "directive_watcher.handler.WatcherHandler.tick",
        fake_tick,
    )
    return captured


# ---------------------------------------------------------------------------
# THE BITERS — each test fails on the pre-fix code path
# ---------------------------------------------------------------------------


def test_run_directive_tick_loads_prod_allowlist_from_env_file(
    tmp_path, monkeypatch, fake_routing, stub_orch_tick
):
    """PROD path with explicit file present: the AllowlistConfig's
    authors must come from the file. The old hardcode
    ``{"astra", "neokyhurtado-cmd"}`` must be gone."""
    prod_file = _write_prod_authors(tmp_path, ["neokyhurtado-cmd"])
    monkeypatch.setenv("HERMES_PROD_AUTHORS_ALLOWLIST", str(prod_file))

    rc = github_poller.run_directive_tick(["neokyhurtado-cmd/traficlab-factory"])

    assert rc == 0, (
        f"run_directive_tick returned non-zero for valid prod allowlist; rc={rc}"
    )
    allowlist = stub_orch_tick["allowlist"]
    assert allowlist is not None, "WatcherHandler was never constructed"
    # MUST come from the file. Only `neokyhurtado-cmd` is allowlisted in prod.
    assert allowlist.allowlisted_authors == frozenset({"neokyhurtado-cmd"}), (
        f"prod allowlist came from the wrong source; got "
        f"{allowlist.allowlisted_authors!r}"
    )
    assert stub_orch_tick["called"] == 1


def test_run_directive_tick_denies_astra_when_not_in_prod_file(
    tmp_path, monkeypatch, fake_routing, stub_orch_tick
):
    """The previous code hardcoded ``astra`` in the prod allowlist. The
    fix MUST move the source of truth to the YAML file, and the prod
    file MUST NOT contain ``astra`` by default. We verify by running the
    AllowlistConfig through the auth-allowed gate: astra is OUT."""
    prod_file = _write_prod_authors(tmp_path, ["neokyhurtado-cmd"])
    monkeypatch.setenv("HERMES_PROD_AUTHORS_ALLOWLIST", str(prod_file))

    rc = github_poller.run_directive_tick(["neokyhurtado-cmd/traficlab-factory"])

    assert rc == 0
    allowlist = stub_orch_tick["allowlist"]
    # astra is hard-blocked in prod by policy (file-only author list).
    assert not allowlist.author_allowed("astra"), (
        "PROD allowlist must NOT include astra — production must only "
        "accept directives from David. The Phase 4 re-audit "
        "(comment 5630425864) explicitly forbade astra in prod."
    )
    # The legitimate operator IS allowed.
    assert allowlist.author_allowed("neokyhurtado-cmd")


def test_run_directive_tick_fail_closed_when_prod_file_missing(
    tmp_path, monkeypatch, fake_routing, stub_orch_tick
):
    """FAIL-CLOSED: when ``HERMES_PROD_AUTHORS_ALLOWLIST`` points at a
    non-existent file, ``run_directive_tick`` MUST propagate
    ``MissingProdAllowlistError`` and MUST NOT silently fall back to the
    legacy hardcode. No tick may run, no AllowlistConfig may be built
    with the hardcoded author list."""
    monkeypatch.setenv(
        "HERMES_PROD_AUTHORS_ALLOWLIST", str(tmp_path / "no_such_prod.yaml")
    )

    with pytest.raises(allowlist_loader.MissingProdAllowlistError) as excinfo:
        github_poller.run_directive_tick(["neokyhurtado-cmd/traficlab-factory"])

    # The error message MUST be specific so an operator can diagnose.
    msg = str(excinfo.value).lower()
    assert "prod author allowlist file missing" in msg, (
        f"MissingProdAllowlistError message must be diagnostic; got {excinfo.value!r}"
    )
    assert "fail-closed" in msg, (
        f"MissingProdAllowlistError message must include 'fail-closed'; "
        f"got {excinfo.value!r}"
    )
    # And the tick MUST NOT have been called.
    assert stub_orch_tick["called"] == 0, (
        "watcher tick ran despite missing prod allowlist — fail-open regression"
    )


def test_run_directive_tick_fail_closed_when_env_unset(
    monkeypatch, fake_routing, stub_orch_tick
):
    """FAIL-CLOSED default: when no env var and no shipped default
    resolves to a real file, ``run_directive_tick`` MUST propagate
    ``MissingProdAllowlistError``. The old hardcode MUST NOT be a
    fallback."""
    monkeypatch.delenv("HERMES_PROD_AUTHORS_ALLOWLIST", raising=False)
    # Make sure no shipped default file accidentally exists in the
    # repo root the loader might fall back to (the loader must fail
    # closed before falling back).
    monkeypatch.setattr(
        allowlist_loader,
        "_DEFAULT_PROD_AUTHORS_PATH",
        pathlib.Path("/nonexistent/traficlab-factory/authors.prod.yaml"),
        raising=False,
    )

    with pytest.raises(allowlist_loader.MissingProdAllowlistError):
        github_poller.run_directive_tick(["neokyhurtado-cmd/traficlab-factory"])

    assert stub_orch_tick["called"] == 0


def test_load_prod_author_allowlist_reads_yaml_and_normalises(tmp_path):
    """The loader MUST round-trip a YAML file with case-insensitive
    authors (GitHub logins) and whitespace-tolerance (defensive)."""
    p = tmp_path / "authors.prod.yaml"
    p.write_text(
        textwrap.dedent(
            """\
            allowlisted_authors:
              - NeokyHurtado-cmd
              -    spaced-author
            """
        ),
        encoding="utf-8",
    )

    authors = allowlist_loader.load_prod_author_allowlist(str(p))
    assert authors == frozenset({"neokyhurtado-cmd", "spaced-author"})


def test_load_prod_author_allowlist_rejects_missing_file(tmp_path):
    p = tmp_path / "nope.yaml"
    with pytest.raises(allowlist_loader.MissingProdAllowlistError):
        allowlist_loader.load_prod_author_allowlist(str(p))


def test_load_prod_author_allowlist_rejects_empty_list(tmp_path):
    """A YAML file that parses but carries an empty authors list is a
    configuration error, NOT a permit-all. The loader must fail
    closed."""
    p = tmp_path / "authors.prod.yaml"
    p.write_text("allowlisted_authors: []\n", encoding="utf-8")
    with pytest.raises(allowlist_loader.MissingProdAllowlistError):
        allowlist_loader.load_prod_author_allowlist(str(p))


# ---------------------------------------------------------------------------
# Sabotage-run hook — read by the dedicated sabotage test below.
# ---------------------------------------------------------------------------


def _current_hardcode_phrase() -> str:
    """Read the current literal in github_poller.run_directive_tick. If
    the fix is in place, this returns the empty string and the sabotage
    test below passes trivially (the fix holds). If the fix is reverted,
    this returns the legacy phrase and the sabotage test FAILS — the
    fail-loud signal we want."""
    import inspect

    src = inspect.getsource(github_poller.run_directive_tick)
    if '"astra"' in src and '"neokyhurtado-cmd"' in src:
        # Detect the legacy hardcode shape: frozenset literal with astra.
        if 'frozenset({"astra", "neokyhurtado-cmd"})' in src or \
           "frozenset({'astra', 'neokyhurtado-cmd'})" in src:
            return 'frozenset({"astra", "neokyhurtado-cmd"})'
    return ""


def test_no_hardcoded_prod_author_tuple_in_run_directive_tick():
    """Sabotage-run guard: this test EXISTS to fail loudly if anyone
    reverts the fix and re-hardcodes the prod author list inside
    ``run_directive_tick``. The previous bug was a literal
    ``frozenset({"astra", "neokyhurtado-cmd"})`` — the Phase 4 re-audit
    (comment 5630425864) explicitly forbade it."""
    legacy = _current_hardcode_phrase()
    assert not legacy, (
        "run_directive_tick still hardcodes the prod author allowlist: "
        f"{legacy!r}. Production must read the allowlist from "
        "HERMES_PROD_AUTHORS_ALLOWLIST (or the shipped default file) — "
        "no literal author lists."
    )