"""Tests for scripts/install_hermes_runtime.py.

These tests cover the bounded install path for ASHLEY-AUTO-WAKE-FACTORY-
PROMOTE-20260918-01: the directive_watcher is rolled out to non-orchestrator
Hermes profiles (e.g. Ashley) without granting that profile executable
authority over Factory or IA-VISION. The tests are adversarial in the same
spirit as test_b3_binding_audit.py — they bite.

Test isolation:
  - Use a temp HERMES_HOME tree; do NOT touch the real
    ~/.hermes/profiles/orchestrator/ or ~/.hermes/profiles/david/.
  - Use a temp factory checkout stub (just an empty directory is fine;
    the install only checks .is_dir()).
  - Each test calls install_hermes_runtime.install() directly with a
    controlled set of paths.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

WT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS_DIR = os.path.join(WT, "scripts")
sys.path.insert(0, SCRIPTS_DIR)
import install_hermes_runtime as ihr  # noqa: E402
sys.path.pop(0)


VALID_SHA = "b4dd937af8866a5cfb881cf0be94bf1e85b725ec"
ASHLEY_REPOS = ["neokyhurtado-cmd/suini", "neokyhurtado-cmd/panorama-mission-control"]
ASHLEY_AUTHORS = ["AshleyGomez0", "neokyhurtado-cmd"]


class Harness(unittest.TestCase):
    """Set up an isolated hermes_home + factory_checkout tree for the test."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="install_hermes_runtime_test_")
        self.hermes_home = Path(self.tmp) / "hermes_home"
        self.hermes_install = Path(self.tmp) / "hermes_install"
        self.factory_checkout = Path(self.tmp) / "factory"
        self.hermes_home.mkdir(parents=True, exist_ok=True)
        self.hermes_install.mkdir(parents=True, exist_ok=True)
        self.factory_checkout.mkdir(parents=True, exist_ok=True)
        # Mirror the layout the script expects under hermes_home:
        self.ashley = self.hermes_home / "profiles" / "ashley"
        self.ashley.mkdir(parents=True, exist_ok=True)
        # Pre-create the orchestrator profile so the "refuse to touch
        # orchestrator" guard can be probed.
        self.orchestrator = self.hermes_home / "profiles" / "orchestrator"
        self.orchestrator.mkdir(parents=True, exist_ok=True)
        self.david = self.hermes_home / "profiles" / "david"
        self.david.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestShaValidation(Harness):
    def test_accepts_full_sha(self) -> None:
        self.assertTrue(ihr.is_valid_sha(VALID_SHA))

    def test_accepts_short_sha(self) -> None:
        self.assertTrue(ihr.is_valid_sha("b4dd937"))

    def test_rejects_none(self) -> None:
        self.assertFalse(ihr.is_valid_sha("NONE"))

    def test_rejects_auto_from_issue_context(self) -> None:
        self.assertFalse(ihr.is_valid_sha("AUTO_FROM_ISSUE_CONTEXT"))

    def test_rejects_non_hex(self) -> None:
        self.assertFalse(ihr.is_valid_sha("not-a-sha"))

    def test_rejects_too_long(self) -> None:
        self.assertFalse(ihr.is_valid_sha("a" * 41))

    def test_rejects_too_short(self) -> None:
        self.assertFalse(ihr.is_valid_sha("abcdef"))


class TestInstallGuardrails(Harness):
    def test_refuses_orchestrator_profile(self) -> None:
        rc = ihr.install(
            profile="orchestrator",
            factory_sha=VALID_SHA,
            repos=list(ASHLEY_REPOS),
            authors=list(ASHLEY_AUTHORS),
            hermes_home=self.hermes_home,
            hermes_install=self.hermes_install,
            factory_checkout=self.factory_checkout,
            interval_minutes=2,
            job_name="orch-directive-watcher",
            dry_run=True,
        )
        self.assertEqual(rc, 2)

    def test_refuses_david_profile(self) -> None:
        rc = ihr.install(
            profile="david",
            factory_sha=VALID_SHA,
            repos=list(ASHLEY_REPOS),
            authors=list(ASHLEY_AUTHORS),
            hermes_home=self.hermes_home,
            hermes_install=self.hermes_install,
            factory_checkout=self.factory_checkout,
            interval_minutes=2,
            job_name="david-directive-watcher",
            dry_run=True,
        )
        self.assertEqual(rc, 2)

    def test_refuses_invalid_sha(self) -> None:
        rc = ihr.install(
            profile="ashley",
            factory_sha="NOT-A-SHA",
            repos=list(ASHLEY_REPOS),
            authors=list(ASHLEY_AUTHORS),
            hermes_home=self.hermes_home,
            hermes_install=self.hermes_install,
            factory_checkout=self.factory_checkout,
            interval_minutes=2,
            job_name="ashley-directive-watcher",
            dry_run=True,
        )
        self.assertEqual(rc, 2)

    def test_refuses_empty_repos(self) -> None:
        rc = ihr.install(
            profile="ashley",
            factory_sha=VALID_SHA,
            repos=[],
            authors=list(ASHLEY_AUTHORS),
            hermes_home=self.hermes_home,
            hermes_install=self.hermes_install,
            factory_checkout=self.factory_checkout,
            interval_minutes=2,
            job_name="ashley-directive-watcher",
            dry_run=True,
        )
        self.assertEqual(rc, 2)

    def test_refuses_empty_authors(self) -> None:
        rc = ihr.install(
            profile="ashley",
            factory_sha=VALID_SHA,
            repos=list(ASHLEY_REPOS),
            authors=[],
            hermes_home=self.hermes_home,
            hermes_install=self.hermes_install,
            factory_checkout=self.factory_checkout,
            interval_minutes=2,
            job_name="ashley-directive-watcher",
            dry_run=True,
        )
        self.assertEqual(rc, 2)


class TestInstallHappyPath(Harness):
    def test_dry_run_writes_nothing(self) -> None:
        rc = ihr.install(
            profile="ashley",
            factory_sha=VALID_SHA,
            repos=list(ASHLEY_REPOS),
            authors=list(ASHLEY_AUTHORS),
            hermes_home=self.hermes_home,
            hermes_install=self.hermes_install,
            factory_checkout=self.factory_checkout,
            interval_minutes=2,
            job_name="ashley-directive-watcher",
            dry_run=True,
        )
        self.assertEqual(rc, 0)
        # In dry-run, no FILE is written. Directory creation alone is
        # acceptable (mkdir with exist_ok=True is idempotent and does
        # not count as a state change for rollback purposes).
        runway = self.ashley / "scripts" / "ashley-directive-watcher_runway.py"
        routing = self.ashley / "config" / "routing.yaml"
        repos_yaml = self.ashley / "directive_watcher" / "config" / "repos.yaml"
        authors_yaml = self.ashley / "directive_watcher" / "allowlists" / "authors.prod.yaml"
        for p in [runway, routing, repos_yaml, authors_yaml]:
            self.assertFalse(p.is_file(), f"unexpectedly wrote: {p}")
        # No jobs.json either.
        jobs = self.ashley / "cron" / "jobs.json"
        self.assertFalse(jobs.is_file())

    def test_writes_runway_routing_allowlist(self) -> None:
        rc = ihr.install(
            profile="ashley",
            factory_sha=VALID_SHA,
            repos=list(ASHLEY_REPOS),
            authors=list(ASHLEY_AUTHORS),
            hermes_home=self.hermes_home,
            hermes_install=self.hermes_install,
            factory_checkout=self.factory_checkout,
            interval_minutes=2,
            job_name="ashley-directive-watcher",
            dry_run=False,
        )
        self.assertEqual(rc, 0)
        # All four files written
        runway = self.ashley / "scripts" / "ashley-directive-watcher_runway.py"
        routing = self.ashley / "config" / "routing.yaml"
        repos_yaml = self.ashley / "directive_watcher" / "config" / "repos.yaml"
        authors_yaml = self.ashley / "directive_watcher" / "allowlists" / "authors.prod.yaml"
        for p in [runway, routing, repos_yaml, authors_yaml]:
            self.assertTrue(p.is_file(), f"missing: {p}")
        # Runway pins the SHA
        self.assertIn(VALID_SHA, runway.read_text(encoding="utf-8"))
        # Routing.yaml lists exactly the two repos
        rt = routing.read_text(encoding="utf-8")
        for repo in ASHLEY_REPOS:
            self.assertIn(repo, rt)
        # authors.prod.yaml lists exactly the two authors
        at = authors_yaml.read_text(encoding="utf-8")
        for a in ASHLEY_AUTHORS:
            self.assertIn(a, at)

    def test_idempotent_rerun_no_double_write(self) -> None:
        # First install
        ihr.install(
            profile="ashley",
            factory_sha=VALID_SHA,
            repos=list(ASHLEY_REPOS),
            authors=list(ASHLEY_AUTHORS),
            hermes_home=self.hermes_home,
            hermes_install=self.hermes_install,
            factory_checkout=self.factory_checkout,
            interval_minutes=2,
            job_name="ashley-directive-watcher",
            dry_run=False,
        )
        # Capture cron job id from jobs.json
        jobs = json.loads((self.ashley / "cron" / "jobs.json").read_text(encoding="utf-8"))
        first_job_ids = [j["id"] for j in jobs["jobs"]]
        # Re-run
        ihr.install(
            profile="ashley",
            factory_sha=VALID_SHA,
            repos=list(ASHLEY_REPOS),
            authors=list(ASHLEY_AUTHORS),
            hermes_home=self.hermes_home,
            hermes_install=self.hermes_install,
            factory_checkout=self.factory_checkout,
            interval_minutes=2,
            job_name="ashley-directive-watcher",
            dry_run=False,
        )
        # No second cron job should be registered
        jobs2 = json.loads((self.ashley / "cron" / "jobs.json").read_text(encoding="utf-8"))
        second_job_ids = [j["id"] for j in jobs2["jobs"]]
        self.assertEqual(first_job_ids, second_job_ids)
        self.assertEqual(len(second_job_ids), 1)

    def test_refuses_unrelated_repo(self) -> None:
        # If a directive is posted for neokyhurtado-cmd/traficlab-factory
        # (Factory), the runway's routing.yaml must NOT contain it.
        # This is enforced by --repos being the only entries we write.
        ihr.install(
            profile="ashley",
            factory_sha=VALID_SHA,
            repos=list(ASHLEY_REPOS),
            authors=list(ASHLEY_AUTHORS),
            hermes_home=self.hermes_home,
            hermes_install=self.hermes_install,
            factory_checkout=self.factory_checkout,
            interval_minutes=2,
            job_name="ashley-directive-watcher",
            dry_run=False,
        )
        rt = (self.ashley / "config" / "routing.yaml").read_text(encoding="utf-8")
        self.assertNotIn("traficlab-factory", rt)
        self.assertNotIn("IA-VISION", rt)

    def test_cron_script_field_is_basename(self) -> None:
        # Regression: hermes cron scheduler resolves the script path as
        # HERMES_HOME/scripts/<script>. If we store "scripts/<file>" the
        # scheduler resolves to HERMES_HOME/scripts/scripts/<file>
        # (doubled). The job MUST store ONLY the basename.
        ihr.install(
            profile="ashley",
            factory_sha=VALID_SHA,
            repos=list(ASHLEY_REPOS),
            authors=list(ASHLEY_AUTHORS),
            hermes_home=self.hermes_home,
            hermes_install=self.hermes_install,
            factory_checkout=self.factory_checkout,
            interval_minutes=2,
            job_name="ashley-directive-watcher",
            dry_run=False,
        )
        jobs = json.loads((self.ashley / "cron" / "jobs.json").read_text(encoding="utf-8"))
        self.assertEqual(len(jobs["jobs"]), 1)
        script_path = jobs["jobs"][0]["script"]
        # Must be the basename only — no directory prefix.
        self.assertNotIn("/", script_path)
        self.assertNotIn("\\", script_path)
        self.assertTrue(script_path.endswith("_runway.py"))


class TestCronRegistration(Harness):
    def test_backup_on_overwrite(self) -> None:
        # Pre-create a cron jobs.json with one job.
        cron_dir = self.ashley / "cron"
        cron_dir.mkdir(parents=True, exist_ok=True)
        prior = {"jobs": [{"id": "prior", "name": "old-job"}], "updated_at": "x"}
        (cron_dir / "jobs.json").write_text(json.dumps(prior), encoding="utf-8")

        ihr.install(
            profile="ashley",
            factory_sha=VALID_SHA,
            repos=list(ASHLEY_REPOS),
            authors=list(ASHLEY_AUTHORS),
            hermes_home=self.hermes_home,
            hermes_install=self.hermes_install,
            factory_checkout=self.factory_checkout,
            interval_minutes=2,
            job_name="ashley-directive-watcher",
            dry_run=False,
        )
        # A backup file with .install_backup.<ts> suffix should exist.
        backups = list(cron_dir.glob("jobs.json.install_backup.*"))
        self.assertGreaterEqual(len(backups), 1)
        # The backup content equals the original
        content = json.loads(backups[0].read_text(encoding="utf-8"))
        self.assertEqual(content["jobs"][0]["id"], "prior")

    def test_refuses_unparseable_jobs_json(self) -> None:
        cron_dir = self.ashley / "cron"
        cron_dir.mkdir(parents=True, exist_ok=True)
        (cron_dir / "jobs.json").write_text("not json", encoding="utf-8")
        with self.assertRaises(SystemExit):
            ihr.install(
                profile="ashley",
                factory_sha=VALID_SHA,
                repos=list(ASHLEY_REPOS),
                authors=list(ASHLEY_AUTHORS),
                hermes_home=self.hermes_home,
                hermes_install=self.hermes_install,
                factory_checkout=self.factory_checkout,
                interval_minutes=2,
                job_name="ashley-directive-watcher",
                dry_run=False,
            )


class TestRunwayScriptSelfCheck(Harness):
    """Smoke-check the runway script imports cleanly + has the expected
    symbols even when the env vars are unset. The actual tick is NOT
    exercised here — that requires a live Factory checkout with the
    directive_watcher module on sys.path, which is the production
    runtime's responsibility, not the installer's."""

    def test_runway_imports_without_nameerror(self) -> None:
        ihr.install(
            profile="ashley",
            factory_sha=VALID_SHA,
            repos=list(ASHLEY_REPOS),
            authors=list(ASHLEY_AUTHORS),
            hermes_home=self.hermes_home,
            hermes_install=self.hermes_install,
            factory_checkout=self.factory_checkout,
            interval_minutes=2,
            job_name="ashley-directive-watcher",
            dry_run=False,
        )
        runway = self.ashley / "scripts" / "ashley-directive-watcher_runway.py"
        # Use AST parse to confirm the generated code is syntactically
        # valid Python. Importing the runway at this point would require
        # real HERMES_HOME wiring, which is the runtime's responsibility.
        import ast
        tree = ast.parse(runway.read_text(encoding="utf-8"), filename=str(runway))
        fns = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        self.assertIn("main", fns)

    def test_runway_pins_specific_sha(self) -> None:
        ihr.install(
            profile="ashley",
            factory_sha=VALID_SHA,
            repos=list(ASHLEY_REPOS),
            authors=list(ASHLEY_AUTHORS),
            hermes_home=self.hermes_home,
            hermes_install=self.hermes_install,
            factory_checkout=self.factory_checkout,
            interval_minutes=2,
            job_name="ashley-directive-watcher",
            dry_run=False,
        )
        runway = self.ashley / "scripts" / "ashley-directive-watcher_runway.py"
        body = runway.read_text(encoding="utf-8")
        # The runway must refuse to tick if the SHA is missing — i.e.
        # the FACTORY_SHA literal is present in the rendered source.
        self.assertIn(f'FACTORY_SHA = "{VALID_SHA}"', body)

    def test_runway_main_block_does_not_refer_to_local_from_main(self) -> None:
        # Regression: the diagnostic log inside `if __name__ == "__main__":`
        # must NOT reference `profile_routing` (which is only defined inside
        # main()). It must resolve the path at module scope.
        ihr.install(
            profile="ashley",
            factory_sha=VALID_SHA,
            repos=list(ASHLEY_REPOS),
            authors=list(ASHLEY_AUTHORS),
            hermes_home=self.hermes_home,
            hermes_install=self.hermes_install,
            factory_checkout=self.factory_checkout,
            interval_minutes=2,
            job_name="ashley-directive-watcher",
            dry_run=False,
        )
        runway = self.ashley / "scripts" / "ashley-directive-watcher_runway.py"
        body = runway.read_text(encoding="utf-8")
        # The diagnostic line must reference the underscore-prefixed local.
        self.assertIn("HERMES_ROUTING_PATH (set): {_profile_routing}", body)
        # The bare `profile_routing` reference inside the if-main block is
        # forbidden — it would NameError because main() hasn't run yet.
        main_block = body.split('if __name__ == "__main__":', 1)[1]
        # Allow occurrences in comments but not as a literal f-string token.
        self.assertNotIn("{profile_routing}", main_block)

    def test_runway_runs_as_main_without_nameerror(self) -> None:
        # Smoke test: invoking the runway as `__main__` must NOT raise
        # NameError. The canonical poller (github_poller.py) is not on
        # disk in this isolated hermes_home tree, so we expect main() to
        # exit with EXIT_RUNWAY_BROKEN (5) — that's a clean failure mode,
        # not a NameError.
        ihr.install(
            profile="ashley",
            factory_sha=VALID_SHA,
            repos=list(ASHLEY_REPOS),
            authors=list(ASHLEY_AUTHORS),
            hermes_home=self.hermes_home,
            hermes_install=self.hermes_install,
            factory_checkout=self.factory_checkout,
            interval_minutes=2,
            job_name="ashley-directive-watcher",
            dry_run=False,
        )
        runway = self.ashley / "scripts" / "ashley-directive-watcher_runway.py"
        # Use the same Python interpreter that is running this test.
        proc = subprocess.run(
            [sys.executable, str(runway)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Must NOT be a NameError. The runway's own diagnostic log
        # captures any NameError before main() runs.
        combined = proc.stdout + proc.stderr
        self.assertNotIn("NameError", combined, f"NameError in runway:\n{combined}")
        # The runway will exit 5 because the canonical checkout is empty
        # in this isolated hermes_home tree. That's expected.
        self.assertEqual(proc.returncode, 5, f"unexpected exit: {proc.returncode}\n{combined}")


class TestStableWatcherState(Harness):
    def _install(self, *, legacy_state_root=None, dry_run=False):
        return ihr.install(
            profile="ashley",
            factory_sha=VALID_SHA,
            repos=list(ASHLEY_REPOS),
            authors=list(ASHLEY_AUTHORS),
            hermes_home=self.hermes_home,
            hermes_install=self.hermes_install,
            factory_checkout=self.factory_checkout,
            interval_minutes=2,
            job_name="ashley-directive-watcher",
            dry_run=dry_run,
            legacy_state_root=legacy_state_root,
        )

    def test_runway_pins_profile_local_state_paths(self) -> None:
        rc = self._install()
        self.assertEqual(rc, 0)
        runway = self.ashley / "scripts" / "ashley-directive-watcher_runway.py"
        body = runway.read_text(encoding="utf-8")
        self.assertIn('"HERMES_DIRECTIVE_SIDECAR_DB"', body)
        self.assertIn('"HERMES_SESSION_LOG"', body)
        self.assertIn('"directive_watcher" / "state"', body)
        self.assertIn('"directive_watcher.sqlite"', body)
        self.assertIn('"sessions.jsonl"', body)

    def test_migrates_legacy_state_once_and_preserves_destination(self) -> None:
        legacy = Path(self.tmp) / "legacy-state"
        legacy.mkdir(parents=True, exist_ok=True)
        old_db = legacy / "directive_watcher.sqlite"
        old_sessions = legacy / "sessions.jsonl"
        old_db.write_bytes(b"legacy-db-v1")
        old_sessions.write_text('{"session_id":"legacy-1"}\n', encoding="utf-8")

        rc = self._install(legacy_state_root=legacy)
        self.assertEqual(rc, 0)

        state_dir = self.ashley / "directive_watcher" / "state"
        new_db = state_dir / "directive_watcher.sqlite"
        new_sessions = state_dir / "sessions.jsonl"
        self.assertEqual(new_db.read_bytes(), b"legacy-db-v1")
        self.assertEqual(
            new_sessions.read_text(encoding="utf-8"),
            '{"session_id":"legacy-1"}\n',
        )

        old_db.write_bytes(b"legacy-db-v2")
        old_sessions.write_text('{"session_id":"legacy-2"}\n', encoding="utf-8")
        rc2 = self._install(legacy_state_root=legacy)
        self.assertEqual(rc2, 0)

        self.assertEqual(new_db.read_bytes(), b"legacy-db-v1")
        self.assertEqual(
            new_sessions.read_text(encoding="utf-8"),
            '{"session_id":"legacy-1"}\n',
        )

    def test_dry_run_does_not_copy_legacy_state(self) -> None:
        legacy = Path(self.tmp) / "legacy-state"
        legacy.mkdir(parents=True, exist_ok=True)
        (legacy / "directive_watcher.sqlite").write_bytes(b"legacy")
        (legacy / "sessions.jsonl").write_text("{}\n", encoding="utf-8")

        rc = self._install(legacy_state_root=legacy, dry_run=True)
        self.assertEqual(rc, 0)
        state_dir = self.ashley / "directive_watcher" / "state"
        self.assertFalse((state_dir / "directive_watcher.sqlite").exists())
        self.assertFalse((state_dir / "sessions.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
