"""Tests for the watcher handler when wired to the orchestrator dispatcher.

This module is the Fix #1 / Fix #8 end-to-end test: a directive comment
goes in, the watcher parses it, the allowlist admits it, the claim lands,
the handler calls the dispatcher, the dispatcher persists a session and
invokes `hermes kanban create`, the handler emits a RESULT with the
session_id + kanban_task_id bound, and the orchestrator end-to-end
contract is satisfied.

The hermes CLI subprocess is mocked (no live hermes daemon in tests).
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from directive_watcher.allowlist import AllowlistConfig
from directive_watcher.gh_client import FakeGitHubClient, RemoteComment
from directive_watcher.handler import WatcherHandler
from directive_watcher.orch_dispatch import OrchestratorDispatcher
from directive_watcher.sidecar_store import RESULT_DISPATCHED
from directive_watcher.retry import BackoffPolicy
from directive_watcher.sidecar_store import SidecarStore


# ---------- helpers ---------------------------------------------------------


def _make_comment(cid: int, body: str, author: str = "astra") -> RemoteComment:
    return RemoteComment(
        id=cid,
        author=author,
        body=body,
        url=f"https://github.com/r/o/issues/18#issuecomment-{cid}",
        issue_number=18,
    )


def _directive_body(directive_id: str = "d-1") -> str:
    return (
        "[ASTRA_DIRECTIVE:v1]\n"
        "ACTION = CONTINUE\n"
        "REPOSITORY = neokyhurtado-cmd/traficlab-factory\n"
        "ISSUE = 18\n"
        "TARGET_BRANCH = AUTO_FROM_ISSUE_CONTEXT\n"
        "EXPECTED_HEAD = NONE\n"
        "SCOPE = test scope\n"
        "AUTO_NEXT_SAFE_GATE = YES\n"
        "REQUIRES_HUMAN_GO_REAL = NO\n"
        f"DIRECTIVE_ID = {directive_id}\n"
    )


@pytest.fixture
def routing_table(tmp_path: Path) -> Path:
    p = tmp_path / "routing.yaml"
    p.write_text(
        "routes:\n"
        "  - repo: neokyhurtado-cmd/traficlab-factory\n"
        "    product: ORCHESTRATION\n"
        "    assignee: hermes-director\n"
        "    capabilities: [write]\n"
        "    max_runtime_seconds: 3600\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture
def env_with_dispatcher(tmp_path: Path, routing_table: Path):
    store = SidecarStore(tmp_path / "sidecar.db")
    gh = FakeGitHubClient()
    # Seed (repo, "main") for legacy EXPECTED_HEAD=NONE /
    # TARGET_BRANCH=AUTO_FROM_ISSUE_CONTEXT sentinels.
    gh.set_branch_head(
        "neokyhurtado-cmd/traficlab-factory", "main",
        "1111111111111111111111111111111111111111",
    )
    allowlist = AllowlistConfig(
        allowlisted_repos=frozenset({"neokyhurtado-cmd/traficlab-factory"}),
        allowlisted_authors=frozenset({"astra"}),
    )
    dispatcher = OrchestratorDispatcher(
        session_log=str(tmp_path / "sessions.jsonl"),
        routing_table_path=str(routing_table),
    )
    handler = WatcherHandler(
        store=store,
        gh=gh,
        allowlist=allowlist,
        evidence_root=str(tmp_path),
        dispatcher=dispatcher,
        backoff=BackoffPolicy(initial_seconds=0.001, max_attempts=2),
    )
    return {
        "store": store,
        "gh": gh,
        "allowlist": allowlist,
        "handler": handler,
        "dispatcher": dispatcher,
        "tmp_path": tmp_path,
    }


# 1. End-to-end: comment -> dispatcher -> session + RESULT with bound ids
def test_handler_wired_to_dispatcher_emits_dispatched_with_session_bind(
    env_with_dispatcher,
):
    """Astra's "doorbell but no one opens" requirement (Fix #1).

    The RESULT body posted back to GitHub must carry:
      - STATUS = DISPATCHED (NOT READY_FOR_ASTRA_REAUDIT, which is reserved
        for the future DONE case)
      - The session_id and kanban_task_id from the session registry

    If any of those are missing, the watcher is lying about executing.
    """
    gh = env_with_dispatcher["gh"]
    handler = env_with_dispatcher["handler"]
    dispatcher = env_with_dispatcher["dispatcher"]
    gh.add(_make_comment(101, _directive_body("d-e2e")))

    fake_kanban = '{"id": "t_e2e_real", "created_at": 1700000000}'
    with mock.patch(
        "directive_watcher.kanban_primitive.subprocess.run",
        return_value=mock.Mock(returncode=0, stdout=fake_kanban, stderr=""),
    ) as m_run:
        summary = handler.tick(["neokyhurtado-cmd/traficlab-factory"])

    assert summary.directives_claimed == 1
    assert summary.directives_failed == 0
    # Subprocess was invoked exactly once for the kanban dispatch.
    assert m_run.call_count == 1
    # Two posts on the wire: ACK + RESULT.
    assert len(gh.posted) == 2
    ack_body, result_body = gh.posted[0][2], gh.posted[1][2]
    assert "[HERMES_ACK:v1]" in ack_body
    assert "[HERMES_RESULT:v1]" in result_body
    assert "STATUS = DISPATCHED" in result_body
    # The result must carry the bound ids, not placeholders.
    sessions = dispatcher.list_sessions()
    assert len(sessions) == 1
    session_id = sessions[0].session_id
    kanban_task_id = sessions[0].kanban_task_id
    assert kanban_task_id == "t_e2e_real"
    assert f"session_id={session_id}" in result_body
    assert f"kanban_task_id={kanban_task_id}" in result_body
    # The store recorded DISPATCHED (not READY).
    rec = env_with_dispatcher["store"].get_processed("d-e2e")
    assert rec["result_status"] == "DISPATCHED"


# 2. Dispatcher failure → BLOCKED_EXTERNAL_REAL (NOT READY)
def test_handler_when_dispatcher_fails_emits_blocked(
    env_with_dispatcher,
):
    gh = env_with_dispatcher["gh"]
    handler = env_with_dispatcher["handler"]
    gh.add(_make_comment(102, _directive_body("d-fail")))

    with mock.patch(
        "directive_watcher.kanban_primitive.subprocess.run",
        return_value=mock.Mock(returncode=1, stdout="", stderr="kanban: boom"),
    ):
        summary = handler.tick(["neokyhurtado-cmd/traficlab-factory"])

    assert summary.directives_claimed == 1
    assert len(gh.posted) == 2  # ACK still goes out, then RESULT
    result_body = gh.posted[1][2]
    assert "STATUS = BLOCKED_EXTERNAL_REAL" in result_body
    # No session was created when the dispatcher failed.
    assert env_with_dispatcher["dispatcher"].list_sessions() == []


# 3. Idempotent: second tick with the same comment sees already-claimed
def test_handler_does_not_redispatch_already_claimed(env_with_dispatcher):
    gh = env_with_dispatcher["gh"]
    handler = env_with_dispatcher["handler"]
    dispatcher = env_with_dispatcher["dispatcher"]
    gh.add(_make_comment(103, _directive_body("d-idem")))

    fake_kanban = '{"id": "t_idem", "created_at": 1700000000}'
    with mock.patch(
        "directive_watcher.kanban_primitive.subprocess.run",
        return_value=mock.Mock(returncode=0, stdout=fake_kanban, stderr=""),
    ) as m_run:
        handler.tick(["neokyhurtado-cmd/traficlab-factory"])
        handler.tick(["neokyhurtado-cmd/traficlab-factory"])

    # Only one dispatch subprocess invocation (idempotent by directive_id).
    assert m_run.call_count == 1
    sessions = dispatcher.list_sessions()
    assert len(sessions) == 1
