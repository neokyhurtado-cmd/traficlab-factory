"""
P0 #1 — github_poller is runtime-broken on the real WO path.

The Phase 3 re-audit (PR #19 comment 5629796729) flagged that
``github_poller.gh_list_work_orders()`` still calls ``subprocess.run()``
directly, even though the Phase 3 single-kanban-primitive refactor
removed ``import subprocess`` from the module. The result is a
deterministic ``NameError: name 'subprocess' is not defined`` the
moment a real cron tick actually invokes the function — the test suite
mocked the kanban primitive's subprocess and never executed
``gh_list_work_orders`` / ``main()``, so the latent bug survived.

The fix: route ``gh_list_work_orders()`` through a wrapper that owns
the subprocess call (NOT the kanban primitive — that one is for
``hermes kanban create`` only). The wrapper is the existing
``GHCLIClient`` abstraction in ``directive_watcher/gh_client.py``,
which is already what the directive watcher's tick path uses.

This test asserts:
  1. github_poller does NOT call subprocess.run() directly anywhere
     (static source guard — extends the kanban-primitive idiom to the
     gh subprocess call too, but ONLY for the github_poller module —
     other modules are free to spawn their own subprocesses).
  2. github_poller.main() executes a real tick path without NameError
     when the subprocess layer is mocked at the wrapper level (NOT at
     the subprocess module level — that's the symptom Phase 3 missed).
"""

from __future__ import annotations

import importlib
import inspect
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

# Ensure github_poller + its deps are importable.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# --- Module imports -----------------------------------------------------------


import github_poller  # noqa: E402
import directive_watcher.gh_client  # noqa: E402


# --- 1. Static guard: github_poller does NOT call subprocess.run directly ----


GITHUB_POLLER_FILE = _REPO_ROOT / "orchestrator" / "scripts" / "github_poller.py"


def test_github_poller_does_not_call_subprocess_run_directly():
    """github_poller MUST go through a wrapper (GHCLIClient or a
    dedicated gh wrapper) for its subprocess calls — NEVER
    ``subprocess.run()`` directly. Same bite pattern as the
    kanban-primitive guard (test_kanban_primitive.py).

    The re-audit (comment 5629796729) flagged this: the kanban
    primitive refactor removed ``import subprocess`` from this file,
    but ``gh_list_work_orders()`` and friends still call
    ``subprocess.run()`` — NameError waiting to happen on a real cron
    tick. We catch that here.
    """
    forbidden = [
        # Top-level ``subprocess.run(`` or ``subprocess.Popen(`` etc.
        # Catch any method access on the subprocess module.
        re.compile(r"\bsubprocess\.(run|Popen|call|check_call|check_output)\b"),
        # ``import subprocess`` (any flavour).
        re.compile(r"^\s*import\s+subprocess\b", re.MULTILINE),
        re.compile(r"^\s*from\s+subprocess\b", re.MULTILINE),
    ]
    src = GITHUB_POLLER_FILE.read_text(encoding="utf-8").splitlines()
    hits: list[tuple[int, str]] = []
    for i, line in enumerate(src, start=1):
        s = line.lstrip()
        if s.startswith("#") or s.startswith('"""') or s.startswith("'''"):
            continue  # Skip pure comments; only inspect code.
        for pat in forbidden:
            if pat.search(line):
                hits.append((i, line.rstrip()))
    assert not hits, (
        "github_poller.py calls subprocess directly — this is the P0 #1 "
        "NameError bug from the Phase 3 re-audit (PR #19 comment 5629796729). "
        "Route every subprocess invocation through a dedicated gh wrapper "
        "(not the kanban primitive — that's reserved for `hermes kanban create`). "
        "Hits:\n"
        + "\n".join(f"  L{i}  {line}" for i, line in hits)
    )


# --- 2. Behavioural: github_poller.main() runs without NameError --------------
#
# We mock the gh wrapper (NOT the subprocess module) and assert the full
# path: routing -> fetch WOs -> dispatch_to_kanban -> mark_seen works.
# This is the bite test the original Phase 3 suite lacked.


class _FakeGH:
    """Stand-in for the gh wrapper. Records what github_poller asked for
    and returns canned responses — same shape the production wrapper
    would return.
    """

    def __init__(self, issues_by_repo: dict[str, list[dict]] | None = None) -> None:
        self.issues_by_repo = issues_by_repo or {}
        self.calls: list[tuple[str, str]] = []

    def list_issues_with_label(self, repo: str, label: str, state: str = "open"):
        self.calls.append((repo, label))
        return list(self.issues_by_repo.get(repo, []))


@pytest.fixture
def fake_routing(monkeypatch, tmp_path):
    """A trivial routing.yaml so watched_repos() finds one repo."""
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
    # On Windows the default-home fallback of ``_on_disk_profiles``
    # uses ``os.path.expanduser('~/.hermes')`` which ignores the
    # HOME / USERPROFILE env vars baked at install time. Bypass the
    # fallback entirely by providing an injectable profiles set —
    # same idiom the existing tests use (``fixture_profiles``).
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


def test_github_poller_main_path_runs_without_nameerror(
    fake_routing, fresh_seen_log, monkeypatch
):
    """One ORCH tick must walk WO ingestion without ever touching the
    subprocess module. github_poller.main() runs the canonical path:
    routing -> fetch WOs -> dispatch_to_kanban -> mark_seen, AND the
    directive ingestion under the SAME tick (P0 #2 / SINGLE_POLLING_TRUTH).

    The suite mocks both wrappers (kanban primitive stays mocked at
    subprocess level because it is the only real subprocess home;
    the gh wrappers are mocked at the wrapper level — NOT at the
    subprocess module level — so a sibling subprocess call inside
    github_poller would surface immediately.
    """
    fake_gh = _FakeGH(
        issues_by_repo={
            "neokyhurtado-cmd/suini": [
                {
                    "number": 1,
                    "title": "Test WO",
                    "body": "test body",
                    "labels": [{"name": github_poller.WORK_ORDER_LABEL}],
                    "state": "open",
                }
            ]
        }
    )

    # Inject the wrapper factory so ``gh_list_work_orders`` constructs
    # our fake client instead of the real one. github_poller reads this
    # factory at module-import time (staticmethod), so we have to patch
    # the factory itself, not a per-call instance.
    fake_factory = mock.Mock(return_value=fake_gh)
    monkeypatch.setattr(github_poller, "_gh_client_factory", fake_factory)

    # The directive ingestion path uses a different gh wrapper
    # (GHCLIClient — comments for the directive side). Mock it with
    # the existing in-memory fake so no real ``gh api`` call runs.
    from directive_watcher.gh_client import FakeGitHubClient
    monkeypatch.setattr(
        "directive_watcher.gh_client.GHCLIClient", FakeGitHubClient
    )

    # The dispatcher's kanban call would invoke ``hermes kanban create``
    # — replace it with a benign stub so no subprocess spawns here.
    monkeypatch.setattr(
        github_poller,
        "dispatch_to_kanban",
        lambda **kw: "t_stub",
    )

    # The kanban primitive ALSO needs its dispatch_to_kanban mocked
    # because the directive ingestion path's dispatcher delegates to
    # it. Both call sites use ``idempotency_key=`` as the kwarg name.
    import directive_watcher.kanban_primitive as kp_mod
    monkeypatch.setattr(
        kp_mod, "dispatch_to_kanban",
        lambda **kw: "t_stub_primitive",
    )

    # If github_poller is still importing/using subprocess anywhere,
    # this mock.patch of subprocess.run is a controlled tripwire — a
    # stray ``subprocess.run`` call inside github_poller would either
    # bypass our wrapper OR raise NameError because the module no
    # longer imports subprocess. Either way, the BITE failure mode
    # shows up here as a clear AssertionError.
    invoked_subprocess = {"count": 0}

    def forbidden(*a, **kw):
        invoked_subprocess["count"] += 1
        raise AssertionError(
            "github_poller invoked subprocess.run directly — P0 #1 violation. "
            "Route the call through the gh wrapper instead. See PR #19 "
            "comment 5629796729."
        )

    monkeypatch.setattr(subprocess, "run", forbidden)

    # The kanban primitive is permitted to use subprocess; we mock it
    # at the SAME level the previous tests did — by replacing its
    # ``subprocess.run`` to a benign stub.
    def benign_kanban_run(cmd, *args, **kwargs):
        return mock.Mock(
            returncode=0,
            stdout=json.dumps({"id": "t_main_test"}),
            stderr="",
        )

    monkeypatch.setattr(
        directive_watcher.kanban_primitive.subprocess, "run", benign_kanban_run
    )

    # Run one cron tick.
    rc = github_poller.main()
    assert rc == 0, f"github_poller.main() must return 0; got {rc}"

    assert invoked_subprocess["count"] == 0, (
        "github_poller.main() invoked subprocess.run directly — the tripwire "
        "caught it. Route the call through a gh wrapper."
    )
    assert ("neokyhurtado-cmd/suini", github_poller.WORK_ORDER_LABEL) in fake_gh.calls, (
        "github_poller.main() did not invoke the gh wrapper to list WOs for "
        "the routed repo. Wiring is broken."
    )
    # The WO was dispatched: idem_key was marked seen in the seen-log.
    seen = json.loads(fresh_seen_log.read_text(encoding="utf-8"))
    assert "github:neokyhurtado-cmd/suini#1" in seen
