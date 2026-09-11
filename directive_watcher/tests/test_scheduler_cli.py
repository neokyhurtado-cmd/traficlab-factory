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
from directive_watcher.handler import WatcherHandler
from directive_watcher.retry import BackoffPolicy
from directive_watcher.scheduler import Scheduler, SchedulerConfig
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
    assert data["last_result_status"] == "READY_FOR_ASTRA_REAUDIT"


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


def test_parse_args_default_interval_is_5_minutes(tmp_path):
    config_path = _write_config(tmp_path)
    args = parse_args(["--config", config_path])
    assert args.interval_seconds == 300


def test_parse_args_once_flag(tmp_path):
    config_path = _write_config(tmp_path)
    args = parse_args(["--config", config_path, "--once"])
    assert args.once is True
