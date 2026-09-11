"""Tests for the scheduler loop and CLI plumbing."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

from directive_watcher.allowlist import AllowlistConfig
from directive_watcher.cli import load_allowlist, parse_args
from directive_watcher.gh_client import FakeGitHubClient, RemoteComment
from directive_watcher.handler import TickSummary, WatcherHandler
from directive_watcher.retry import BackoffPolicy
from directive_watcher.scheduler import Scheduler, SchedulerConfig, build_status
from directive_watcher.sidecar_store import SidecarStore


def _make_comment(cid: int, body: str, author: str = "astra") -> RemoteComment:
    return RemoteComment(
        id=cid, author=author, body=body,
        url=f"https://github.com/r/o/issues/1#issuecomment-{cid}",
        issue_number=1,
    )


def _directive_body(directive_id: str = "d-1") -> str:
    return (
        "[ASTRA_DIRECTIVE:v1]\n"
        "ACTION = CONTINUE\n"
        "REPOSITORY = neokyhurtado-cmd/traficlab-factory\n"
        "ISSUE = 1\n"
        "TARGET_BRANCH = AUTO_FROM_ISSUE_CONTEXT\n"
        "EXPECTED_HEAD = NONE\n"
        "SCOPE = test\n"
        "AUTO_NEXT_SAFE_GATE = YES\n"
        "REQUIRES_HUMAN_GO_REAL = NO\n"
        f"DIRECTIVE_ID = {directive_id}\n"
    )


def test_scheduler_runs_until_max_ticks(tmp_path, monkeypatch):
    store = SidecarStore(tmp_path / "sidecar.db")
    gh = FakeGitHubClient()
    allowlist = AllowlistConfig(
        allowlisted_repos=frozenset({"neokyhurtado-cmd/traficlab-factory"}),
        allowlisted_authors=frozenset({"astra"}),
    )
    handler = WatcherHandler(
        store=store, gh=gh, allowlist=allowlist,
        evidence_root=str(tmp_path),
        backoff=BackoffPolicy(initial_seconds=0.001),
    )
    scheduler = Scheduler(
        config=SchedulerConfig(interval_seconds=0.01, max_ticks=2, status_path=str(tmp_path / "status.json")),
        handler=handler,
        repos=["neokyhurtado-cmd/traficlab-factory"],
    )
    # Monkey-patch sleep so the test runs fast.
    monkeypatch.setattr("directive_watcher.scheduler.time.sleep", lambda s: None)
    scheduler.run_forever()
    runs = store.last_runs(limit=5)
    assert len(runs) == 2


def test_scheduler_writes_status_after_each_tick(tmp_path, monkeypatch):
    store = SidecarStore(tmp_path / "sidecar.db")
    gh = FakeGitHubClient()
    gh.add(_make_comment(101, _directive_body("d-sched")))
    allowlist = AllowlistConfig(
        allowlisted_repos=frozenset({"neokyhurtado-cmd/traficlab-factory"}),
        allowlisted_authors=frozenset({"astra"}),
    )
    handler = WatcherHandler(
        store=store, gh=gh, allowlist=allowlist,
        evidence_root=str(tmp_path),
        backoff=BackoffPolicy(initial_seconds=0.001),
    )
    scheduler = Scheduler(
        config=SchedulerConfig(interval_seconds=0.01, max_ticks=1, status_path=str(tmp_path / "status.json")),
        handler=handler,
        repos=["neokyhurtado-cmd/traficlab-factory"],
    )
    monkeypatch.setattr("directive_watcher.scheduler.time.sleep", lambda s: None)
    scheduler.run_forever()
    status_path = tmp_path / "status.json"
    data = json.loads(status_path.read_text(encoding="utf-8"))
    assert data["watcher_status"] == "healthy"
    assert data["last_seen_comment_id"] == 101
    assert data["last_result"] == "d-sched"
    # Without a dispatcher, the handler surfaces BLOCKED_EXTERNAL_REAL
    # (Fix #1 from the re-audit). The "DISPATCHED" status is asserted in
    # test_handler_with_dispatch.py.
    assert data["last_result_status"] == "BLOCKED_EXTERNAL_REAL"


def test_scheduler_stops_on_should_stop(tmp_path, monkeypatch):
    store = SidecarStore(tmp_path / "sidecar.db")
    gh = FakeGitHubClient()
    allowlist = AllowlistConfig(
        allowlisted_repos=frozenset({"neokyhurtado-cmd/traficlab-factory"}),
        allowlisted_authors=frozenset({"astra"}),
    )
    handler = WatcherHandler(
        store=store, gh=gh, allowlist=allowlist,
        evidence_root=str(tmp_path),
        backoff=BackoffPolicy(initial_seconds=0.001),
    )
    counter = {"n": 0}

    def should_stop():
        counter["n"] += 1
        return counter["n"] >= 2

    monkeypatch.setattr("directive_watcher.scheduler.time.sleep", lambda s: None)
    scheduler = Scheduler(
        config=SchedulerConfig(interval_seconds=0.01, max_ticks=None, status_path=str(tmp_path / "status.json")),
        handler=handler,
        repos=["neokyhurtado-cmd/traficlab-factory"],
        should_stop=should_stop,
    )
    scheduler.run_forever()
    assert counter["n"] >= 2


def test_scheduler_swallows_tick_errors(tmp_path, monkeypatch):
    store = SidecarStore(tmp_path / "sidecar.db")
    gh = FakeGitHubClient()

    def boom(repo, since_id):
        raise RuntimeError("network down")

    allowlist = AllowlistConfig(
        allowlisted_repos=frozenset({"neokyhurtado-cmd/traficlab-factory"}),
        allowlisted_authors=frozenset({"astra"}),
    )
    handler = WatcherHandler(
        store=store, gh=gh, allowlist=allowlist,
        evidence_root=str(tmp_path),
        backoff=BackoffPolicy(initial_seconds=0.001, max_attempts=1),
    )
    monkeypatch.setattr(gh, "list_comments_since", boom)
    monkeypatch.setattr("directive_watcher.scheduler.time.sleep", lambda s: None)
    scheduler = Scheduler(
        config=SchedulerConfig(interval_seconds=0.01, max_ticks=2, status_path=str(tmp_path / "status.json")),
        handler=handler,
        repos=["neokyhurtado-cmd/traficlab-factory"],
    )
    scheduler.run_forever()  # must NOT raise
    runs = store.last_runs(limit=5)
    assert len(runs) == 2
    assert all(r["status"] == "error" for r in runs)


# --- CLI plumbing ----------------------------------------------------------


def _write_config(tmp_path: Path) -> str:
    p = tmp_path / "config.yaml"
    p.write_text(
        "allowlisted_repos:\n"
        "  - neokyhurtado-cmd/traficlab-factory\n"
        "  - neokyhurtado-cmd/suini\n"
        "allowlisted_authors:\n"
        "  - neokyhurtado-cmd\n"
        "  - astra\n",
        encoding="utf-8",
    )
    return str(p)


def test_load_allowlist_returns_frozensets(tmp_path):
    config_path = _write_config(tmp_path)
    allowlist, repos = load_allowlist(config_path)
    assert "neokyhurtado-cmd/traficlab-factory" in allowlist.allowlisted_repos
    assert "astra" in {a.lower() for a in allowlist.allowlisted_authors}
    assert "neokyhurtado-cmd/suini" in repos


def test_load_allowlist_rejects_non_list(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("allowlisted_repos: not-a-list\nallowlisted_authors: []\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_allowlist(str(p))


def test_parse_args_requires_once_flag(tmp_path):
    """`--once` is the ONLY mode the CLI supports (P0 #2 / SINGLE_POLLING_TRUTH).

    The Phase 3 re-audit (PR #19 comment 5629796729) explicitly required
    that the cli not be a production-reachable scheduling authority —
    the Scheduler loop was removed from this module. Operators who want
    a single diagnostic tick must pass ``--once``; running the cli with
    no scheduler flag is rejected with exit 2 + argparse usage error.
    """
    config_path = _write_config(tmp_path)
    # No --once → argparse rejects with SystemExit(2).
    with pytest.raises(SystemExit):
        parse_args(["--config", config_path])


def test_parse_args_once_flag(tmp_path):
    config_path = _write_config(tmp_path)
    args = parse_args(["--config", config_path, "--once"])
    assert args.once is True


# --- Phase 3 / Objective 1: ENTRYPOINT_REAL_DISPATCH -----------------------
#
# Per the Phase 3 directive (comment 5629246987) + the steered rephrase
# (comment 5629293070), the production CLI must build the handler WITH
# the OrchestratorDispatcher wired in. The previous version constructed
# the handler without `dispatcher=` — which made the production path a
# no-op (the handler fell through to BLOCKED_EXTERNAL_REAL with no
# session bind).
#
# These tests fail today because cli.main() does not pass dispatcher=
# to WatcherHandler and does not write watcher_status.json in --once
# mode. They are the RED that drives the GREEN refactor in cli.py.


def test_cli_once_wires_dispatcher_to_handler(tmp_path, monkeypatch):
    """cli.main() must construct the OrchestratorDispatcher and pass it
    to the WatcherHandler so the production path produces real session
    binds (DISPATCHED), not BLOCKED_EXTERNAL_REAL."""
    config_path = _write_config(tmp_path)
    sidecar = tmp_path / "sidecar.db"
    status_path = tmp_path / "watcher_status.json"

    # Capture what cli.main() constructs.
    captured: dict = {}

    class _SpyDispatcher:
        def __init__(self, *args, **kwargs):
            captured["dispatcher_built"] = True
            captured["dispatcher_args"] = (args, kwargs)

    monkeypatch.setattr(
        "directive_watcher.cli.OrchestratorDispatcher", _SpyDispatcher
    )

    # Capture WatcherHandler kwargs. We patch the class to record
    # what main() passes and then raise so we never run the real tick.
    import directive_watcher.cli as cli_mod
    orig_handler_cls = cli_mod.WatcherHandler

    class _RecordingHandler:
        def __init__(self, *args, **kwargs):
            captured["handler_kwargs"] = dict(kwargs)
            self._orig = orig_handler_cls(*args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._orig, name)

    monkeypatch.setattr("directive_watcher.cli.WatcherHandler", _RecordingHandler)

    # The real handler would call SidecarStore.list_pending_publications
    # in tick(). We don't want to run the real tick — we just want to
    # confirm the wiring. Patch the constructed handler's tick to raise
    # BEFORE any side effects. P0 #3 (ONE_TICK_ONE_RUN_RECORD): the cli
    # now passes run_id to handler.tick(), so the fake must accept it.
    def fake_tick(self, repos, *, run_id=None):
        captured["repos_polled"] = list(repos)
        captured["run_id_passed"] = run_id
        raise RuntimeError("stop-after-wiring")

    monkeypatch.setattr(
        "directive_watcher.handler.WatcherHandler.tick", fake_tick
    )

    rc = cli_mod.main([
        "--config", config_path,
        "--sidecar-db", str(sidecar),
        "--status-path", str(status_path),
        "--once",
    ])
    # tick was rigged to raise — main() catches and returns 1, that's OK.
    assert rc in (0, 1)
    # The dispatcher MUST have been built.
    assert captured.get("dispatcher_built") is True, (
        "cli.main() must construct OrchestratorDispatcher"
    )
    # The handler MUST have been constructed with dispatcher=.
    assert "handler_kwargs" in captured, "WatcherHandler was never constructed"
    handler_kwargs = captured["handler_kwargs"]
    assert "dispatcher" in handler_kwargs, (
        "cli.main() must pass dispatcher= to WatcherHandler — "
        f"got kwargs keys: {sorted(handler_kwargs)}"
    )
    assert handler_kwargs["dispatcher"] is not None, (
        "dispatcher= must be a real OrchestratorDispatcher instance, not None"
    )
    assert captured.get("repos_polled") == [
        "neokyhurtado-cmd/traficlab-factory",
        "neokyhurtado-cmd/suini",
    ]


def test_cli_once_writes_watcher_status_json(tmp_path, monkeypatch):
    """`--once` must write watcher_status.json with the same shape the
    scheduler loop writes. Same snapshot, same source of truth."""
    config_path = _write_config(tmp_path)
    sidecar = tmp_path / "sidecar.db"
    status_path = tmp_path / "watcher_status.json"

    # Stub the dispatcher to avoid spawning real subprocesses.
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

    # Avoid hitting GitHub. Stub FakeGitHubClient so list_comments_since
    # and list_recent_comments return empty lists (no real directives
    # to dispatch).
    from directive_watcher.tests.test_scheduler_cli import _make_comment  # noqa
    from directive_watcher.gh_client import FakeGitHubClient
    monkeypatch.setattr("directive_watcher.cli.GHCLIClient", FakeGitHubClient)

    import directive_watcher.cli as cli_mod
    rc = cli_mod.main([
        "--config", config_path,
        "--sidecar-db", str(sidecar),
        "--status-path", str(status_path),
        "--once",
    ])
    assert rc == 0
    assert status_path.exists(), (
        f"cli --once MUST write watcher_status.json — got no file at {status_path}. "
        "Per Objective 1 of the Phase 3 directive, the documented cron path "
        "must refresh the machine-readable status for War Room consumption."
    )
    data = json.loads(status_path.read_text(encoding="utf-8"))
    # Same shape as Scheduler writes
    assert "watcher_status" in data
    assert "last_poll_at" in data
    assert "last_run_status" in data
    assert "queue_depth" in data
    # --once ran without errors → status is "healthy"
    assert data["watcher_status"] == "healthy", (
        f"--once ran cleanly; expected watcher_status='healthy', got {data['watcher_status']!r}"
    )


# --- build_status fail-honest (Phase 3, Objective 5) -------------------------
#
# Per Astra re-audit objective 5 + the Phase 3 directive:
#   build_status() must DERIVE watcher_status from the last run, never
#   hardcode "healthy". A run that ends in error must surface as
#   "degraded"; a successful run stays "healthy"; no run at all is "unknown".
#
# These tests fail today because build_status() always returns "healthy"
# regardless of last_run_status. They are the RED that drives the GREEN
# refactor in scheduler.py::build_status.


def test_build_status_reflects_degraded_when_last_run_errored(tmp_path):
    """If the last recorded run finished with status='error',
    build_status must NOT lie and report 'healthy' — it must report
    'degraded' so the War Room panel sees reality."""
    store = SidecarStore(tmp_path / "sidecar.db")
    run_id = store.record_run_start(notes="unit")
    store.record_run_finish(run_id, status="error", notes="boom")
    status = build_status(
        store=store,
        last_tick=TickSummary(),
        last_result=None,
        last_run_status="error",
        last_run_finished_at=12345,
    )
    assert status.watcher_status == "degraded", (
        f"build_status must surface last_run_status='error' as 'degraded', "
        f"got {status.watcher_status!r}"
    )
    assert status.last_run_status == "error"


def test_build_status_reflects_healthy_when_last_run_ok(tmp_path):
    """If the last recorded run finished with status='ok',
    build_status must report 'healthy'."""
    store = SidecarStore(tmp_path / "sidecar.db")
    run_id = store.record_run_start(notes="unit")
    store.record_run_finish(run_id, status="ok")
    status = build_status(
        store=store,
        last_tick=TickSummary(),
        last_result=None,
        last_run_status="ok",
        last_run_finished_at=12345,
    )
    assert status.watcher_status == "healthy"
    assert status.last_run_status == "ok"


def test_build_status_reflects_unknown_when_no_run(tmp_path):
    """If no run has ever happened, watcher_status must be 'unknown'."""
    store = SidecarStore(tmp_path / "sidecar.db")
    status = build_status(
        store=store,
        last_tick=None,
        last_result=None,
        last_run_status=None,
        last_run_finished_at=None,
    )
    assert status.watcher_status == "unknown"
