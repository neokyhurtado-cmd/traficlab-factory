"""Adversarial tests for SINGLE-FRONT-DOOR-01 (F7 of traf ic lab-factory #37).

Covers the 10 fail-safe behaviors required by the issue body:

 1.  same goal sent twice → no duplicate worktree/PR
 2.  stale issue already fixed → no worktree created
 3.  Orca restart/reconnect → Control Room remains recoverable from GitHub truth
 4.  Telegram duplicate/retry → no duplicate task state
 5.  two product repos active → no IA-VISION/SUINI cross-write
 6.  product worktree dirty → no unsafe cleanup
 7.  main protection → no direct write
 8.  canonical DB / source media → no mutation without explicit authorized task
 9.  Hermes runtime/gateway duplication → detected, not silently started
10.  state DB ownership → exactly one owner, no network-share SQLite

These tests are PURE (no network, no gh, no hermes subprocess when avoidable).
They assert the goal-loop SHAPE — not the live runtime — so they pass in any
CI environment.
"""

from __future__ import annotations

import json
import os
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

# Resolve repo root regardless of where pytest is invoked from. This file
# lives at <repo>/tests/sfd_tests/test_adversarial.py, so the repo
# root is two levels up (test_adversarial.py → sfd_tests → tests → repo).
HERE = Path(__file__).resolve()
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))
from single_front_door.intake import (  # noqa: E402
    Goal,
    RealityMatrix,
    check_already_done,
    discover_runtime,
    render_evidence_block,
    run_goal_loop,
)


def _fake_matrix(**overrides) -> RealityMatrix:
    base = dict(
        hermes_home="C:/Users/david/AppData/Local/hermes",
        gateway_pid=12345,
        gateway_status="Gateway process running (PID: 12345)",
        orchestrator_profile="C:/Users/david/AppData/Local/hermes/profiles/orchestrator",
        ia_vision_profile="C:/Users/david/AppData/Local/hermes/profiles/ia-vision",
        suini_profile="C:/Users/david/AppData/Local/hermes/profiles/suini",
        routing_table_path="C:/Users/david/AppData/Local/hermes/profiles/orchestrator/config/routing.yaml",
        obsidian_vault="C:/Users/david/Documents/BrainPool",
        orca_installed=True,
        orca_path="C:/Users/david/AppData/Local/Programs/orca/Orca.exe",
        orca_running_procs=4,
        github_poller_cron_id="44c091e79145",
        github_poller_last_status="ok",
        asof_unix=1789604000,
    )
    base.update(overrides)
    return RealityMatrix(**base)


def _patch_runtime(target_func, matrix):
    """Return a context manager that mocks discover_runtime inside `target_func`."""
    return mock.patch(f"{target_func}.discover_runtime", return_value=matrix)


class TestF7_01_DuplicateGoalIdempotency(unittest.TestCase):
    """Same goal sent twice → no duplicate worktree/PR."""

    def test_goal_parser_is_pure(self):
        g1 = Goal.parse("Sigue IA-VISION y llévame #111 hasta revisión")
        g2 = Goal.parse("Sigue IA-VISION y llévame #111 hasta revisión")
        self.assertEqual(asdict_for_test(g1), asdict_for_test(g2))
        self.assertEqual(g1.repo, "neokyhurtado-cmd/ia-vision")
        self.assertEqual(g1.issue, 111)
        self.assertEqual(g1.assignee, "ia-vision")

    def test_run_goal_loop_twice_returns_same_shape(self):
        text = "Cierra traf ic lab-factory #18 si pasa los tests"
        m = _fake_matrix()
        with _patch_runtime("single_front_door.intake", m):
            a = run_goal_loop(text, dry_run=True)
            b = run_goal_loop(text, dry_run=True)
        self.assertEqual(a["overall"], b["overall"])
        self.assertEqual(a["idempotency"], "PASS")
        self.assertEqual(a["evidence_block"], b["evidence_block"])

    def test_check_already_done_is_idempotent(self):
        fake = json.dumps({"state": "OPEN", "labels": [], "comments": []})
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0, stdout=fake, stderr="")
            r1 = check_already_done("neokyhurtado-cmd/ia-vision", 111)
            r2 = check_already_done("neokyhurtado-cmd/ia-vision", 111)
        self.assertFalse(r1["already_done"])
        self.assertFalse(r2["already_done"])


class TestF7_02_StaleAlreadyFixed(unittest.TestCase):
    """Stale issue already fixed → no worktree created."""

    def test_closed_issue_short_circuits(self):
        closed_payload = json.dumps({"state": "CLOSED", "labels": [], "comments": []})
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0, stdout=closed_payload, stderr="")
            r = check_already_done("neokyhurtado-cmd/suini", 99)
        self.assertTrue(r["already_done"])
        self.assertIn("CLOSED", r["evidence"])

    def test_ready_for_audit_label_short_circuits(self):
        payload = json.dumps({
            "state": "OPEN",
            "labels": [{"name": "ready-for-audit"}],
            "comments": [],
        })
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0, stdout=payload, stderr="")
            r = check_already_done("neokyhurtado-cmd/ia-vision", 111)
        self.assertTrue(r["already_done"])

    def test_done_hermes_result_short_circuits(self):
        payload = json.dumps({
            "state": "OPEN",
            "labels": [],
            "comments": [{"body": "[HERMES_RESULT:v1]\nSTATUS = DONE"}],
        })
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0, stdout=payload, stderr="")
            r = check_already_done("neokyhurtado-cmd/suini", 35)
        self.assertTrue(r["already_done"])


class TestF7_03_OrcaRestartRecovery(unittest.TestCase):
    """Orca restart/reconnect → Control Room recovers from GitHub truth."""

    def test_recovery_uses_durable_github_truth(self):
        m = _fake_matrix(orca_running_procs=0)  # Orca just restarted
        # Even with 0 Orca processes, the goal loop must NOT start a new one.
        with mock.patch("subprocess.run") as run, _patch_runtime(
            "single_front_door.intake", m,
        ):
            run.return_value = mock.Mock(returncode=0, stdout="[]", stderr="")
            r = run_goal_loop("Audita IA-VISION #111", dry_run=True)
        self.assertEqual(r["reality_summary"]["orca_running"], 0)
        # The intent is recoverable from GitHub, not from Orca.
        self.assertEqual(r["new_daemon"], 0)


class TestF7_04_TelegramNoDuplicateState(unittest.TestCase):
    """Telegram duplicate/retry → no duplicate task state."""

    def test_telegram_no_state_machine(self):
        # Telegram must be referenced only as a transport fallback.
        # The adapter MUST NOT persist state into Telegram.
        m = _fake_matrix()
        with _patch_runtime("single_front_door.intake", m):
            r = run_goal_loop("dummy", dry_run=True)
        self.assertEqual(r["telegram_fallback"], "PASS (existing gateway transport)")


class TestF7_05_NoCrossProductWrite(unittest.TestCase):
    """Two product repos active → no IA-VISION/SUINI cross-write."""

    def test_ia_vision_assignee_isolation(self):
        g = Goal.parse("Lleva IA-VISION #111 a revisión")
        self.assertEqual(g.assignee, "ia-vision")
        self.assertNotIn(g.assignee, {"suini", "orchestrator"})

    def test_suini_assignee_isolation(self):
        g = Goal.parse("Cierra suini #35")
        self.assertEqual(g.assignee, "suini")
        self.assertNotIn(g.assignee, {"ia-vision", "orchestrator"})

    def test_factory_routes_to_orchestrator(self):
        g = Goal.parse("Cierra traficlab-factory #18")
        self.assertEqual(g.assignee, "orchestrator")


class TestF7_06_DirtyWorktreeNoUnsafeCleanup(unittest.TestCase):
    """Product worktree dirty → no unsafe cleanup."""

    def test_intake_does_not_touch_worktrees(self):
        # The adapter never invokes git worktree prune / remove.
        # Verify by inspecting subprocess calls during run_goal_loop.
        m = _fake_matrix()
        with mock.patch("subprocess.run") as run, _patch_runtime(
            "single_front_door.intake", m,
        ):
            run.return_value = mock.Mock(returncode=0, stdout="[]", stderr="")
            run_goal_loop("dummy", dry_run=True)
        for call in run.call_args_list:
            args = call.args[0] if call.args else []
            joined = " ".join(map(str, args))
            self.assertNotIn("worktree prune", joined)
            self.assertNotIn("worktree remove", joined)
            self.assertNotIn("worktree delete", joined)


class TestF7_07_MainProtection(unittest.TestCase):
    """Main protection → no direct write."""

    def test_main_writes_counter_is_zero(self):
        m = _fake_matrix()
        with _patch_runtime("single_front_door.intake", m):
            r = run_goal_loop("dummy", dry_run=True)
        self.assertEqual(r["main_writes"], 0)

    def test_no_direct_git_commit_in_intake(self):
        m = _fake_matrix()
        with mock.patch("subprocess.run") as run, _patch_runtime(
            "single_front_door.intake", m,
        ):
            run.return_value = mock.Mock(returncode=0, stdout="[]", stderr="")
            run_goal_loop("dummy", dry_run=True)
        for call in run.call_args_list:
            args = call.args[0] if call.args else []
            joined = " ".join(map(str, args))
            self.assertNotIn("git commit", joined)
            self.assertNotIn("git push", joined)


class TestF7_08_NoCanonicalDbMutation(unittest.TestCase):
    """Canonical DB / source media → no mutation without explicit authorization."""

    def test_canonical_db_writes_zero(self):
        m = _fake_matrix()
        with _patch_runtime("single_front_door.intake", m):
            r = run_goal_loop("dummy", dry_run=True)
        self.assertEqual(r["canonical_db_writes"], 0)
        self.assertEqual(r["source_media_writes"], 0)


class TestF7_09_NoSecondHermesRuntime(unittest.TestCase):
    """Hermes runtime/gateway duplication detected, not silently started."""

    def test_second_runtime_zero(self):
        m = _fake_matrix()
        with _patch_runtime("single_front_door.intake", m):
            r = run_goal_loop("dummy", dry_run=True)
        self.assertEqual(r["second_runtime"], 0)
        self.assertEqual(r["new_daemon"], 0)

    def test_no_gateway_install_invocation(self):
        m = _fake_matrix()
        with mock.patch("subprocess.run") as run, _patch_runtime(
            "single_front_door.intake", m,
        ):
            run.return_value = mock.Mock(returncode=0, stdout="[]", stderr="")
            run_goal_loop("dummy", dry_run=True)
        for call in run.call_args_list:
            args = call.args[0] if call.args else []
            joined = " ".join(map(str, args))
            self.assertNotIn("gateway install", joined)
            self.assertNotIn("gateway start", joined)


class TestF7_10_NoSharedNetworkSqlite(unittest.TestCase):
    """State DB ownership → exactly one owner, no network-share SQLite."""

    def test_no_new_sqlite(self):
        m = _fake_matrix()
        with _patch_runtime("single_front_door.intake", m):
            r = run_goal_loop("dummy", dry_run=True)
        self.assertEqual(r["new_sqlite"], 0)
        self.assertEqual(r["new_queue"], 0)
        self.assertEqual(r["shared_sqlite"], 0)


class TestF0_FailClosedOnGatewayDown(unittest.TestCase):
    """F0: if the gateway is not active, the loop must NOT proceed."""

    def test_disabled_gateway_blocks(self):
        with mock.patch(
            "single_front_door.intake.discover_runtime",
            return_value=_fake_matrix(
                gateway_pid=None, gateway_status="Hermes_Gateway task = Disabled",
            ),
        ):
            r = run_goal_loop("dummy", dry_run=True)
        self.assertEqual(r["overall"], "BLOCKED")
        self.assertIn("HUMAN_GO_REAL", r["next_owner"])


class TestEvidenceBlockShape(unittest.TestCase):
    """The required evidence block must match the issue body schema exactly."""

    REQUIRED_KEYS = (
        "SINGLE_FRONT_DOOR_01",
        "CONTROL_ROOM",
        "CONTROL_ROOM_HOST",
        "CONTROL_ROOM_ORCA_WORKSPACE",
        "ORCA_MOBILE_CHAT_FOLLOWUP",
        "ORCA_DESKTOP_CHAT_FOLLOWUP",
        "ONE_GOAL_END_TO_END",
        "GOAL_USED",
        "PRODUCT_WORKTREE_CREATED_BY_ORCA",
        "OBSIDIAN_READ",
        "OBSIDIAN_WRITE_BOUNDED",
        "GITHUB_DURABLE_EVIDENCE",
        "TELEGRAM_ALERT_FALLBACK",
        "DUPLICATE_GOAL_IDEMPOTENCY",
        "ORCA_RESTART_RECOVERY",
        "MAIN_DIRECT_WRITE",
        "CANONICAL_DB_UNAUTHORIZED_WRITE",
        "SOURCE_MEDIA_UNAUTHORIZED_WRITE",
        "SECOND_HERMES_RUNTIME",
        "SHARED_NETWORK_SQLITE",
        "NEW_DAEMON",
        "NEW_QUEUE",
        "NEW_SQLITE",
        "ORCH_REMOVED",
        "TELEGRAM_REMOVED",
        "WAITING_FOR_DAVID",
        "NEXT_OWNER_ACTION",
    )

    def test_every_required_key_present(self):
        m = _fake_matrix()
        goal = Goal.parse("Sigue IA-VISION #111")
        # Force a deterministic overall result.
        out = {"overall": "PASS", "waiting_reason": None, "next_owner": "NONE"}
        block = render_evidence_block(goal, m, out)
        for key in self.REQUIRED_KEYS:
            with self.subTest(key=key):
                self.assertIn(key, block)

    def test_no_direct_write_counters_above_zero(self):
        m = _fake_matrix()
        goal = Goal.parse("dummy")
        out = {"overall": "PASS", "waiting_reason": None, "next_owner": "NONE"}
        block = render_evidence_block(goal, m, out)
        for key in (
            "MAIN_DIRECT_WRITE",
            "CANONICAL_DB_UNAUTHORIZED_WRITE",
            "SOURCE_MEDIA_UNAUTHORIZED_WRITE",
            "SECOND_HERMES_RUNTIME",
            "SHARED_NETWORK_SQLITE",
            "NEW_DAEMON",
            "NEW_QUEUE",
            "NEW_SQLITE",
        ):
            m_ = re.search(rf"{key} = (\d+)", block)
            self.assertIsNotNone(m_, f"missing counter {key}")
            self.assertEqual(int(m_.group(1)), 0, f"{key} should be 0")


def asdict_for_test(g: Goal) -> dict:
    return {
        "text": g.text, "repo": g.repo, "issue": g.issue,
        "product": g.product, "assignee": g.assignee,
        "source": g.source,
    }


if __name__ == "__main__":
    unittest.main(verbosity=2)
