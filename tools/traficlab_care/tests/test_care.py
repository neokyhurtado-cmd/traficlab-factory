import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
import urllib.response
from email.message import Message
from unittest.mock import patch
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "care.py"
spec = importlib.util.spec_from_file_location("care", SOURCE)
care = importlib.util.module_from_spec(spec)
spec.loader.exec_module(care)


class CareTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.vault = self.root / "DAVID_OS"
        self.vault.mkdir()
        (self.vault / "mi_nota.md").write_text("Mi nota original", encoding="utf-8")
        self.cfg = {"schema_version": 1, "owner": "david", "state_dir": str(self.root / "state"),
                    "vault_path": str(self.vault), "disk_roots": [str(self.root)], "projects": [],
                    "health_urls": [], "interval_seconds": 3600}

    def tearDown(self):
        self.temp.cleanup()

    def record(self, name, *, age=8 * 86400, owner="david", app=care.APP):
        root = care.init_state(self.cfg)
        path = root / "cache" / name
        path.write_text(json.dumps({"app": app, "owner": owner, "created_epoch": time.time() - age}), encoding="utf-8")
        return path

    def test_real_restart_and_compacted_context_preserve_original_note(self):
        first = care.run_cycle(self.cfg, offline=True)
        second = care.run_cycle(self.cfg, offline=True)
        self.assertEqual(first["obsidian"]["status"], "WRITTEN")
        self.assertEqual(second["obsidian"]["status"], "WRITTEN")
        self.assertEqual((self.vault / "mi_nota.md").read_text(), "Mi nota original")
        self.assertTrue((Path(self.cfg["state_dir"]) / "context.json").is_file())

    def test_due_only_does_not_reexecute(self):
        care.run_cycle(self.cfg, offline=True)
        state = Path(self.cfg["state_dir"]) / "state.json"
        before = state.read_bytes()
        result = care.run_cycle(self.cfg, offline=True, due_only=True)
        self.assertEqual(result["status"], "NOT_DUE")
        self.assertEqual(state.read_bytes(), before)

    def test_user_edit_to_generated_note_is_preserved(self):
        care.run_cycle(self.cfg, offline=True)
        note = next((self.vault / "99_SYSTEM" / "traficlab_care" / "david").glob("20*.md"))
        note.write_text("David agrego informacion", encoding="utf-8")
        result = care.run_cycle(self.cfg, offline=True)
        self.assertEqual(result["obsidian"]["status"], "PRESERVED_USER_EDIT")
        self.assertEqual(note.read_text(), "David agrego informacion")

    def test_unknown_note_never_overwritten(self):
        p = self.vault / "existing.md"
        p.write_text("nota ajena", encoding="utf-8")
        result = care.managed_note(p, "reemplazo", {})
        self.assertEqual(result["status"], "PRESERVED_USER_EDIT")
        self.assertEqual(p.read_text(), "nota ajena")

    def test_state_cannot_overlap_vault_or_repository(self):
        bad = dict(self.cfg, state_dir=str(self.vault / "state"))
        with self.assertRaises(ValueError):
            care.validate_config(bad)
        repo = self.root / "repo"
        repo.mkdir()
        bad = dict(self.cfg, state_dir=str(repo / "state"), projects=[{"repository": "owner/repo", "local_path": str(repo)}])
        with self.assertRaises(ValueError):
            care.validate_config(bad)

    def test_nonempty_unknown_state_is_preserved(self):
        p = Path(self.cfg["state_dir"])
        p.mkdir()
        (p / "original.db").write_bytes(b"unique")
        with self.assertRaises(ValueError):
            care.init_state(self.cfg)
        self.assertEqual((p / "original.db").read_bytes(), b"unique")

    def test_cross_owner_is_refused(self):
        care.init_state(self.cfg)
        other = dict(self.cfg, owner="ashley")
        with self.assertRaises(ValueError):
            care.init_state(other)

    def test_two_profiles_share_vault_but_not_state_or_notes(self):
        ashley = dict(self.cfg, owner="ashley", state_dir=str(self.root / "ashley-state"))
        care.run_cycle(self.cfg, offline=True)
        care.run_cycle(ashley, offline=True)
        for owner, cfg in (("david", self.cfg), ("ashley", ashley)):
            marker = care.read_json(Path(cfg["state_dir"]) / care.MARKER)
            self.assertEqual(marker["owner"], owner)
            index = self.vault / "99_SYSTEM" / "traficlab_care" / owner / "LATEST.md"
            self.assertIn("[[99_SYSTEM/traficlab_care/" + owner + "/", index.read_text())
        self.assertEqual((self.vault / "mi_nota.md").read_text(), "Mi nota original")

    def test_wrong_windows_account_is_refused_before_writing(self):
        cfg = dict(self.cfg, windows_user_sid="S-1-5-21-100")
        with patch.object(care, "current_windows_sid", return_value="S-1-5-21-200"):
            with self.assertRaises(ValueError):
                care.run_cycle(cfg, offline=True)
        self.assertFalse(Path(cfg["state_dir"]).exists())

    def test_single_writer_lock(self):
        root = care.init_state(self.cfg)
        with care.RunLock(root):
            with self.assertRaises(RuntimeError):
                with care.RunLock(root):
                    pass
        self.assertFalse((root / "run.lock").exists())

    def test_cleanup_dry_run_then_bounded_apply_only_own_cache(self):
        stale = self.record("gh-aaaaaaaa.json")
        fresh = self.record("gh-bbbbbbbb.json", age=10)
        unknown = self.record("notes.json")
        other = self.record("gh-cccccccc.json", owner="ashley")
        p = Path(self.cfg["state_dir"])
        dry = care.clean_cache(p, "david")
        self.assertEqual(len(dry["candidates"]), 1)
        self.assertTrue(stale.exists())
        applied = care.clean_cache(p, "david", apply=True)
        self.assertGreater(applied["removed_bytes"], 0)
        self.assertFalse(stale.exists())
        self.assertTrue(all(x.exists() for x in (fresh, unknown, other)))
        self.assertEqual((self.vault / "mi_nota.md").read_text(), "Mi nota original")

    def test_cleanup_cap_preserves_large_candidate(self):
        stale = self.record("gh-aaaaaaaa.json")
        care.clean_cache(Path(self.cfg["state_dir"]), "david", apply=True, max_bytes=1)
        self.assertTrue(stale.exists())

    def test_corrupt_cache_is_preserved(self):
        p = self.record("gh-aaaaaaaa.json")
        p.write_text("not json", encoding="utf-8")
        care.clean_cache(Path(self.cfg["state_dir"]), "david", apply=True)
        self.assertTrue(p.exists())

    def test_cache_unknown_nonfinite_timestamp_is_preserved(self):
        p = self.record("gh-aaaaaaaa.json")
        record = care.read_json(p)
        record["created_epoch"] = float("nan")
        p.write_text(json.dumps(record), encoding="utf-8")
        care.clean_cache(Path(self.cfg["state_dir"]), "david", apply=True)
        self.assertTrue(p.exists())

    def test_symlink_cache_target_is_preserved(self):
        root = care.init_state(self.cfg)
        outside = self.root / "outside.json"
        outside.write_text("unique", encoding="utf-8")
        link = root / "cache" / "gh-aaaaaaaa.json"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("Symlink privilege unavailable on this host")
        result = care.clean_cache(root, "david", apply=True)
        self.assertIn(link.name, result["preserved"])
        self.assertEqual(outside.read_text(), "unique")

    def test_symlink_owned_directory_is_refused(self):
        root = care.init_state(self.cfg)
        (root / "cache").rmdir()
        outside = self.root / "outside"
        outside.mkdir()
        try:
            (root / "cache").symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Symlink privilege unavailable on this host")
        with self.assertRaises(ValueError):
            care.clean_cache(root, "david", apply=True)

    def test_windows_links_unknown_tags_and_cloud_placeholders(self):
        for tag in (0, 0xA0000003, 0xA000000C, 0x9000001C):
            self.assertTrue(care.blocked_windows_reparse(0x400, tag))
        for variant in range(16):
            self.assertFalse(care.blocked_windows_reparse(0x400, 0x9000001A | (variant << 12)))
        self.assertFalse(care.blocked_windows_reparse(0, 0))

    def test_adapter_without_timestamp_is_not_fresh(self):
        p = self.root / "guardian.json"
        p.write_text('{"status":"PASS"}', encoding="utf-8")
        result = care.evidence_adapter(str(p))
        self.assertEqual(result["status"], "UNKNOWN_FRESHNESS")

    def test_remote_health_address_is_refused_without_network(self):
        self.assertEqual(care.health_probe("http://example.com/health")["status"], "REFUSED_NON_LOCAL_ENDPOINT")

    def test_local_health_does_not_follow_redirect(self):
        seen = []
        class StubHTTPHandler(urllib.request.HTTPHandler):
            def http_open(self, request):
                seen.append(request.full_url)
                headers = Message()
                headers["Location"] = "http://external.invalid/redirected"
                response = urllib.response.addinfourl(io.BytesIO(b""), headers, request.full_url, code=302)
                response.msg = "Found"
                return response
        with patch.object(urllib.request, "HTTPHandler", StubHTTPHandler):
            result = care.health_probe("http://127.0.0.1/health")
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertEqual(result["error"], "HTTPError")
        self.assertEqual(seen, ["http://127.0.0.1/health"])

    def test_python_audit_is_explicitly_not_a_benchmark(self):
        text = "def f(rows, db):\n    for row in rows:\n        db.execute(row)\n"
        findings = care.audit_python_file(text, "sample.py")
        self.assertEqual(findings[0]["kind"], "IO_IN_LOOP")
        self.assertEqual(findings[0]["status"], "MEASURE_FIRST")

    @unittest.skipUnless(shutil.which("git"), "Git unavailable")
    def test_repository_audit_is_read_only_and_records_commit(self):
        repo = self.root / "repo"
        repo.mkdir()
        source = repo / "sample.py"
        source.write_text("def f(rows, db):\n    for row in rows:\n        db.execute(row)\n", encoding="utf-8")
        for argv in (["git", "init", "-q", str(repo)], ["git", "-C", str(repo), "add", "sample.py"],
                     ["git", "-C", str(repo), "-c", "user.name=Care Test", "-c", "user.email=care@example.invalid", "commit", "-qm", "fixture"]):
            subprocess.run(argv, check=True, capture_output=True)
        before = source.read_bytes()
        result = care.audit_repository({"repository": "owner/repo", "local_path": str(repo)})
        self.assertEqual(result["status"], "STATIC_ANALYSIS")
        self.assertEqual(result["files_scanned"], 1)
        self.assertEqual(result["findings"][0]["kind"], "IO_IN_LOOP")
        self.assertEqual(len(result["local_git"]["head_sha"]), 40)
        self.assertFalse(result["local_git"]["dirty"])
        self.assertEqual(source.read_bytes(), before)
        self.assertFalse(care.local_git_status(str(repo))["dirty"])

    def test_github_cached_snapshot_keeps_observation_timestamp(self):
        root = care.init_state(self.cfg)
        repo = "owner/repo"
        timestamp = "2026-01-01T00:00:00+00:00"
        path = root / "cache" / ("gh-" + care.digest(repo)[:20] + ".json")
        care.write_json(path, {"app": care.APP, "owner": "david", "created_epoch": time.time(),
                              "observed_at": timestamp, "data": {"status": "GITHUB_OBSERVED", "repository": repo}})
        result = care.github_project({"repository": repo}, root / "cache", "david")
        self.assertEqual(result["transport"], "CACHE")
        self.assertEqual(result["observed_at"], timestamp)

    def test_html_escapes_external_content(self):
        rendered = care.html_report("<script>alert(1)</script>", {"generated_at": "now"})
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)

    def test_cli_offline_creates_report_and_records_unavailable_sources(self):
        cfg = dict(self.cfg, projects=[{"repository": "owner/repo", "local_path": ""}])
        config_path = self.root / "config.json"
        config_path.write_text(json.dumps(cfg), encoding="utf-8")
        p = subprocess.run([sys.executable, str(SOURCE), "run", "--config", str(config_path), "--offline"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        report = care.read_json(next((Path(cfg["state_dir"]) / "reports").glob("*.json")))
        self.assertEqual(report["projects"][0]["github"]["status"], "OFFLINE")
        self.assertEqual(report["housekeeper"]["status"], "NOT_CONFIGURED")


if __name__ == "__main__":
    unittest.main()
