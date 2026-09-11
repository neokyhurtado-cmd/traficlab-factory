"""
P0 #3 — ONE TICK = ONE RUN RECORD.

The Phase 3 re-audit (PR #19 comment 5629796729) flagged that ``--once``
writes TWO run records per invocation: ``cli.main()`` calls
``store.record_run_start()`` itself, then ``handler.tick()`` calls
``store.record_run_start()`` AGAIN internally. That double-paints
``watcher_run``, corrupting the War Room observability story.

This test asserts the contract:
  - exactly one record_run_start per logical --once invocation
  - exactly one record_run_finish per logical --once invocation
  - handler.tick(injected run accounting) does NOT spawn its own when
    the cli owns the run accounting
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


@pytest.fixture
def _isolated_imports(monkeypatch):
    """Make sure we import directive_watcher.* fresh inside the test."""
    import importlib

    for mod_name in list(sys.modules):
        if mod_name.startswith("directive_watcher"):
            monkeypatch.delitem(sys.modules, mod_name, raising=False)
    yield


def test_cli_once_records_exactly_one_run(tmp_path, monkeypatch, _isolated_imports):
    """One logical --once invocation = one record_run_start = one record_run_finish.

    We probe via the watcher_run SQLite table directly so the test is
    agnostic about the precise tick semantics; it only asserts the
    SCAR (runs-in-storage) contract that Astra re-audit demanded.
    """
    import directive_watcher.cli as cli_mod
    from directive_watcher.allowlist import AllowlistConfig
    from directive_watcher.gh_client import FakeGitHubClient

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "allowlisted_repos:\n"
        "  - neokyhurtado-cmd/traficlab-factory\n"
        "allowlisted_authors:\n"
        "  - astra\n",
        encoding="utf-8",
    )
    sidecar = tmp_path / "sidecar.db"
    status_path = tmp_path / "watcher_status.json"

    # Stub the dispatcher so no real subprocess runs.
    class _StubDispatcher:
        def __init__(self, *args, **kwargs):
            pass

        def dispatch(self, request):
            from directive_watcher.orch_dispatch import DispatchResult
            return DispatchResult(
                session_id="sess-stub",
                kanban_task_id="t_stub",
                assignee="hermes-director",
                state="DISPATCHED",
            )

    monkeypatch.setattr(
        "directive_watcher.cli.OrchestratorDispatcher", _StubDispatcher
    )
    monkeypatch.setattr("directive_watcher.cli.GHCLIClient", FakeGitHubClient)

    rc = cli_mod.main([
        "--config", str(config_path),
        "--sidecar-db", str(sidecar),
        "--status-path", str(status_path),
        "--once",
    ])
    assert rc == 0

    # Probe the SQLite sidecar directly — we want the raw row count, not
    # a parsed TickSummary that might mask the duplication.
    import sqlite3
    con = sqlite3.connect(str(sidecar))
    cur = con.execute("SELECT COUNT(*) FROM watcher_run")
    (total,) = cur.fetchone()
    cur = con.execute(
        "SELECT status, notes, COUNT(*) FROM watcher_run GROUP BY status, notes"
    )
    rows = cur.fetchall()
    con.close()

    assert total == 1, (
        f"P0 #3 violation: --once must produce EXACTLY ONE watcher_run row, "
        f"got {total}. Rows by (status, notes): {rows}. "
        f"See PR #19 comment 5629796729 — cli.main() and "
        f"handler.tick() both calling record_run_start()."
    )
