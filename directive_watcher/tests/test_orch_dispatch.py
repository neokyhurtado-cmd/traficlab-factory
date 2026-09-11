"""Tests for the orchestrator dispatch seam (Fix #1, #7, #8 from Astra re-audit).

The watcher's default `execution_fn` must actually wake a real work-session
through the existing orchestrator routing + kanban path. It must NOT emit
`READY_FOR_ASTRA_REAUDIT` until delegated execution has produced a real
result — emitting READY without execution is the "doorbell but no one
opens" failure the re-audit called out.

Tests in this module exercise `orch_dispatch.dispatch()` directly. The
integration with the live routing_resolver + kanban subprocess is mocked
so the tests stay hermetic.
"""
from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from directive_watcher.directive_parser import parse_directive
from directive_watcher.orch_dispatch import (
    DispatchRequest,
    DispatchResult,
    OrchestratorDispatcher,
    DispatchError,
    SessionAlreadyExistsError,
)


# ---------- helpers ---------------------------------------------------------


@pytest.fixture
def routing_table(tmp_path: Path) -> Path:
    """Write a minimal routing.yaml in tmp_path so the resolver can read it.

    The directive bodies in these tests use
    ``neokyhurtado-cmd/traficlab-factory`` so we map that repo to
    ``hermes-director`` here.
    """
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


def _directive_body(
    *,
    directive_id: str = "d-1",
    repository: str = "neokyhurtado-cmd/traficlab-factory",
    issue: int = 18,
    target_branch: str = "AUTO_FROM_ISSUE_CONTEXT",
    expected_head: str = "NONE",
    requires_hgr: bool = False,
    action: str = "CONTINUE",
) -> str:
    return (
        "[ASTRA_DIRECTIVE:v1]\n"
        f"ACTION = {action}\n"
        f"REPOSITORY = {repository}\n"
        f"ISSUE = {issue}\n"
        f"TARGET_BRANCH = {target_branch}\n"
        f"EXPECTED_HEAD = {expected_head}\n"
        "SCOPE = test scope\n"
        "AUTO_NEXT_SAFE_GATE = YES\n"
        f"REQUIRES_HUMAN_GO_REAL = {'YES' if requires_hgr else 'NO'}\n"
        f"DIRECTIVE_ID = {directive_id}\n"
    )


def _make_dispatcher(tmp_path: Path, routing_table: Path) -> OrchestratorDispatcher:
    return OrchestratorDispatcher(
        session_log=str(tmp_path / "sessions.jsonl"),
        routing_table_path=str(routing_table),
    )


# 1. dispatch creates a real session (not just READY status)
def test_dispatch_creates_real_session_record(tmp_path: Path, routing_table: Path):
    """The watcher must wake a real session record through the dispatch seam.

    A DispatchResult without a session_id would be the "doorbell but no one
    opens" failure the re-audit flagged. The dispatcher must register the
    session BEFORE returning success.
    """
    dispatcher = _make_dispatcher(tmp_path, routing_table)
    d = parse_directive(_directive_body(directive_id="d-001"))

    fake_kanban_output = '{"id": "t_fake_001", "created_at": 1700000000}'
    with mock.patch(
        "directive_watcher.kanban_primitive.subprocess.run",
        return_value=mock.Mock(returncode=0, stdout=fake_kanban_output, stderr=""),
    ):
        result = dispatcher.dispatch(
            DispatchRequest(
                directive=d,
                source_comment_id=101,
                execution_id="exec-test-001",
            )
        )

    assert isinstance(result, DispatchResult)
    assert result.kanban_task_id == "t_fake_001"
    # CRITICAL: dispatch must mint a non-empty session_id. An empty
    # session_id is exactly the "doorbell but no one opens" failure
    # the Astra re-audit flagged. We assert on the registry directly,
    # not on the in-memory mirror — so the test fails even if a future
    # refactor hides the bug behind a synthetic id.
    sessions = dispatcher.list_sessions()
    assert len(sessions) >= 1, "dispatch must persist a session record"
    assert sessions[0].session_id
    assert sessions[0].session_id == result.session_id
    assert sessions[0].session_id != ""
    assert sessions[0].directive_id == "d-001"
    assert sessions[0].state == "DISPATCHED"
    assert sessions[0].created_at > 0


# 2. Dispatch failure must NOT emit ready status
def test_dispatch_failure_raises(tmp_path: Path, routing_table: Path):
    """If the kanban subprocess fails, dispatcher must raise.

    The handler translates DispatchError into BLOCKED_EXTERNAL_REAL (or
    HUMAN_GO_REAL_REQUIRED for protected directives). READY_FOR_ASTRA_REAUDIT
    must be reserved for cases where delegated work actually completed.
    """
    dispatcher = _make_dispatcher(tmp_path, routing_table)
    d = parse_directive(_directive_body(directive_id="d-002"))

    with mock.patch(
        "directive_watcher.kanban_primitive.subprocess.run",
        return_value=mock.Mock(returncode=1, stdout="", stderr="kanban: boom"),
    ):
        with pytest.raises(DispatchError):
            dispatcher.dispatch(
                DispatchRequest(
                    directive=d,
                    source_comment_id=202,
                    execution_id="exec-test-002",
                )
            )


# 3. Idempotent dispatch
def test_dispatch_is_idempotent_per_directive_id(
    tmp_path: Path, routing_table: Path
):
    dispatcher = _make_dispatcher(tmp_path, routing_table)
    d = parse_directive(_directive_body(directive_id="d-003"))

    fake_kanban_output = '{"id": "t_fake_003", "created_at": 1700000000}'
    with mock.patch(
        "directive_watcher.kanban_primitive.subprocess.run",
        return_value=mock.Mock(returncode=0, stdout=fake_kanban_output, stderr=""),
    ) as m_run:
        first = dispatcher.dispatch(
            DispatchRequest(directive=d, source_comment_id=303, execution_id="exec-test-003")
        )
        second = dispatcher.dispatch(
            DispatchRequest(directive=d, source_comment_id=303, execution_id="exec-test-003")
        )

    assert first.session_id == second.session_id
    assert first.kanban_task_id == second.kanban_task_id
    assert m_run.call_count == 1, (
        f"idempotent dispatch must call subprocess exactly once; got {m_run.call_count}"
    )


# 4. Sessions survive restart
def test_sessions_survive_restart(tmp_path: Path, routing_table: Path):
    dispatcher_a = _make_dispatcher(tmp_path, routing_table)
    d = parse_directive(_directive_body(directive_id="d-004"))

    fake_kanban_output = '{"id": "t_fake_004", "created_at": 1700000000}'
    with mock.patch(
        "directive_watcher.kanban_primitive.subprocess.run",
        return_value=mock.Mock(returncode=0, stdout=fake_kanban_output, stderr=""),
    ):
        dispatcher_a.dispatch(
            DispatchRequest(directive=d, source_comment_id=404, execution_id="exec-test-004")
        )

    dispatcher_b = _make_dispatcher(tmp_path, routing_table)
    sessions = dispatcher_b.list_sessions()
    assert len(sessions) == 1
    assert sessions[0].directive_id == "d-004"


# 5. Concurrent sessions are independent
def test_concurrent_directives_create_independent_sessions(
    tmp_path: Path, routing_table: Path
):
    dispatcher = _make_dispatcher(tmp_path, routing_table)
    d1 = parse_directive(_directive_body(directive_id="d-A"))
    d2 = parse_directive(_directive_body(directive_id="d-B", issue=42))

    fake_kanban_output = '{"id": "t_fake_X", "created_at": 1700000000}'
    with mock.patch(
        "directive_watcher.kanban_primitive.subprocess.run",
        return_value=mock.Mock(returncode=0, stdout=fake_kanban_output, stderr=""),
    ):
        r1 = dispatcher.dispatch(DispatchRequest(d1, 101, "exec-A"))
        r2 = dispatcher.dispatch(DispatchRequest(d2, 102, "exec-B"))

    assert r1.session_id != r2.session_id
    sessions = {s.directive_id: s for s in dispatcher.list_sessions()}
    assert "d-A" in sessions and "d-B" in sessions


# 6. Same directive_id with DIFFERENT execution_id → SessionAlreadyExistsError
def test_same_directive_different_execution_conflicts(
    tmp_path: Path, routing_table: Path
):
    dispatcher = _make_dispatcher(tmp_path, routing_table)
    d = parse_directive(_directive_body(directive_id="d-conflict"))

    fake_kanban_output = '{"id": "t_fake_Y", "created_at": 1700000000}'
    with mock.patch(
        "directive_watcher.kanban_primitive.subprocess.run",
        return_value=mock.Mock(returncode=0, stdout=fake_kanban_output, stderr=""),
    ):
        dispatcher.dispatch(
            DispatchRequest(directive=d, source_comment_id=1, execution_id="exec-A")
        )
        with pytest.raises(SessionAlreadyExistsError):
            dispatcher.dispatch(
                DispatchRequest(directive=d, source_comment_id=1, execution_id="exec-B")
            )


# 7. Session state transitions
def test_session_state_transitions(tmp_path: Path, routing_table: Path):
    dispatcher = _make_dispatcher(tmp_path, routing_table)
    d = parse_directive(_directive_body(directive_id="d-trans"))

    fake_kanban_output = '{"id": "t_fake_T", "created_at": 1700000000}'
    with mock.patch(
        "directive_watcher.kanban_primitive.subprocess.run",
        return_value=mock.Mock(returncode=0, stdout=fake_kanban_output, stderr=""),
    ):
        r = dispatcher.dispatch(
            DispatchRequest(directive=d, source_comment_id=1, execution_id="exec-T")
        )

    # DISPATCHED → RUNNING
    dispatcher.update_session(r.session_id, state="RUNNING")
    assert dispatcher.get_session(r.session_id).state == "RUNNING"

    # RUNNING → DONE with head_after + tests
    dispatcher.update_session(
        r.session_id,
        state="DONE",
        head_after="abcd1234",
        tests_summary="12/12 passed",
        evidence_uri="/tmp/evidence/d-trans",
    )
    s = dispatcher.get_session(r.session_id)
    assert s.state == "DONE"
    assert s.head_after == "abcd1234"
    assert s.tests_summary == "12/12 passed"
    assert s.evidence_uri == "/tmp/evidence/d-trans"


# 8. Invalid state rejected
def test_invalid_session_state_rejected(tmp_path: Path, routing_table: Path):
    dispatcher = _make_dispatcher(tmp_path, routing_table)
    d = parse_directive(_directive_body(directive_id="d-bad-state"))

    fake_kanban_output = '{"id": "t_bad", "created_at": 1700000000}'
    with mock.patch(
        "directive_watcher.kanban_primitive.subprocess.run",
        return_value=mock.Mock(returncode=0, stdout=fake_kanban_output, stderr=""),
    ):
        r = dispatcher.dispatch(
            DispatchRequest(directive=d, source_comment_id=1, execution_id="exec-BS")
        )

    # The session exists; mutating it with a garbage state must raise ValueError.
    with pytest.raises(ValueError):
        dispatcher.update_session(r.session_id, state="GIBBERING")


# 9. Routing deny raises DispatchError
def test_routing_deny_raises(tmp_path: Path):
    # routing table that does NOT contain our test repo
    rt = tmp_path / "routing.yaml"
    rt.write_text("routes: []\n", encoding="utf-8")
    dispatcher = OrchestratorDispatcher(
        session_log=str(tmp_path / "sessions.jsonl"),
        routing_table_path=str(rt),
    )
    d = parse_directive(_directive_body(directive_id="d-deny"))
    with pytest.raises(DispatchError):
        dispatcher.dispatch(
            DispatchRequest(directive=d, source_comment_id=1, execution_id="exec-D")
        )


# 10. active_sessions JSON shape (foundation for War Room)
def test_active_sessions_json_shape(tmp_path: Path, routing_table: Path):
    """Session records must serialise to a War-Room-friendly shape.

    No UI yet, but the JSON shape is the contract the future panel will
    consume. We test it explicitly here so the contract doesn't drift.
    """
    import json

    dispatcher = _make_dispatcher(tmp_path, routing_table)
    d = parse_directive(_directive_body(directive_id="d-shape"))

    fake_kanban_output = '{"id": "t_shape", "created_at": 1700000000}'
    with mock.patch(
        "directive_watcher.kanban_primitive.subprocess.run",
        return_value=mock.Mock(returncode=0, stdout=fake_kanban_output, stderr=""),
    ):
        dispatcher.dispatch(
            DispatchRequest(directive=d, source_comment_id=42, execution_id="exec-S")
        )

    sessions = dispatcher.list_sessions()
    assert len(sessions) == 1
    blob = json.loads(sessions[0].to_json())
    expected_keys = {
        "session_id", "execution_id", "directive_id", "repository",
        "issue_number", "target_branch", "kanban_task_id", "assignee",
        "state", "source_comment_id", "head_before", "head_after",
        "tests_summary", "evidence_uri", "block_reason",
        "requires_human_go_real", "created_at", "updated_at",
    }
    assert expected_keys.issubset(set(blob.keys())), (
        f"missing keys: {expected_keys - set(blob.keys())}"
    )
