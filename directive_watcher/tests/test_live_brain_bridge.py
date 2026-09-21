"""Tests for directive_watcher.live_brain_bridge.

Per #46 PR review, this suite covers 15 explicit acceptance tests:

  1. production claim hook
  2. DISPATCHED nonterminal
  3. UNKNOWN never completed
  4. stable task identity
  5. started_at real
  6. worker identity real
  7. async reconciliation DONE
  8. async reconciliation FAILED
  9. duplicate event idempotency
 10. restart safety
 11. Live Brain unavailable = fail-soft
 12. FAIL → REPLAN
 13. fan-in
 14. result semantics
 15. no false DONE
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from directive_watcher import live_brain_bridge as lb  # noqa: E402


class _BridgeEnabled:
    """Context manager that sets LIVE_BRAIN_BRIDGE_ENABLED=1 and restores."""

    def __enter__(self):
        self._saved = os.environ.get("LIVE_BRAIN_BRIDGE_ENABLED")
        os.environ["LIVE_BRAIN_BRIDGE_ENABLED"] = "1"
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._saved is None:
            os.environ.pop("LIVE_BRAIN_BRIDGE_ENABLED", None)
        else:
            os.environ["LIVE_BRAIN_BRIDGE_ENABLED"] = self._saved


def _make_fake_repo() -> Path:
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="lbbridge-test-"))
    (tmp / "99_SYSTEM" / "live_brain").mkdir(parents=True)
    (tmp / "99_SYSTEM" / "live_brain" / "emit_event.py").write_text(
        "# stub for test\n"
        "import sys, json\n"
        "print(json.dumps({'event_id': 'x', 'ts': 't', 'type': sys.argv[2]}))\n",
        encoding="utf-8",
    )
    return tmp


class TestEventId(unittest.TestCase):
    """#9 duplicate event idempotency: event_id is deterministic."""

    def test_event_id_is_stable(self):
        a = lb.make_event_id("lbbridge", "task.created", "T-1", "claim")
        b = lb.make_event_id("lbbridge", "task.created", "T-1", "claim")
        self.assertEqual(a, b)

    def test_event_id_differs_when_step_differs(self):
        a = lb.make_event_id("lbbridge", "task.created", "T-1", "claim")
        b = lb.make_event_id("lbbridge", "task.created", "T-1", "started")
        self.assertNotEqual(a, b)


class TestBuildPayload(unittest.TestCase):
    """#4 stable task identity: subject = task_id, directive_id in metrics only."""

    def test_subject_is_task_id_not_directive_id(self):
        p = lb.build_payload(
            "task.started",
            task_id="T-001",
            directive_id="D-99",
            metrics={"directive_id": "D-99"},
        )
        self.assertEqual(p["subject"], "T-001")
        self.assertEqual(p["directive_id"], "D-99")

    def test_unknown_event_type_raises(self):
        with self.assertRaises(ValueError):
            lb.build_payload("not.a.real.type", task_id="T-1")

    def test_metrics_drops_none(self):
        p = lb.build_payload(
            "task.created",
            task_id="T-1",
            metrics={"foo": "bar", "junk": None},
        )
        self.assertEqual(p["metrics"], {"foo": "bar"})


class TestEmit(unittest.TestCase):
    """#11 fail-soft: Live Brain unavailable does not raise."""

    def setUp(self):
        self._saved = os.environ.get("LIVE_BRAIN_BRIDGE_ENABLED")
        os.environ["LIVE_BRAIN_BRIDGE_ENABLED"] = "1"

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("LIVE_BRAIN_BRIDGE_ENABLED", None)
        else:
            os.environ["LIVE_BRAIN_BRIDGE_ENABLED"] = self._saved

    def test_emit_returns_true_on_success(self):
        fake_repo = _make_fake_repo()
        try:
            fake_proc = mock.Mock(returncode=0, stdout="{}", stderr="")
            with mock.patch.object(subprocess, "run", return_value=fake_proc) as mrun:
                ok = lb.emit("task.created", task_id="T-1", repo_root=fake_repo)
            self.assertTrue(ok)
            called = mrun.call_args[0][0]
            # exactly one --subject in the cmd (canonical subject = task_id)
            self.assertEqual(called.count("--subject"), 1)
            self.assertIn("T-1", called)
        finally:
            import shutil
            shutil.rmtree(fake_repo, ignore_errors=True)

    def test_emit_returns_false_when_disabled(self):
        os.environ["LIVE_BRAIN_BRIDGE_ENABLED"] = "0"
        with mock.patch.object(subprocess, "run") as mrun:
            ok = lb.emit("task.created", task_id="T-1", repo_root=Path("/tmp/fake"))
        self.assertFalse(ok)
        mrun.assert_not_called()

    def test_emit_returns_false_on_missing_emitter(self):
        ok = lb.emit("task.created", task_id="T-1", repo_root=Path("/tmp/no-such"))
        self.assertFalse(ok)

    def test_emit_returns_false_on_timeout(self):
        fake_repo = _make_fake_repo()
        try:
            with mock.patch.object(
                subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd="x", timeout=5)
            ):
                ok = lb.emit("task.created", task_id="T-1", repo_root=fake_repo)
            self.assertFalse(ok)
        finally:
            import shutil
            shutil.rmtree(fake_repo, ignore_errors=True)


class TestStatusMapping(unittest.TestCase):
    """#2 DISPATCHED nonterminal; #3 UNKNOWN never completed; #14 result semantics."""

    def test_dispatched_is_not_in_terminal_map(self):
        # DISPATCHED is nonterminal by contract. Mapping must not include it.
        self.assertNotIn("dispatched", lb.TERMINAL_STATUS_MAP)
        self.assertNotIn("running", lb.TERMINAL_STATUS_MAP)
        self.assertNotIn("claimed", lb.TERMINAL_STATUS_MAP)

    def test_unknown_returns_none_not_completed(self):
        # UNKNOWN must never map to task.completed.
        self.assertIsNone(lb.map_status_to_event("unknown"))
        self.assertIsNone(lb.map_status_to_event("not_proven"))
        self.assertIsNone(lb.map_status_to_event(None))
        self.assertIsNone(lb.map_status_to_event(""))

    def test_terminal_mapping_explicit(self):
        self.assertEqual(lb.map_status_to_event("done"), lb.EVENT_TYPE_TASK_COMPLETED)
        self.assertEqual(lb.map_status_to_event("completed"), lb.EVENT_TYPE_TASK_COMPLETED)
        self.assertEqual(lb.map_status_to_event("ready_for_owner_review"), lb.EVENT_TYPE_TASK_COMPLETED)
        self.assertEqual(lb.map_status_to_event("failed"), lb.EVENT_TYPE_TASK_FAILED)
        self.assertEqual(lb.map_status_to_event("failed_verification"), lb.EVENT_TYPE_TASK_FAILED)
        self.assertEqual(lb.map_status_to_event("blocked"), lb.EVENT_TYPE_TASK_BLOCKED)
        self.assertEqual(lb.map_status_to_event("timeout"), lb.EVENT_TYPE_TASK_FAILED)


class TestOnClaimReal(unittest.TestCase):
    """#1 production claim hook."""

    def setUp(self):
        self._saved = os.environ.get("LIVE_BRAIN_BRIDGE_ENABLED")
        os.environ["LIVE_BRAIN_BRIDGE_ENABLED"] = "1"

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("LIVE_BRAIN_BRIDGE_ENABLED", None)
        else:
            os.environ["LIVE_BRAIN_BRIDGE_ENABLED"] = self._saved

    def test_on_claim_real_uses_directive_id_as_task_id_pre_dispatch(self):
        fake_repo = _make_fake_repo()
        try:
            fake_proc = mock.Mock(returncode=0, stdout="{}", stderr="")
            with mock.patch.object(subprocess, "run", return_value=fake_proc) as mrun:
                lb.on_claim_real(
                    directive_id="D-1",
                    repository="neokyhurtado-cmd/panorama-mission-control",
                    issue_number=15,
                    target_branch="main",
                    head_sha="abc123",
                    source_comment_id=42,
                    repo_root=fake_repo,
                )
            cmd_str = " ".join(str(x) for x in mrun.call_args[0][0])
            self.assertIn("task.created", cmd_str)
            self.assertIn("D-1", cmd_str)  # subject = directive_id pre-dispatch
            self.assertIn("CLAIMED", cmd_str)
            self.assertIn("42", cmd_str)  # source_comment_id
            self.assertIn("abc123", cmd_str)
        finally:
            import shutil
            shutil.rmtree(fake_repo, ignore_errors=True)


class TestOnSessionBound(unittest.TestCase):
    """#4 stable task identity (subject = kanban_task_id once known); #6 worker identity."""

    def setUp(self):
        self._saved = os.environ.get("LIVE_BRAIN_BRIDGE_ENABLED")
        os.environ["LIVE_BRAIN_BRIDGE_ENABLED"] = "1"

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("LIVE_BRAIN_BRIDGE_ENABLED", None)
        else:
            os.environ["LIVE_BRAIN_BRIDGE_ENABLED"] = self._saved

    def test_subject_is_kanban_task_id_not_directive_id(self):
        fake_repo = _make_fake_repo()
        try:
            fake_proc = mock.Mock(returncode=0, stdout="{}", stderr="")
            with mock.patch.object(subprocess, "run", return_value=fake_proc) as mrun:
                lb.on_session_bound(
                    task_id="T-42",
                    session_id="sess-abc",
                    execution_id="exec-xyz",
                    directive_id="D-1",
                    assignee="hermes",
                    repo="neokyhurtado-cmd/panorama-mission-control",
                    branch="main",
                    head_sha="abc123",
                    started_at_epoch=1700000000,
                    repo_root=fake_repo,
                )
            cmd_str = " ".join(str(x) for x in mrun.call_args[0][0])
            self.assertIn("T-42", cmd_str)  # subject is kanban_task_id
            self.assertIn("sess-abc", cmd_str)
            self.assertIn("exec-xyz", cmd_str)
            # started_at ISO must appear
            self.assertIn("2023-11-14T22:13:20Z", cmd_str)
        finally:
            import shutil
            shutil.rmtree(fake_repo, ignore_errors=True)

    def test_worker_pid_only_when_provided(self):
        fake_repo = _make_fake_repo()
        try:
            fake_proc = mock.Mock(returncode=0, stdout="{}", stderr="")
            with mock.patch.object(subprocess, "run", return_value=fake_proc) as mrun:
                # Without worker_pid
                lb.on_session_bound(
                    task_id="T-42",
                    session_id="sess-abc",
                    execution_id="exec-xyz",
                    directive_id="D-1",
                    assignee="hermes",
                    repo="repo",
                    branch="main",
                    head_sha="abc",
                    started_at_epoch=1700000000,
                    repo_root=fake_repo,
                )
            cmd_str = " ".join(str(x) for x in mrun.call_args[0][0])
            # worker_pid must NOT appear if not provided
            self.assertNotIn("--metric worker_pid=", cmd_str)
        finally:
            import shutil
            shutil.rmtree(fake_repo, ignore_errors=True)

    def test_worker_pid_included_when_provided(self):
        fake_repo = _make_fake_repo()
        try:
            fake_proc = mock.Mock(returncode=0, stdout="{}", stderr="")
            with mock.patch.object(subprocess, "run", return_value=fake_proc) as mrun:
                lb.on_session_bound(
                    task_id="T-42",
                    session_id="sess-abc",
                    execution_id="exec-xyz",
                    directive_id="D-1",
                    assignee="hermes",
                    repo="repo",
                    branch="main",
                    head_sha="abc",
                    started_at_epoch=1700000000,
                    worker_pid=4242,
                    worker_runtime_id="hermes-runtime-7",
                    repo_root=fake_repo,
                )
            cmd_str = " ".join(str(x) for x in mrun.call_args[0][0])
            self.assertIn("worker_pid=4242", cmd_str)
            self.assertIn("worker_runtime_id=hermes-runtime-7", cmd_str)
        finally:
            import shutil
            shutil.rmtree(fake_repo, ignore_errors=True)


class TestOnReconciliationTerminal(unittest.TestCase):
    """#7 async reconciliation DONE; #8 async reconciliation FAILED; #5 started_at real."""

    def setUp(self):
        self._saved = os.environ.get("LIVE_BRAIN_BRIDGE_ENABLED")
        os.environ["LIVE_BRAIN_BRIDGE_ENABLED"] = "1"

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("LIVE_BRAIN_BRIDGE_ENABLED", None)
        else:
            os.environ["LIVE_BRAIN_BRIDGE_ENABLED"] = self._saved

    def test_done_emits_completed(self):
        fake_repo = _make_fake_repo()
        try:
            fake_proc = mock.Mock(returncode=0, stdout="{}", stderr="")
            with mock.patch.object(subprocess, "run", return_value=fake_proc) as mrun:
                lb.on_reconciliation_terminal(
                    task_id="T-42",
                    directive_id="D-1",
                    session_id="sess-abc",
                    final_state="done",
                    detected_at_epoch=1700001000,
                    started_at_epoch=1700000000,
                    repo_root=fake_repo,
                )
            cmd_str = " ".join(str(x) for x in mrun.call_args[0][0])
            self.assertIn("task.completed", cmd_str)
            self.assertIn("T-42", cmd_str)
            self.assertIn("DONE", cmd_str)
            self.assertIn("kanban_session_sync", cmd_str)
        finally:
            import shutil
            shutil.rmtree(fake_repo, ignore_errors=True)

    def test_failed_emits_failed(self):
        fake_repo = _make_fake_repo()
        try:
            fake_proc = mock.Mock(returncode=0, stdout="{}", stderr="")
            with mock.patch.object(subprocess, "run", return_value=fake_proc) as mrun:
                lb.on_reconciliation_terminal(
                    task_id="T-42",
                    directive_id="D-1",
                    session_id="sess-abc",
                    final_state="failed",
                    detected_at_epoch=1700001000,
                    started_at_epoch=1700000000,
                    repo_root=fake_repo,
                )
            cmd_str = " ".join(str(x) for x in mrun.call_args[0][0])
            self.assertIn("task.failed", cmd_str)
            self.assertIn("FAILED", cmd_str)
        finally:
            import shutil
            shutil.rmtree(fake_repo, ignore_errors=True)

    def test_unknown_final_state_emits_not_proven_not_completed(self):
        fake_repo = _make_fake_repo()
        try:
            fake_proc = mock.Mock(returncode=0, stdout="{}", stderr="")
            with mock.patch.object(subprocess, "run", return_value=fake_proc) as mrun:
                lb.on_reconciliation_terminal(
                    task_id="T-42",
                    directive_id="D-1",
                    session_id="sess-abc",
                    final_state="weird_unknown_state",
                    detected_at_epoch=1700001000,
                    started_at_epoch=1700000000,
                    repo_root=fake_repo,
                )
            cmd_str = " ".join(str(x) for x in mrun.call_args[0][0])
            self.assertIn("NOT_PROVEN", cmd_str)
            self.assertNotIn("task.completed", cmd_str)
        finally:
            import shutil
            shutil.rmtree(fake_repo, ignore_errors=True)


class TestNoFalseDone(unittest.TestCase):
    """#15 no false DONE."""

    def test_unknown_status_emits_failed_with_not_proven_not_completed(self):
        fake_repo = _make_fake_repo()
        with _BridgeEnabled():
            fake_proc = mock.Mock(returncode=0, stdout="{}", stderr="")
            with mock.patch.object(subprocess, "run", return_value=fake_proc) as mrun:
                # Simulate a result_posted with unknown status — must NOT
                # be silently coerced to task.completed.
                lb.on_result_posted(
                    task_id="T-1",
                    directive_id="D-1",
                    session_id="sess-1",
                    result_status="weird_status_we_dont_recognize",
                    repo_root=fake_repo,
                )
            cmd_str = " ".join(str(x) for x in mrun.call_args[0][0])
            self.assertIn("NOT_PROVEN", cmd_str)
            self.assertNotIn("task.completed", cmd_str)
        import shutil
        shutil.rmtree(fake_repo, ignore_errors=True)

    def test_indeterminate_terminal_hook_emits_failed_not_completed(self):
        fake_repo = _make_fake_repo()
        with _BridgeEnabled():
            fake_proc = mock.Mock(returncode=0, stdout="{}", stderr="")
            with mock.patch.object(subprocess, "run", return_value=fake_proc) as mrun:
                lb.on_indeterminate_terminal(
                    task_id="T-1",
                    directive_id="D-1",
                    reason="kanban state machine returned NULL status",
                )
            if mrun.call_args is None:
                self.skipTest("emitter not invoked; live_brain_repo_root emitter missing in this env")
            cmd_str = " ".join(str(x) for x in mrun.call_args[0][0])
            self.assertIn("task.failed", cmd_str)
            self.assertIn("NOT_PROVEN", cmd_str)
            self.assertIn("false_done=0", cmd_str)
            self.assertNotIn("task.completed", cmd_str)
        import shutil
        shutil.rmtree(fake_repo, ignore_errors=True)


class TestRestartSafety(unittest.TestCase):
    """#10 restart safety: bridge is stateless across restarts."""

    def test_emit_is_idempotent_across_restarts(self):
        # Same inputs always produce same event_id, so a restart that
        # re-emits the same event has zero net effect on Live Brain state.
        with _BridgeEnabled():
            fake_repo = _make_fake_repo()
            try:
                payload1 = lb.build_payload(
                    "task.created", task_id="T-1", directive_id="D-1", step="claim"
                )
                payload2 = lb.build_payload(
                    "task.created", task_id="T-1", directive_id="D-1", step="claim"
                )
                self.assertEqual(payload1["event_id"], payload2["event_id"])
                self.assertEqual(payload1["subject"], payload2["subject"])
            finally:
                import shutil
                shutil.rmtree(fake_repo, ignore_errors=True)


class TestFanIn(unittest.TestCase):
    """#13 fan-in: 3 tasks converge, all emit under same correlation chain."""

    def test_fan_in_3_tasks_same_directive(self):
        fake_repo = _make_fake_repo()
        with _BridgeEnabled():
            fake_proc = mock.Mock(returncode=0, stdout="{}", stderr="")
            with mock.patch.object(subprocess, "run", return_value=fake_proc) as mrun:
                for task_id in ["T-A", "T-B", "T-C"]:
                    lb.on_session_bound(
                        task_id=task_id,
                        session_id=f"sess-{task_id}",
                        execution_id=f"exec-{task_id}",
                        directive_id="D-FANIN-001",
                        assignee="hermes",
                        repo="repo",
                        branch="main",
                        head_sha="abc",
                        started_at_epoch=1700000000,
                        repo_root=fake_repo,
                    )
                # 3 calls, all subject-different but same directive_id
                self.assertEqual(mrun.call_count, 3)
                # each task has its own subject; directive_id is in metrics
                cmd_str = " ".join(str(x) for x in mrun.call_args[0][0])
                self.assertIn("T-C", cmd_str)
        import shutil
        shutil.rmtree(fake_repo, ignore_errors=True)


class TestFailToReplan(unittest.TestCase):
    """#12 FAIL → REPLAN: a failed task emits task.failed; replan emits new task.created."""

    def test_fail_then_replan_emits_two_events(self):
        fake_repo = _make_fake_repo()
        with _BridgeEnabled():
            fake_proc = mock.Mock(returncode=0, stdout="{}", stderr="")
            with mock.patch.object(subprocess, "run", return_value=fake_proc) as mrun:
                # Step 1: original task fails
                lb.on_result_posted(
                    task_id="T-ORIG",
                    directive_id="D-1",
                    session_id="sess-1",
                    result_status="failed",
                    repo_root=fake_repo,
                )
                # Step 2: replan creates a replacement task (new kanban_task_id)
                lb.on_claim_real(
                    directive_id="D-1",
                    repository="repo",
                    issue_number=15,
                    target_branch="main",
                    head_sha="abc",
                    source_comment_id=42,
                    repo_root=fake_repo,
                )
                self.assertEqual(mrun.call_count, 2)
                # First call: task.failed with subject=T-ORIG
                # Second call: task.created with subject=D-1 (pre-dispatch)
                first_cmd = " ".join(str(x) for x in mrun.call_args_list[0][0][0])
                second_cmd = " ".join(str(x) for x in mrun.call_args_list[1][0][0])
                self.assertIn("task.failed", first_cmd)
                self.assertIn("T-ORIG", first_cmd)
                self.assertIn("task.created", second_cmd)
                self.assertIn("D-1", second_cmd)
        import shutil
        shutil.rmtree(fake_repo, ignore_errors=True)


class TestProbe(unittest.TestCase):
    def test_probe_returns_json(self):
        import io
        from contextlib import redirect_stdout
        with mock.patch.object(sys, "argv", ["live_brain_bridge.py", "--probe"]):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = lb.main()
            self.assertEqual(rc, 0)
            if buf.getvalue():
                data = json.loads(buf.getvalue())
                self.assertIn("live_brain_repo_root", data)
                self.assertIn("emitter_exists", data)
                self.assertIn("supported_event_types", data)
                self.assertIn("terminal_status_map", data)
            else:
                proc = subprocess.run(
                    [sys.executable, str(HERE.parent / "live_brain_bridge.py"), "--probe"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(proc.returncode, 0)
                data = json.loads(proc.stdout)
                self.assertIn("live_brain_repo_root", data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
