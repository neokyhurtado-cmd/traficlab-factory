"""Smoke tests for directive_watcher.live_brain_bridge.

These tests do not require a live Live Brain runtime. They verify:
  * Stable event_id from (event_type, actor, subject).
  * Subprocess invocation with the canonical emit_event.py.
  * Fail-soft on bad event types and missing emitter.
  * Hook functions emit the right canonical event types for each
    directive_watcher state transition.
"""
from __future__ import annotations

import inspect
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


class TestEventId(unittest.TestCase):
    def test_event_id_is_stable(self):
        a = lb.make_event_id("lbbridge", "task.created", "actor", "subject")
        b = lb.make_event_id("lbbridge", "task.created", "actor", "subject")
        self.assertEqual(a, b)

    def test_event_id_differs_when_step_differs(self):
        a = lb.make_event_id("lbbridge", "task.created", "actor", "subject")
        b = lb.make_event_id("lbbridge", "task.created", "actor", "subject", "step2")
        self.assertNotEqual(a, b)


class TestBuildPayload(unittest.TestCase):
    def test_known_event_types_pass(self):
        for et in lb.ALL_EVENT_TYPES:
            p = lb.build_payload(et, actor="a", subject="s")
            self.assertEqual(p["type"], et)
            self.assertEqual(p["actor"], "a")
            self.assertEqual(p["subject"], "s")
            self.assertIn("event_id", p)
            self.assertIn("ts", p)

    def test_unknown_event_type_raises(self):
        with self.assertRaises(ValueError):
            lb.build_payload("not.a.real.type", actor="a", subject="s")

    def test_metrics_drops_none(self):
        p = lb.build_payload(
            "task.created",
            actor="a",
            subject="s",
            metrics={"foo": "bar", "junk": None},
        )
        self.assertEqual(p["metrics"], {"foo": "bar"})


class TestEmit(unittest.TestCase):
    def setUp(self):
        # Enable the bridge for tests; tests that need OFF override via env.
        import os
        self._env = os.environ.get("LIVE_BRAIN_BRIDGE_ENABLED")
        os.environ["LIVE_BRAIN_BRIDGE_ENABLED"] = "1"

    def tearDown(self):
        import os
        if self._env is None:
            os.environ.pop("LIVE_BRAIN_BRIDGE_ENABLED", None)
        else:
            os.environ["LIVE_BRAIN_BRIDGE_ENABLED"] = self._env

    def _make_fake_repo(self) -> Path:
        """Create a temp directory with a fake emitter so the existence check passes."""
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="lbbridge-test-"))
        (tmp / "99_SYSTEM" / "live_brain").mkdir(parents=True)
        (tmp / "99_SYSTEM" / "live_brain" / "emit_event.py").write_text(
            "# stub for test\nimport sys, json\nprint(json.dumps({'event_id': 'x', 'ts': 't', 'type': sys.argv[2]}))\n",
            encoding="utf-8",
        )
        return tmp

    def test_emit_returns_true_on_success(self):
        fake_repo = self._make_fake_repo()
        try:
            fake_event = {
                "event_id": "x",
                "ts": "2026-09-19T00:00:00Z",
                "type": "task.created",
                "actor": "a",
                "subject": "s",
            }
            fake_proc = mock.Mock(returncode=0, stdout=json.dumps(fake_event), stderr="")
            with mock.patch.object(subprocess, "run", return_value=fake_proc) as mrun:
                ok = lb.emit(
                    "task.created",
                    actor="a",
                    subject="s",
                    repo_root=fake_repo,
                )
            self.assertTrue(ok)
            called = mrun.call_args[0][0]
            self.assertIn("--type", called)
            self.assertIn("task.created", called)
            self.assertIn("--actor", called)
            self.assertIn("a", called)
            self.assertIn("--subject", called)
            self.assertIn("s", called)
        finally:
            import shutil
            shutil.rmtree(fake_repo, ignore_errors=True)

    def test_emit_returns_false_on_nonzero_exit(self):
        fake_repo = self._make_fake_repo()
        try:
            fake_proc = mock.Mock(returncode=1, stdout="", stderr="boom")
            with mock.patch.object(subprocess, "run", return_value=fake_proc):
                ok = lb.emit("task.created", actor="a", subject="s", repo_root=fake_repo)
            self.assertFalse(ok)
        finally:
            import shutil
            shutil.rmtree(fake_repo, ignore_errors=True)

    def test_emit_returns_false_on_missing_emitter(self):
        ok = lb.emit(
            "task.created",
            actor="a",
            subject="s",
            repo_root=Path("/tmp/no-such-repo-xyz"),
        )
        self.assertFalse(ok)

    def test_emit_returns_false_on_bad_event_type(self):
        ok = lb.emit(
            "not.a.real.type",
            actor="a",
            subject="s",
            repo_root=Path("/tmp/fake"),
        )
        self.assertFalse(ok)

    def test_emit_returns_false_when_disabled(self):
        # Override the env to disable the bridge.
        import os
        os.environ["LIVE_BRAIN_BRIDGE_ENABLED"] = "0"
        with mock.patch.object(subprocess, "run") as mrun:
            ok = lb.emit(
                "task.created",
                actor="a",
                subject="s",
                repo_root=Path("/tmp/fake"),
            )
        self.assertFalse(ok)
        mrun.assert_not_called()

    def test_emit_returns_false_on_timeout(self):
        fake_repo = self._make_fake_repo()
        try:
            with mock.patch.object(
                subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd="x", timeout=5)
            ):
                ok = lb.emit("task.created", actor="a", subject="s", repo_root=fake_repo)
            self.assertFalse(ok)
        finally:
            import shutil
            shutil.rmtree(fake_repo, ignore_errors=True)


class TestHooks(unittest.TestCase):
    def setUp(self):
        import os
        self._env = os.environ.get("LIVE_BRAIN_BRIDGE_ENABLED")
        os.environ["LIVE_BRAIN_BRIDGE_ENABLED"] = "1"

    def tearDown(self):
        import os
        if self._env is None:
            os.environ.pop("LIVE_BRAIN_BRIDGE_ENABLED", None)
        else:
            os.environ["LIVE_BRAIN_BRIDGE_ENABLED"] = self._env

    def _make_fake_repo(self) -> Path:
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="lbbridge-hook-"))
        (tmp / "99_SYSTEM" / "live_brain").mkdir(parents=True)
        (tmp / "99_SYSTEM" / "live_brain" / "emit_event.py").write_text(
            "# stub for test\nimport sys, json\nprint(json.dumps({'event_id': 'x', 'ts': 't', 'type': sys.argv[2]}))\n",
            encoding="utf-8",
        )
        return tmp

    def test_on_directive_claimed_uses_task_created(self):
        fake_repo = self._make_fake_repo()
        try:
            fake_proc = mock.Mock(returncode=0, stdout="{}", stderr="")
            with mock.patch.object(subprocess, "run", return_value=fake_proc) as mrun:
                lb.on_directive_claimed(
                    directive_id="D-1",
                    repository="neokyhurtado-cmd/panorama-mission-control",
                    issue_number=15,
                    target_branch="main",
                    head_sha="abc123",
                    actor="Hermes Control Room — David",
                    repo_root=fake_repo,
                )
            cmd = mrun.call_args[0][0]
            cmd_str = " ".join(str(x) for x in cmd)
            self.assertIn("task.created", cmd)
            self.assertIn("D-1", cmd)
            self.assertIn("neokyhurtado-cmd/panorama-mission-control", cmd_str)
            self.assertIn("main", cmd_str)
            self.assertIn("abc123", cmd_str)
        finally:
            import shutil
            shutil.rmtree(fake_repo, ignore_errors=True)

    def test_on_session_bound_uses_task_started(self):
        fake_repo = self._make_fake_repo()
        try:
            fake_proc = mock.Mock(returncode=0, stdout="{}", stderr="")
            with mock.patch.object(subprocess, "run", return_value=fake_proc) as mrun:
                lb.on_session_bound(
                    session_id="sess-abc",
                    execution_id="exec-xyz",
                    directive_id="D-1",
                    kanban_task_id="t_42",
                    assignee="hermes",
                    repo="neokyhurtado-cmd/panorama-mission-control",
                    branch="main",
                    head_sha="abc123",
                    actor="Hermes Control Room — David",
                    repo_root=fake_repo,
                )
            cmd = mrun.call_args[0][0]
            cmd_str = " ".join(str(x) for x in cmd)
            self.assertIn("task.started", cmd)
            self.assertIn("sess-abc", cmd_str)
            self.assertIn("exec-xyz", cmd_str)
            self.assertIn("t_42", cmd_str)
        finally:
            import shutil
            shutil.rmtree(fake_repo, ignore_errors=True)

    def test_on_result_posted_maps_ready_to_completed(self):
        fake_repo = self._make_fake_repo()
        try:
            fake_proc = mock.Mock(returncode=0, stdout="{}", stderr="")
            with mock.patch.object(subprocess, "run", return_value=fake_proc) as mrun:
                lb.on_result_posted(
                    directive_id="D-1",
                    session_id="sess-abc",
                    result_status="ready_for_owner_review",
                    comment_id=12345,
                    actor="Hermes",
                    repo_root=fake_repo,
                )
            cmd = mrun.call_args[0][0]
            self.assertIn("task.completed", cmd)
        finally:
            import shutil
            shutil.rmtree(fake_repo, ignore_errors=True)

    def test_on_result_posted_maps_failed_to_failed(self):
        fake_repo = self._make_fake_repo()
        try:
            fake_proc = mock.Mock(returncode=0, stdout="{}", stderr="")
            with mock.patch.object(subprocess, "run", return_value=fake_proc) as mrun:
                lb.on_result_posted(
                    directive_id="D-1",
                    session_id="sess-abc",
                    result_status="failed_verification",
                    comment_id=12345,
                    actor="Hermes",
                    repo_root=fake_repo,
                )
            cmd = mrun.call_args[0][0]
            self.assertIn("task.failed", cmd)
        finally:
            import shutil
            shutil.rmtree(fake_repo, ignore_errors=True)

    def test_on_result_posted_maps_blocked(self):
        """C3+C6: blocked_external_real -> task.blocked, NOT task.failed.

        BLOCKED is a distinct terminal state from FAILED. A blocked
        directive requires external input (or owner action); a failed
        one has a verified negative outcome. The bridge MUST preserve
        this distinction so Live Brain consumers can render the two
        states differently.
        """
        fake_repo = self._make_fake_repo()
        try:
            fake_proc = mock.Mock(returncode=0, stdout="{}", stderr="")
            with mock.patch.object(subprocess, "run", return_value=fake_proc) as mrun:
                lb.on_result_posted(
                    directive_id="D-1",
                    session_id="sess-abc",
                    result_status="blocked_external_real",
                    comment_id=12345,
                    actor="Hermes",
                    repo_root=fake_repo,
                )
            cmd = mrun.call_args[0][0]
            self.assertIn("task.blocked", cmd)
            self.assertNotIn("task.failed", cmd)
            self.assertNotIn("task.completed", cmd)
        finally:
            import shutil
            shutil.rmtree(fake_repo, ignore_errors=True)

    # --- C3 closed-mapping tests (FACTORY-E2E-BRIDGE-01 acceptance) ---

    def test_on_result_posted_dispatched_is_not_completed(self):
        """C3: DISPATCHED must NEVER emit task.completed (nonterminal)."""
        fake_repo = self._make_fake_repo()
        try:
            fake_proc = mock.Mock(returncode=0, stdout="{}", stderr="")
            with mock.patch.object(subprocess, "run", return_value=fake_proc) as mrun:
                lb.on_result_posted(
                    directive_id="D-dispatched",
                    session_id="sess-abc",
                    result_status="dispatched",
                    comment_id=12345,
                    actor="Hermes",
                    repo_root=fake_repo,
                )
            cmd = mrun.call_args[0][0]
            self.assertNotIn("task.completed", cmd)
            self.assertIn("task.heartbeat", cmd)
        finally:
            import shutil
            shutil.rmtree(fake_repo, ignore_errors=True)

    def test_on_result_posted_running_is_not_completed(self):
        fake_repo = self._make_fake_repo()
        try:
            fake_proc = mock.Mock(returncode=0, stdout="{}", stderr="")
            with mock.patch.object(subprocess, "run", return_value=fake_proc) as mrun:
                lb.on_result_posted(
                    directive_id="D-running",
                    session_id="sess-abc",
                    result_status="running",
                    comment_id=12345,
                    actor="Hermes",
                    repo_root=fake_repo,
                )
            cmd = mrun.call_args[0][0]
            self.assertNotIn("task.completed", cmd)
            self.assertIn("task.heartbeat", cmd)
        finally:
            import shutil
            shutil.rmtree(fake_repo, ignore_errors=True)

    def test_on_result_posted_human_go_is_not_completed(self):
        fake_repo = self._make_fake_repo()
        try:
            fake_proc = mock.Mock(returncode=0, stdout="{}", stderr="")
            with mock.patch.object(subprocess, "run", return_value=fake_proc) as mrun:
                lb.on_result_posted(
                    directive_id="D-hgr",
                    session_id="sess-abc",
                    result_status="human_go_real_required",
                    comment_id=12345,
                    actor="Hermes",
                    repo_root=fake_repo,
                )
            cmd = mrun.call_args[0][0]
            self.assertNotIn("task.completed", cmd)
        finally:
            import shutil
            shutil.rmtree(fake_repo, ignore_errors=True)

    def test_on_result_posted_unknown_status_is_blocked_not_completed(self):
        """C3: unknown status -> task.blocked with UNKNOWN_PROCESSED,
        NEVER task.completed (FAIL CLOSED / NOT_PROVEN)."""
        fake_repo = self._make_fake_repo()
        try:
            fake_proc = mock.Mock(returncode=0, stdout="{}", stderr="")
            with mock.patch.object(subprocess, "run", return_value=fake_proc) as mrun:
                lb.on_result_posted(
                    directive_id="D-unknown",
                    session_id="sess-abc",
                    result_status="some_random_status_we_dont_know",
                    comment_id=12345,
                    actor="Hermes",
                    repo_root=fake_repo,
                )
            cmd = mrun.call_args[0][0]
            self.assertNotIn("task.completed", cmd)
            self.assertIn("task.blocked", cmd)
            self.assertIn("UNKNOWN_PROCESSED", [s.upper() for s in cmd])
        finally:
            import shutil
            shutil.rmtree(fake_repo, ignore_errors=True)

    def test_on_result_posted_ready_for_owner_review_keeps_literal_status(self):
        """C6: ready_for_owner_review is terminal but status field MUST
        keep the literal READY_FOR_OWNER_REVIEW so downstream consumers
        can distinguish it from product DONE."""
        fake_repo = self._make_fake_repo()
        try:
            fake_proc = mock.Mock(returncode=0, stdout="{}", stderr="")
            with mock.patch.object(subprocess, "run", return_value=fake_proc) as mrun:
                lb.on_result_posted(
                    directive_id="D-rfor",
                    session_id="sess-abc",
                    result_status="ready_for_owner_review",
                    comment_id=12345,
                    actor="Hermes",
                    repo_root=fake_repo,
                )
            cmd = mrun.call_args[0][0]
            self.assertIn("task.completed", cmd)
            self.assertIn("READY_FOR_OWNER_REVIEW", cmd)
            self.assertNotIn("DONE", cmd)
        finally:
            import shutil
            shutil.rmtree(fake_repo, ignore_errors=True)

    # --- C2: RUNNING physical proof tests ---

    def test_on_session_bound_propagates_started_at_and_pid(self):
        fake_repo = self._make_fake_repo()
        try:
            fake_proc = mock.Mock(returncode=0, stdout="{}", stderr="")
            with mock.patch.object(subprocess, "run", return_value=fake_proc) as mrun:
                lb.on_session_bound(
                    session_id="sess-x",
                    execution_id="exec-x",
                    directive_id="D-x",
                    kanban_task_id="t-x",
                    assignee="hermes",
                    repo="owner/repo",
                    branch="main",
                    head_sha="abc",
                    actor="Hermes",
                    started_at="2026-09-19T18:00:00Z",
                    worker_pid=12345,
                    worker_runtime_id="directive_watcher.dispatch@host",
                    repo_root=fake_repo,
                )
            cmd = mrun.call_args[0][0]
            cmd_str = " ".join(cmd)
            self.assertIn("started_at=2026-09-19T18:00:00Z", cmd_str)
            self.assertIn("worker_pid=12345", cmd_str)
            self.assertIn("worker_runtime_id=directive_watcher.dispatch@host", cmd_str)
        finally:
            import shutil
            shutil.rmtree(fake_repo, ignore_errors=True)

    def test_on_session_bound_worker_pid_unknown_is_honest(self):
        """C2: if no PID is observable, the bridge MUST record UNKNOWN,
        not fabricate one."""
        fake_repo = self._make_fake_repo()
        try:
            fake_proc = mock.Mock(returncode=0, stdout="{}", stderr="")
            with mock.patch.object(subprocess, "run", return_value=fake_proc) as mrun:
                lb.on_session_bound(
                    session_id="sess-x",
                    execution_id="exec-x",
                    directive_id="D-x",
                    kanban_task_id="t-x",
                    assignee="hermes",
                    repo="owner/repo",
                    branch="main",
                    head_sha="abc",
                    actor="Hermes",
                    started_at="2026-09-19T18:00:00Z",
                    worker_pid=None,  # not observable
                    worker_runtime_id="external-worker:host",
                    repo_root=fake_repo,
                )
            cmd = mrun.call_args[0][0]
            cmd_str = " ".join(cmd)
            self.assertIn("worker_pid=UNKNOWN", cmd_str)
        finally:
            import shutil
            shutil.rmtree(fake_repo, ignore_errors=True)

    # --- C5: stable task subject tests ---

    def test_resolve_task_subject_prefers_kanban_task_id(self):
        result = lb._resolve_task_subject(
            directive_id="D-x",
            kanban_task_id="t-x",
            session_id="sess-x",
        )
        self.assertEqual(result, "t-x")

    def test_resolve_task_subject_falls_back_to_session_id(self):
        result = lb._resolve_task_subject(
            directive_id="D-x",
            kanban_task_id="",
            session_id="sess-x",
        )
        self.assertEqual(result, "sess-x")

    def test_resolve_task_subject_falls_back_to_directive_id(self):
        result = lb._resolve_task_subject(
            directive_id="D-x",
            kanban_task_id="",
            session_id="",
        )
        self.assertEqual(result, "D-x")

    def test_one_subject_across_lifecycle(self):
        """C5: claim + session + result + reconciliation all use the
        same subject for the same directive (once kanban_task_id exists)."""
        fake_repo = self._make_fake_repo()
        try:
            fake_proc = mock.Mock(returncode=0, stdout="{}", stderr="")
            subjects_seen = []
            with mock.patch.object(subprocess, "run", return_value=fake_proc) as mrun:
                lb.on_directive_claimed(
                    directive_id="D-lifecycle",
                    repository="owner/repo",
                    issue_number=1,
                    target_branch="main",
                    head_sha=None,
                    actor="Hermes",
                    repo_root=fake_repo,
                )
                lb.on_session_bound(
                    session_id="sess-lc",
                    execution_id="exec-lc",
                    directive_id="D-lifecycle",
                    kanban_task_id="t-lc",
                    assignee="hermes",
                    repo="owner/repo",
                    branch="main",
                    head_sha=None,
                    actor="Hermes",
                    repo_root=fake_repo,
                )
                lb.on_result_posted(
                    directive_id="D-lifecycle",
                    session_id="sess-lc",
                    kanban_task_id="t-lc",
                    result_status="ready_for_owner_review",
                    comment_id=1,
                    actor="Hermes",
                    repo_root=fake_repo,
                )
                lb.on_terminal_observed(
                    directive_id="D-lifecycle",
                    session_id="sess-lc",
                    kanban_task_id="t-lc",
                    outcome="done",
                    actor="Hermes",
                    repo_root=fake_repo,
                )
                for call in mrun.call_args_list:
                    cmd = call[0][0]
                    # Subject is the element after --subject
                    idx = cmd.index("--subject")
                    subjects_seen.append(cmd[idx + 1])
            self.assertEqual(subjects_seen, ["D-lifecycle", "t-lc", "t-lc", "t-lc"])
        finally:
            import shutil
            shutil.rmtree(fake_repo, ignore_errors=True)

    # --- C4: reconciliation terminal hook tests ---

    def test_on_terminal_observed_done_emits_completed(self):
        fake_repo = self._make_fake_repo()
        try:
            fake_proc = mock.Mock(returncode=0, stdout="{}", stderr="")
            with mock.patch.object(subprocess, "run", return_value=fake_proc) as mrun:
                lb.on_terminal_observed(
                    directive_id="D-rc",
                    session_id="sess-rc",
                    kanban_task_id="t-rc",
                    outcome="done",
                    actor="Hermes",
                    tests_summary="23/23 PASS",
                    evidence_uri="/path/evidence",
                    repo_root=fake_repo,
                )
            cmd = mrun.call_args[0][0]
            cmd_str = " ".join(cmd)
            self.assertIn("task.completed", cmd)
            self.assertIn("DONE", cmd)
            self.assertIn("reconcile_open_sessions", cmd_str)
            self.assertIn("tests_summary=23/23 PASS", cmd_str)
        finally:
            import shutil
            shutil.rmtree(fake_repo, ignore_errors=True)

    def test_on_terminal_observed_failed_emits_failed(self):
        fake_repo = self._make_fake_repo()
        try:
            fake_proc = mock.Mock(returncode=0, stdout="{}", stderr="")
            with mock.patch.object(subprocess, "run", return_value=fake_proc) as mrun:
                lb.on_terminal_observed(
                    directive_id="D-rc-fail",
                    session_id="sess-rc-fail",
                    kanban_task_id="t-rc-fail",
                    outcome="failed",
                    actor="Hermes",
                    repo_root=fake_repo,
                )
            cmd = mrun.call_args[0][0]
            self.assertIn("task.failed", cmd)
            self.assertIn("FAILED", cmd)
        finally:
            import shutil
            shutil.rmtree(fake_repo, ignore_errors=True)

    def test_on_terminal_observed_unknown_outcome_is_blocked(self):
        fake_repo = self._make_fake_repo()
        try:
            fake_proc = mock.Mock(returncode=0, stdout="{}", stderr="")
            with mock.patch.object(subprocess, "run", return_value=fake_proc) as mrun:
                lb.on_terminal_observed(
                    directive_id="D-rc-unk",
                    session_id="sess-rc-unk",
                    kanban_task_id="t-rc-unk",
                    outcome="alien_outcome_from_future",
                    actor="Hermes",
                    repo_root=fake_repo,
                )
            cmd = mrun.call_args[0][0]
            self.assertIn("task.blocked", cmd)
            self.assertIn("UNKNOWN_RECONCILIATION_OUTCOME", cmd)
            self.assertNotIn("task.completed", cmd)
        finally:
            import shutil
            shutil.rmtree(fake_repo, ignore_errors=True)

    # --- Production claim hook test (C1) ---

    def test_handler_invokes_on_directive_claimed_on_claim(self):
        """C1: real watcher handler invokes on_directive_claimed after
        durable claim.

        The source-code wiring is verified exhaustively by
        TestC1ProductionClaimWiring::test_handler_module_invokes_on_directive_claimed
        below. This placeholder exists for documentation; the real proof
        is the end-to-end canary in test_e2e_canary.py (added in a
        follow-up commit if required).
        """
        import directive_watcher.handler as handler_mod
        self.assertTrue(hasattr(handler_mod, "WatcherHandler"))


class TestC1ProductionClaimWiring(unittest.TestCase):
    """C1 — production handler.py invokes on_directive_claimed after durable claim.

    Verifies the SOURCE code actually contains the call wiring (not just
    that a test can patch it).
    """

    def test_handler_module_invokes_on_directive_claimed(self):
        import directive_watcher.handler as handler_mod
        source = inspect.getsource(handler_mod)
        self.assertIn("_lbb.on_directive_claimed(", source)
        self.assertIn("summary.directives_claimed += 1", source)
        # Must be placed AFTER the claim counter increment, BEFORE _post_ack.
        claim_pos = source.index("_lbb.on_directive_claimed(")
        post_ack_pos = source.index("self._post_ack(repo, comment.issue_number, claim)")
        counter_pos = source.index("summary.directives_claimed += 1")
        self.assertGreater(claim_pos, counter_pos)
        self.assertLess(claim_pos, post_ack_pos)


class TestC4ReconciliationHookWiring(unittest.TestCase):
    """C4 — kanban_session_sync module invokes on_terminal_observed after update_session."""

    def test_kanban_session_sync_module_invokes_on_terminal_observed(self):
        import directive_watcher.kanban_session_sync as sync_mod
        source = inspect.getsource(sync_mod)
        self.assertIn("_lbb.on_terminal_observed(", source)
        update_pos = source.index("dispatcher.update_session(session_id, **kwargs)")
        # The hook invocation must come AFTER the update_session call.
        hook_pos = source.index("_lbb.on_terminal_observed(")
        self.assertGreater(hook_pos, update_pos)

    def test_orch_dispatch_propagates_started_at_and_pid(self):
        import directive_watcher.orch_dispatch as od
        source = inspect.getsource(od)
        self.assertIn("started_at=_lbb.utc_iso()", source)
        self.assertIn("worker_pid=_os.getpid()", source)
        self.assertIn("worker_runtime_id=", source)


class TestC7BridgeDocstring(unittest.TestCase):
    """C7 — module docstring documents B2 lives in orchestrator/."""

    def test_module_docstring_mentions_orchestrator_path(self):
        source = inspect.getsource(lb)
        self.assertIn("orchestrator/", source)
        self.assertIn("NOT at", source)
        self.assertIn("loop_engineering", source)


class TestProbe(unittest.TestCase):
    def test_probe_returns_json(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = lb.main_with_args(["--probe"]) if hasattr(lb, "main_with_args") else None
        # argparse path via sys.argv
        with mock.patch.object(sys, "argv", ["live_brain_bridge.py", "--probe"]):
            rc = lb.main()
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        # If we used sys.argv mocking, buf would be empty; in that case, run again differently.
        if not out:
            proc = subprocess.run(
                [sys.executable, str(HERE.parent / "live_brain_bridge.py"), "--probe"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(proc.returncode, 0)
            data = json.loads(proc.stdout)
            self.assertIn("live_brain_repo_root", data)
            self.assertIn("emitter_exists", data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
