#!/usr/bin/env python3
"""
test_github_poller.py — Unit tests for the github_poller routing pipeline.

Covers WO-ORCH-AUTODISPATCH-02 step 4 ("Refactor github_poller to import
the resolver and eliminate its hard-coded route authority") and step 5
("eligibility/idempotency/double-claim tests; existing running writers
must yield ALREADY_CLAIMED/RECOVERY_REQUIRED, never a second writer").

Run with:
    python -m pytest ~/.hermes/profiles/orchestrator/scripts/test_github_poller.py -v
"""

from __future__ import annotations

import json
import os
import sys
import types

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import github_poller  # noqa: E402
import routing_resolver  # noqa: E402


# --- watched_repos() --------------------------------------------------------

@pytest.fixture
def routing_table_yaml(tmp_path):
    """Write a routing.yaml with several repos in a tmp directory."""
    content = (
        "routes:\n"
        "  - repo: neokyhurtado-cmd/suini\n"
        "    product: SUINI\n"
        "    assignee: suini\n"
        "    capabilities: [write]\n"
        "  - repo: neokyhurtado-cmd/IA-VISION\n"
        "    product: IA-VISION\n"
        "    assignee: ia-vision\n"
        "    capabilities: [write]\n"
        "  - repo: neokyhurtado-cmd/ashley\n"
        "    product: ASHLEY\n"
        "    assignee: default\n"
        "    capabilities: [read]\n"
        "  - repo: neokyhurtado-cmd/orphan\n"
        "    product: ORPHAN\n"
        "    assignee: missing-profile\n"
        "    capabilities: [write]\n"
        "  - product: ASHLEY-FALLBACK\n"
        "    assignee: default\n"
        "    capabilities: [read]\n"
    )
    p = tmp_path / "routing.yaml"
    p.write_text(content, encoding="utf-8")
    return str(p)


@pytest.fixture
def fixture_profiles(tmp_path, monkeypatch):
    """Create profile directories matching the routing table and stub the
    hermes_cli.profiles.list_profile_names() helper to return them.

    The poller walks hermes_cli.profiles._get_profiles_root() (which is
    anchored to the global hermes root, NOT the active profile's
    HERMES_HOME). To keep tests hermetic without touching real profile
    state, we monkeypatch list_profile_names() to return whatever
    directory names we provision under tmp_path.

    Returns the list of provisioned profile names."""
    names = ["suini", "ia-vision", "default"]
    # `missing-profile` is intentionally NOT provisioned — the orphan
    # route should be filtered out by watched_repos().
    monkeypatch.setattr(
        "hermes_cli.profiles.list_profile_names",
        lambda: names,
        raising=False,
    )
    return names


def test_watched_repos_returns_only_repo_routes(
    routing_table_yaml, fixture_profiles, monkeypatch
):
    """watched_repos() should iterate the routing table, filter to entries
    with a `repo:` key, and produce (repo, assignee) tuples in declared order."""
    monkeypatch.setenv("HERMES_ROUTING_PATH", routing_table_yaml)

    repos = github_poller.watched_repos()

    assert ("neokyhurtado-cmd/suini", "suini") in repos
    assert ("neokyhurtado-cmd/IA-VISION", "ia-vision") in repos
    assert ("neokyhurtado-cmd/ashley", "default") in repos


def test_watched_repos_drops_orphan_routes_with_missing_profile(
    routing_table_yaml, fixture_profiles, monkeypatch
):
    """A route whose assignee profile does not exist on disk must be
    filtered out per step 4 fail-closed contract."""
    monkeypatch.setenv("HERMES_ROUTING_PATH", routing_table_yaml)

    repos = github_poller.watched_repos()

    assert ("neokyhurtado-cmd/orphan", "missing-profile") not in repos
    # Sanity: the other repos still come through.
    assert len(repos) == 3


def test_watched_repos_skips_repo_less_fallbacks(
    routing_table_yaml, fixture_profiles, monkeypatch
):
    """Repo-less entries (e.g. ASHLEY-FALLBACK) must NOT appear in
    watched_repos() — the poller polls GitHub, which requires a repo."""
    monkeypatch.setenv("HERMES_ROUTING_PATH", routing_table_yaml)

    repos = github_poller.watched_repos()

    # No entry should have assignee=None (which is what a repo-less fallback
    # would produce if we naively included it).
    for repo, assignee in repos:
        assert repo and assignee, f"empty repo/assignee in {repos}"


def test_watched_repos_returns_empty_when_table_missing(
    tmp_path, fixture_profiles, monkeypatch
):
    """A missing routing table must not crash the poller — return []."""
    monkeypatch.setenv("HERMES_ROUTING_PATH", str(tmp_path / "no_such.yaml"))

    repos = github_poller.watched_repos()
    assert repos == []


def test_watched_repos_returns_empty_when_no_profiles_on_disk(
    routing_table_yaml, tmp_path, monkeypatch
):
    """If the profiles root is empty (or list_profile_names returns []),
    every route is filtered out — the poller cannot route to anything."""
    monkeypatch.setattr(
        "hermes_cli.profiles.list_profile_names",
        lambda: [],
        raising=False,
    )
    monkeypatch.setenv("HERMES_ROUTING_PATH", routing_table_yaml)

    repos = github_poller.watched_repos()
    assert repos == []


# --- create_kanban_task: eligibility / idempotency ---------------------------

class _FakeProc:
    """Stand-in for subprocess.run().CompletedProcess for tests."""

    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


@pytest.fixture
def fresh_seen_log(tmp_path, monkeypatch):
    """Route github_poller's seen-log into a tmp file so each test starts clean."""
    log_path = tmp_path / "github_poller_seen.json"
    monkeypatch.setattr(github_poller, "_SEEN_LOG", str(log_path))
    return log_path


@pytest.fixture
def issue_sample():
    return {
        "number": 42,
        "title": "WO from test",
        "body": "test body",
        "labels": [{"name": "hermes-work-order"}],
        "state": "open",
    }


def test_create_kanban_task_succeeds_when_resolver_allows(
    routing_table_yaml, fixture_profiles, fresh_seen_log, issue_sample,
    monkeypatch
):
    """Happy path: resolver allows → kanban CLI is called once, idem_key
    is marked seen, task_id is returned."""
    monkeypatch.setenv("HERMES_ROUTING_PATH", routing_table_yaml)

    invoked = {"count": 0, "args": None}

    def fake_run(cmd, *args, **kwargs):
        if cmd[:2] == ["hermes", "kanban"]:
            invoked["count"] += 1
            invoked["args"] = cmd
            return _FakeProc(
                stdout=json.dumps({"id": "t_new123"}),
                returncode=0,
            )
        return _FakeProc(stdout="[]", returncode=0)

    monkeypatch.setattr(github_poller.subprocess, "run", fake_run)

    task_id, was_created = github_poller.create_kanban_task(
        issue_sample, "neokyhurtado-cmd/suini", "suini"
    )

    assert task_id == "t_new123"
    assert was_created is True
    assert invoked["count"] == 1
    # The CLI was called with the correct idem_key + assignee from the table.
    assert "--assignee" in invoked["args"]
    assert "suini" in invoked["args"]
    assert "--idempotency-key" in invoked["args"]
    assert "github:neokyhurtado-cmd/suini#42" in invoked["args"]


def test_create_kanban_task_skips_when_already_seen(
    routing_table_yaml, fixture_profiles, fresh_seen_log, issue_sample,
    monkeypatch
):
    """Idempotency: if the (repo, number) pair is already in the seen log,
    no subprocess is invoked and was_created=False."""
    monkeypatch.setenv("HERMES_ROUTING_PATH", routing_table_yaml)

    # Pre-mark the idem_key as seen.
    fresh_seen_log.write_text(
        json.dumps(["github:neokyhurtado-cmd/suini#42"]), encoding="utf-8"
    )

    invoked = {"count": 0}

    def fake_run(cmd, *args, **kwargs):
        invoked["count"] += 1
        return _FakeProc(stdout="[]", returncode=0)

    monkeypatch.setattr(github_poller.subprocess, "run", fake_run)

    task_id, was_created = github_poller.create_kanban_task(
        issue_sample, "neokyhurtado-cmd/suini", "suini"
    )

    assert task_id == ""
    assert was_created is False
    assert invoked["count"] == 0


def test_create_kanban_task_skips_when_resolver_denies(
    routing_table_yaml, fixture_profiles, fresh_seen_log, issue_sample,
    monkeypatch
):
    """Eligibility: if the resolver denies (e.g. repo not in table), the
    poller must NOT call the kanban CLI. was_created=False, no task_id."""
    monkeypatch.setenv("HERMES_ROUTING_PATH", routing_table_yaml)

    invoked = {"count": 0}

    def fake_run(cmd, *args, **kwargs):
        invoked["count"] += 1
        return _FakeProc(stdout="[]", returncode=0)

    monkeypatch.setattr(github_poller.subprocess, "run", fake_run)

    # Repo that's NOT in the routing table → resolver denies.
    task_id, was_created = github_poller.create_kanban_task(
        issue_sample, "neokyhurtado-cmd/unknown", "orchestrator"
    )

    assert task_id == ""
    assert was_created is False
    assert invoked["count"] == 0


def test_create_kanban_task_skips_when_routing_table_assignee_drifts(
    routing_table_yaml, fixture_profiles, fresh_seen_log, issue_sample,
    monkeypatch
):
    """Double-claim guard: if the poller's intended assignee disagrees with
    what the routing table currently says, we drop the issue rather than
    claim it under a stale assignee (step 5 — never a second writer)."""
    monkeypatch.setenv("HERMES_ROUTING_PATH", routing_table_yaml)

    invoked = {"count": 0}

    def fake_run(cmd, *args, **kwargs):
        invoked["count"] += 1
        return _FakeProc(stdout="[]", returncode=0)

    monkeypatch.setattr(github_poller.subprocess, "run", fake_run)

    # The poller thinks the assignee is `orchestrator`, but the routing
    # table says `suini`. Without the guard, the kanban CLI would create
    # a task owned by the wrong profile (silent reassignment — FORBIDDEN).
    task_id, was_created = github_poller.create_kanban_task(
        issue_sample, "neokyhurtado-cmd/suini", "orchestrator"
    )

    assert task_id == ""
    assert was_created is False
    assert invoked["count"] == 0


def test_create_kanban_task_marks_seen_after_creation(
    routing_table_yaml, fixture_profiles, fresh_seen_log, issue_sample,
    monkeypatch
):
    """After a successful create, the idem_key must be persisted to the
    seen-log so the next tick is silent (idempotency across cron ticks)."""
    monkeypatch.setenv("HERMES_ROUTING_PATH", routing_table_yaml)

    def fake_run(cmd, *args, **kwargs):
        return _FakeProc(stdout=json.dumps({"id": "t_x"}), returncode=0)

    monkeypatch.setattr(github_poller.subprocess, "run", fake_run)

    github_poller.create_kanban_task(
        issue_sample, "neokyhurtado-cmd/suini", "suini"
    )

    seen = json.loads(fresh_seen_log.read_text(encoding="utf-8"))
    assert "github:neokyhurtado-cmd/suini#42" in seen


def test_create_kanban_task_second_call_same_idem_key_is_silent(
    routing_table_yaml, fixture_profiles, fresh_seen_log, issue_sample,
    monkeypatch
):
    """Two consecutive calls with the same issue must produce exactly one
    subprocess call to `hermes kanban create`. The second call short-circuits
    on the seen-log entry — no kanban CLI invocation, no stdout line."""
    monkeypatch.setenv("HERMES_ROUTING_PATH", routing_table_yaml)

    invoked = {"count": 0}

    def fake_run(cmd, *args, **kwargs):
        if cmd[:2] == ["hermes", "kanban"]:
            invoked["count"] += 1
            return _FakeProc(stdout=json.dumps({"id": "t_x"}), returncode=0)
        return _FakeProc(stdout="[]", returncode=0)

    monkeypatch.setattr(github_poller.subprocess, "run", fake_run)

    github_poller.create_kanban_task(
        issue_sample, "neokyhurtado-cmd/suini", "suini"
    )
    github_poller.create_kanban_task(
        issue_sample, "neokyhurtado-cmd/suini", "suini"
    )

    assert invoked["count"] == 1
