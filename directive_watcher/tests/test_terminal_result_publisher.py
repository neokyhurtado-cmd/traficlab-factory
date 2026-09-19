"""Tests for async terminal GitHub result projection."""
from types import SimpleNamespace

from directive_watcher.gh_client import FakeGitHubClient
import directive_watcher.terminal_result_publisher as terminal


class Dispatcher:
    def __init__(self, session):
        self.session = session

    def list_sessions(self):
        return [self.session]


def session(state="DONE", directive_id="canary-1"):
    return SimpleNamespace(
        session_id="sess-1",
        execution_id="exec-1",
        directive_id=directive_id,
        repository="neokyhurtado-cmd/suini",
        issue_number=103,
        target_branch="main",
        kanban_task_id="t-canary",
        assignee="ashley",
        state=state,
        source_comment_id=10,
        head_before="abc",
        head_after="def",
        tests_summary="read-only canary PASS",
        evidence_uri="/evidence/canary",
    )


def physical_evidence(*args, **kwargs):
    return {
        "task_id": "t-canary",
        "assignee": "ashley",
        "task_status": "done",
        "worker_pid": 4242,
        "spawned_at": 100,
        "heartbeat_count": 1,
        "last_heartbeat_at": 110,
        "terminal_kind": "completed",
        "terminal_at": 120,
    }


def test_done_projection_and_replay_dedupe(monkeypatch):
    monkeypatch.setattr(terminal, "_runtime_evidence_for_directive", physical_evidence)
    gh = FakeGitHubClient()
    dispatcher = Dispatcher(session(directive_id="canary-dedupe"))

    first = terminal.publish_terminal_session_results(dispatcher=dispatcher, gh=gh)
    second = terminal.publish_terminal_session_results(dispatcher=dispatcher, gh=gh)

    assert first == {"scanned": 1, "posted": 1, "skipped": 0, "errors": 0}
    assert second == {"scanned": 1, "posted": 0, "skipped": 1, "errors": 0}
    assert len(gh.posted) == 1
    body = gh.posted[0][2]
    assert "STATUS = READY_FOR_ASTRA_REAUDIT" in body
    assert "WORKER_SPAWN_PROVEN=YES" in body
    assert "worker_pid=4242" in body
    assert "heartbeat_count=1" in body


def test_failed_projection_is_terminal_and_honest(monkeypatch):
    monkeypatch.setattr(terminal, "_runtime_evidence_for_directive", lambda *a, **k: {})
    gh = FakeGitHubClient()
    dispatcher = Dispatcher(session(state="FAILED", directive_id="canary-failed"))

    stats = terminal.publish_terminal_session_results(dispatcher=dispatcher, gh=gh)

    assert stats["posted"] == 1
    body = gh.posted[0][2]
    assert "STATUS = BLOCKED_EXTERNAL_REAL" in body
    assert "terminal_session_state=FAILED" in body
    assert "WORKER_SPAWN_PROVEN=NO" in body
