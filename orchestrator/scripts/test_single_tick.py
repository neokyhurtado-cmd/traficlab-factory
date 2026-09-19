"""
P0 #2 — SINGLE_POLLING_TRUTH.

The Phase 3 re-audit (PR #19 comment 5629796729) flagged that two
production polling authorities still exist independently:

  1. ``orchestrator/scripts/github_poller.main()`` runs the WO
     ingestion pass.
  2. ``directive_watcher.cli`` previously constructed a
     ``Scheduler(...)`` and called ``scheduler.run_forever()`` when
     ``--once`` was not supplied — a second ticking authority.

The frozen architecture (comment 5629246987) requires ONE runtime
tick that triggers BOTH WO ingestion AND directive ingestion. The
unit of "one cron tick" is a single Python invocation, not two.

This file proves the contract end-to-end with a single test that
exercises the ORCH tick as the unit: WO ingestion + directive
ingestion under ONE call.

Implementation choices that drove the test shape:

  - The cron entry point is ``orchestrator/scripts/github_poller.py`` —
    the existing ticket said "the orchestrator cron continues to drive
    github_poller.main". After Phase 3 closeout, that main function
    fans out to BOTH ingestion paths.

  - The directive ingestion under the ORCH tick is delegated to the
    canonical ``WatcherHandler.tick()`` constructed with a real
    ``OrchestratorDispatcher`` (Phase 3 / Objective 1) and an explicit
    ``run_id`` (P0 #3 / ONE_TICK_ONE_RUN_RECORD).

  - ``directive_watcher.cli`` survives but ONLY supports ``--once``
    — it never starts a production loop. The PR body and the open PR
    change adds this restriction with a clear error message. See
    ``test_cli_rejects_no_once`` below.
"""

from __future__ import annotations

import argparse
import inspect
import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


import github_poller  # noqa: E402
import directive_watcher.kanban_primitive  # noqa: E402


class _FakeGH:
    def __init__(self, issues_by_repo: dict | None = None) -> None:
        self.issues_by_repo = issues_by_repo or {}
        self.calls = []

    def list_issues_with_label(self, repo, label, **kw):
        self.calls.append((repo, label))
        return list(self.issues_by_repo.get(repo, []))


@pytest.fixture
def fake_routing(monkeypatch, tmp_path):
    content = (
        "routes:\n"
        "  - repo: neokyhurtado-cmd/suini\n"
        "    product: SUINI\n"
        "    assignee: suini\n"
        "    capabilities: [write]\n"
    )
    p = tmp_path / "routing.yaml"
    p.write_text(content, encoding="utf-8")
    monkeypatch.setenv("HERMES_ROUTING_PATH", str(p))
    monkeypatch.setattr(
        "hermes_cli.profiles.list_profile_names",
        lambda: ["suini"],
        raising=False,
    )
    return p


@pytest.fixture
def fresh_seen_log(monkeypatch, tmp_path):
    log_path = tmp_path / "github_poller_seen.json"
    monkeypatch.setattr(github_poller, "_SEEN_LOG", str(log_path))
    return log_path


def test_orch_tick_invokes_both_wo_and_directive_ingestion(
    fake_routing, fresh_seen_log, monkeypatch
):
    """One ORCH tick (one call to ``github_poller.main()``) must walk
    BOTH the WO ingestion path AND the directive ingestion path
    exactly once each.

    The directive-watcher's handler.tick() is invoked as part of the
    same logical tick; we mock it to record the call without doing
    real ack/result work. The WO ingestion is real (via the injected
    gh wrapper) so we can verify one tick == one kanban dispatch per
    discovered WO.
    """
    fake_gh = _FakeGH(
        issues_by_repo={
            "neokyhurtado-cmd/suini": [
                {
                    "number": 7,
                    "title": "WO under tick",
                    "body": "do this",
                    "labels": [{"name": github_poller.WORK_ORDER_LABEL}],
                    "state": "open",
                },
            ]
        }
    )
    monkeypatch.setattr(
        github_poller, "_gh_client_factory", mock.Mock(return_value=fake_gh)
    )

    # benign kanban primitive (this is the only place subprocess.run lives)
    monkeypatch.setattr(
        directive_watcher.kanban_primitive.subprocess, "run",
        lambda *a, **kw: mock.Mock(returncode=0, stdout=json.dumps({"id": "t_x"}), stderr=""),
    )

    # Spy the directive watcher handler.tick() — the cron entry point
    # MUST invoke it. If github_poller.main() never reaches
    # WatcherHandler.tick, the test fails loudly.
    called_directive = {"count": 0, "args": None}

    import directive_watcher.handler as handler_mod
    orig_init = handler_mod.WatcherHandler.__init__

    def spy_init(self, *args, **kwargs):
        orig_init(self, *args, **kwargs)
        orig_tick = self.tick

        def spy_tick(repos, **kw):
            called_directive["count"] += 1
            called_directive["args"] = (list(repos), dict(kw))
            # Return a benign TickSummary so main() doesn't choke on
            # downstream status assertions.
            from directive_watcher.handler import TickSummary
            return TickSummary(polled_repos=list(repos))

        self.tick = spy_tick

    monkeypatch.setattr(
        handler_mod.WatcherHandler, "__init__", spy_init
    )

    rc = github_poller.main()
    assert rc == 0

    # WO ingestion: one call to list_issues_with_label for the routed repo.
    assert ("neokyhurtado-cmd/suini", github_poller.WORK_ORDER_LABEL) in fake_gh.calls
    # Idem_key for the WO was marked seen.
    seen = json.loads(fresh_seen_log.read_text(encoding="utf-8"))
    assert "github:neokyhurtado-cmd/suini#7" in seen

    # Directive ingestion: ONE call to WatcherHandler.tick under the
    # same logical tick. Phase 3 directive explicitly: "one ORCH
    # tick must invoke both consumers exactly once".
    assert called_directive["count"] == 1, (
        f"orch tick must invoke WatcherHandler.tick() exactly once; got "
        f"{called_directive['count']}. P0 #2 / SINGLE_POLLING_TRUTH."
    )


def test_cli_rejects_running_without_once_flag(tmp_path):
    """``directive_watcher.cli`` MUST reject any invocation that does
    not carry ``--once`` — production paths (cron entries) that omit
    the flag must NOT silently start a separate scheduler loop.

    This is the half of P0 #2 the cron entrypoint doesn't cover: even
    if a copy-pasted crontab row points at ``directive_watcher.cli``
    without ``--once``, argparse refuses with exit 2.
    """
    from directive_watcher.cli import parse_args

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "allowlisted_repos:\n"
        "  - neokyhurtado-cmd/traficlab-factory\n"
        "allowlisted_authors:\n"
        "  - astra\n",
        encoding="utf-8",
    )
    # argparse uses SystemExit(2) on missing required arg.
    with pytest.raises(SystemExit):
        parse_args(["--config", str(config_path)])

    # With --once argparse accepts.
    args = parse_args(["--config", str(config_path), "--once"])
    assert args.once is True


def test_scheduler_class_survives_for_diagnostic_use():
    """``Scheduler`` is preserved for diagnostic use (tests, operator
    inline loops on a workstation) but is NOT wired from
    ``directive_watcher.cli`` as a production authority.

    This test asserts the class still exists and the
    ``run_forever`` method is callable, so the module remains a
    reusable primitive — but proves nothing ties it to production.
    """
    from directive_watcher.scheduler import Scheduler, SchedulerConfig

    cls_src = inspect.getsource(Scheduler)
    # The class itself is fine — it survives. What closes P0 #2 is
    # that ``directive_watcher.cli`` no longer instantiates it.
    assert "run_forever" in cls_src
    # Config still works for direct callers.
    cfg = SchedulerConfig()
    assert cfg.interval_seconds == 300
