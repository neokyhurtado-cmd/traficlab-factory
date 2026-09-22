from __future__ import annotations

import json

from directive_watcher.directive_parser import Directive
from directive_watcher.orca_auto_wake import (
    OrcaAutoWakeBridge,
    OrcaWakeResult,
    directive_requests_orca,
)
from directive_watcher.orch_dispatch import (
    DispatchRequest,
    OrchestratorDispatcher,
    SESSION_STATE_RUNNING,
)


def directive(*, did="d-1", scope="EXECUTION_TARGET=ORCA; ORCA_RUN_REQUIRED=YES"):
    return Directive(
        action="BUILD",
        repository="neokyhurtado-cmd/IA-VISION",
        issue=244,
        target_branch="feat/trafficlab-premium-cabin-v1",
        expected_head="abc123",
        scope=scope,
        auto_next_safe_gate=True,
        requires_human_go_real=False,
        directive_id=did,
    )


class FakeRunner:
    def __init__(self):
        self.calls = []

    def call(self, args, *, env=None, timeout_seconds=60):
        self.calls.append((list(args), dict(env or {})))
        cmd = tuple(args[:2])
        if cmd == ("repo", "list"):
            return {"result": {"repos": [{
                "id": "repo-ia",
                "name": "IA-VISION",
                "remote": "https://github.com/neokyhurtado-cmd/IA-VISION.git",
            }]}}
        if cmd == ("worktree", "list"):
            return {"result": {"worktrees": []}}
        if cmd == ("worktree", "create"):
            return {"result": {"worktree": {
                "id": "repo-ia::C:/orca/wt-244",
                "branch": "feat/autowake-244",
            }}}
        if cmd == ("worktree", "show"):
            return {"result": {"worktree": {
                "id": "repo-ia::C:/orca/wt-244",
                "branch": "feat/trafficlab-premium-cabin-v1",
            }}}
        if cmd == ("terminal", "list"):
            return {"result": {"terminals": []}}
        if cmd == ("terminal", "create"):
            return {"result": {"terminal": {"handle": "term-hermes"}}}
        if cmd == ("terminal", "show"):
            return {"result": {"terminal": {
                "handle": "term-hermes",
                "title": "Hermes coordinator",
                "paneKey": "pane-1",
                "tabId": "tab-1",
            }}}
        if cmd == ("terminal", "wait"):
            return {"result": {"wait": {"satisfied": True}}}
        if cmd == ("terminal", "send"):
            return {"result": {"accepted": True}}
        if cmd == ("orchestration", "run-create"):
            assert env["ORCA_TERMINAL_HANDLE"] == "term-hermes"
            return {"result": {"run": {"id": "run_244"}}}
        if cmd == ("orchestration", "run-show"):
            return {"result": {"run": {"id": "run_244"}}}
        if cmd == ("orchestration", "run-use"):
            assert env["ORCA_TERMINAL_HANDLE"] == "term-hermes"
            return {"result": {"run": {"id": "run_244"}}}
        raise AssertionError(f"unexpected command: {args}")


def command_names(runner):
    return [tuple(args[:2]) for args, _env in runner.calls]


def test_scope_opt_in_is_explicit():
    assert directive_requests_orca(directive())
    assert directive_requests_orca(directive(scope="ORCA_RUN_REQUIRED=YES"))
    assert not directive_requests_orca(directive(scope="WORKER=mcode; MODE=visual"))


def test_first_wake_creates_one_orca_cabin_and_delivers_without_copy_paste(tmp_path):
    runner = FakeRunner()
    bridge = OrcaAutoWakeBridge(
        registry_path=tmp_path / "orca_runs.json",
        runner=runner,
        hermes_command="hermes -p orchestrator",
    )

    result = bridge.start_or_resume(
        directive(),
        source_comment_id=5770440668,
        execution_id="exec-1",
    )

    assert result.action == "created"
    assert result.run_id == "run_244"
    assert result.worktree_id == "repo-ia::C:/orca/wt-244"
    assert result.terminal_handle == "term-hermes"
    names = command_names(runner)
    assert names.count(("worktree", "create")) == 1
    assert names.count(("terminal", "create")) == 1
    assert names.count(("orchestration", "run-create")) == 1
    assert names.count(("terminal", "send")) == 1

    sent = next(args for args, _env in runner.calls if args[:2] == ["terminal", "send"])
    prompt = sent[sent.index("--text") + 1]
    assert "never ask David to copy/paste" in prompt
    assert "MiniMax/mcode" in prompt
    assert "Do not create another Run" in prompt

    registry = json.loads((tmp_path / "orca_runs.json").read_text(encoding="utf-8"))
    record = next(iter(registry["runs"].values()))
    assert record["run_id"] == "run_244"
    assert record["last_directive_id"] == "d-1"


def test_next_directive_resumes_same_run_and_worktree(tmp_path):
    registry = {
        "version": 1,
        "runs": {
            "neokyhurtado-cmd/IA-VISION#244:feat/trafficlab-premium-cabin-v1": {
                "run_id": "run_244",
                "worktree_id": "repo-ia::C:/orca/wt-244",
                "terminal_handle": "term-hermes",
                "last_directive_id": "old-directive",
            }
        },
    }
    path = tmp_path / "orca_runs.json"
    path.write_text(json.dumps(registry), encoding="utf-8")
    runner = FakeRunner()
    bridge = OrcaAutoWakeBridge(registry_path=path, runner=runner)

    result = bridge.start_or_resume(
        directive(did="d-2"),
        source_comment_id=5771000000,
        execution_id="exec-2",
    )

    assert result.action == "resumed"
    assert result.run_id == "run_244"
    names = command_names(runner)
    assert ("worktree", "create") not in names
    assert ("terminal", "create") not in names
    assert ("orchestration", "run-create") not in names
    assert names.count(("orchestration", "run-use")) == 1
    assert names.count(("terminal", "send")) == 1


def test_same_directive_is_local_idempotent_without_cli_calls(tmp_path):
    key = "neokyhurtado-cmd/IA-VISION#244:feat/trafficlab-premium-cabin-v1"
    path = tmp_path / "orca_runs.json"
    path.write_text(json.dumps({"version": 1, "runs": {key: {
        "run_id": "run_244",
        "worktree_id": "repo-ia::C:/orca/wt-244",
        "terminal_handle": "term-hermes",
        "last_directive_id": "d-1",
    }}}), encoding="utf-8")
    runner = FakeRunner()
    bridge = OrcaAutoWakeBridge(registry_path=path, runner=runner)

    result = bridge.start_or_resume(
        directive(),
        source_comment_id=1,
        execution_id="exec-1",
    )

    assert result.action == "idempotent"
    assert runner.calls == []


class FakeBridge:
    def __init__(self):
        self.calls = []

    def start_or_resume(self, d, *, source_comment_id, execution_id):
        self.calls.append((d.directive_id, source_comment_id, execution_id))
        return OrcaWakeResult(
            run_key="rk",
            run_id="run_244",
            worktree_id="repo-ia::C:/orca/wt-244",
            terminal_handle="term-hermes",
            action="resumed",
        )


def test_dispatcher_orca_path_bypasses_direct_hermes_kanban(tmp_path):
    fake_bridge = FakeBridge()
    dispatcher = OrchestratorDispatcher(
        session_log=tmp_path / "sessions.jsonl",
        routing_table_path=tmp_path / "routing.yaml",
        orca_bridge=fake_bridge,
    )
    dispatcher._resolve_assignee = lambda _d: "ia-vision"

    def forbidden(*_a, **_kw):
        raise AssertionError("direct Hermes kanban path must not run")

    dispatcher._invoke_kanban = forbidden
    result = dispatcher.dispatch(DispatchRequest(
        directive=directive(),
        source_comment_id=5770440668,
        execution_id="exec-1",
        head_before="abc123",
    ))

    assert result.state == SESSION_STATE_RUNNING
    assert result.kanban_task_id == "orca:run_244"
    assert fake_bridge.calls == [("d-1", 5770440668, "exec-1")]
    session = dispatcher.get_session(result.session_id)
    assert session is not None
    assert session.state == SESSION_STATE_RUNNING
    assert session.evidence_uri == "orca://run/run_244"
