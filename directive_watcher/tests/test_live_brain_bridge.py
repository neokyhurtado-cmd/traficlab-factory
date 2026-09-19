"""Smoke tests for directive_watcher.live_brain_bridge.

These tests do not require a live Live Brain runtime. They verify:
  * Stable event_id from (event_type, actor, subject).
  * Subprocess invocation with the canonical emit_event.py.
  * Fail-soft on bad event types and missing emitter.
  * Hook functions emit the right canonical event types for each
    directive_watcher state transition.
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
            self.assertIn("task.failed", cmd)
        finally:
            import shutil
            shutil.rmtree(fake_repo, ignore_errors=True)


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
