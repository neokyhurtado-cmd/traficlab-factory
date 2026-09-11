"""Adversarial tests for the B3 binding audit script.

Per Astra review 5181335515 on PR #21, the audit must prove:
  (a) Adapter self-reference + an unrelated production merge
      callable => UNWIRED (never WIRED).
  (b) Merge callable under a non-watched root (or an additional
      root the script does scan) without any seam caller =>
      detected UNWIRED.
  (c) Real production caller that imports the seam + a merge
      callable behind that caller => WIRED.

Plus regression tests that verify the v2 audit covers multiple
production roots (directive_watcher/ + orchestrator/).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


WT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _run_audit(roots=None):
    """Run the audit script with optional --root overrides via env
    or argv. Returns (stdout, report_json_dict)."""
    # We can't easily monkey-patch DEFAULT_PRODUCTION_ROOTS from
    # outside, so we use the import path: import the module and call
    # its audit() function directly with custom roots.
    audit_path = os.path.join(WT, "scripts", "b3_binding_audit.py")
    sys.path.insert(0, os.path.dirname(audit_path))
    import b3_binding_audit as mod
    if roots is not None:
        report = mod.audit(production_roots=roots)
    else:
        report = mod.audit()
    sys.path.pop(0)
    return report


def _make_fake_repo(layout):
    """Build a tempdir with the requested directory structure. Each
    entry in layout is a relative path. Files contain a body, or are
    empty if body=None.
    Returns (tmpdir, root_path).
    """
    tmp = tempfile.mkdtemp(prefix="b3_fake_repo_")
    for rel, body in layout:
        full = os.path.join(tmp, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        if body is not None:
            with open(full, "w", encoding="utf-8") as f:
                f.write(body)
    return tmp, tmp


class TestAuditV2(unittest.TestCase):
    def test_repo_wide_classification_when_neither_caller_nor_merge_exists(self):
        """Vanilla repo: no merge callable anywhere, no seam caller.
        Per-root and repo-wide must both be PRODUCTION_MERGE_PATH_NOT_PRESENT."""
        report = _run_audit()
        # Verify the default scan includes both roots
        self.assertEqual(
            sorted(report["production_roots"]),
            ["directive_watcher", "orchestrator"],
            f"expected both roots, got {report['production_roots']}",
        )
        for r in report["per_root"]:
            self.assertEqual(
                r["classification"],
                "PRODUCTION_MERGE_PATH_NOT_PRESENT",
                f"root {r['root']}: {r['classification']}",
            )
            self.assertEqual(r["production_caller_count"], 0)
            self.assertFalse(r["merge_callable_present_in_production"])
        self.assertEqual(
            report["repo_wide"]["repo_classification"],
            "PRODUCTION_MERGE_PATH_NOT_PRESENT (repo-wide)",
        )
        self.assertFalse(report["repo_wide"]["any_merge_in_production"])
        self.assertFalse(report["repo_wide"]["any_caller_in_production"])

    def test_v2_canonical_classification_does_not_use_any_ref_on_token_refs(self):
        """Verify that the canonical repo classification depends on
        production_caller_refs (caller_refs), not seam_token_reverse_refs.
        The current state has seam_token_reverse_refs populated (because
        the adapter is part of directive_watcher/), but production_caller_
        refs is empty. The classification MUST be PATH_NOT_PRESENT, not WIRED.
        This is the v1 → v2 bug-fix proof."""
        report = _run_audit()
        # In directive_watcher, the adapter itself contains seam tokens
        # but is excluded from caller_refs. token_refs should be populated;
        # caller_refs should be empty.
        dw = next(r for r in report["per_root"]
                  if r["root"] == "directive_watcher")
        self.assertTrue(
            any(dw["seam_token_reverse_refs"].values()),
            "expected token_refs populated by the adapter",
        )
        self.assertEqual(
            dw["production_caller_refs"], {},
            f"production caller_refs must be empty, got {dw['production_caller_refs']}",
        )
        self.assertEqual(
            dw["classification"],
            "PRODUCTION_MERGE_PATH_NOT_PRESENT",
            "BUG: v1-style bug — any_ref on token_refs would have classified WIRED",
        )

    def test_orchestrator_root_is_audited(self):
        """Verify the orchestrator/ root is explicitly included and
        reports independently from directive_watcher/."""
        report = _run_audit()
        roots = [r["root"] for r in report["per_root"]]
        self.assertIn("orchestrator", roots)
        self.assertIn("directive_watcher", roots)
        orch = next(r for r in report["per_root"]
                    if r["root"] == "orchestrator")
        self.assertIn("classification", orch)
        self.assertIn("production_caller_count", orch)
        self.assertIn("merge_callable_present_in_production", orch)


class TestAuditAdversarialWithFakeRepos(unittest.TestCase):
    """Adversarial: build a fake repo with known code and verify the
    audit classifies correctly under all three scenarios Astra
    required: (a) adapter-self + merge callable => UNWIRED, (b) merge
    in orchestrator + no seam caller => UNWIRED detected, (c) real
    production caller + merge behind seam => WIRED."""

    def setUp(self):
        # Create a tiny fake repo that has directive_watcher/ + orchestrator/
        # structure. We use a minimal layout to make assertions
        # predictable.
        self.tmp = tempfile.mkdtemp(prefix="b3_adv_repo_")
        self.dw = os.path.join(self.tmp, "directive_watcher")
        self.orch = os.path.join(self.tmp, "orchestrator")
        os.makedirs(self.dw, exist_ok=True)
        os.makedirs(self.orch, exist_ok=True)
        # The "self" files the audit always excludes
        os.makedirs(os.path.join(self.dw, "tests"), exist_ok=True)
        self.adapter = os.path.join(self.dw, "b3_adapter.py")
        self.caller = os.path.join(self.dw, "real_caller.py")
        self.merger = os.path.join(self.dw, "merger.py")
        self.orch_merger = os.path.join(self.orch, "orch_merger.py")
        self.dw_test = os.path.join(self.dw, "tests", "test_x.py")
        self.p1_gate = os.path.join(self.tmp, "p1_human_go_gate")
        os.makedirs(self.p1_gate, exist_ok=True)
        self.seam = os.path.join(self.p1_gate, "seam.py")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_adapter(self):
        with open(self.adapter, "w", encoding="utf-8") as f:
            f.write(
                "from seam import run_or_bite\n"
                "def hermes2_merge_pr_19(c, cb): return run_or_bite(c, cb)\n"
            )

    def _write_seam(self):
        with open(self.seam, "w", encoding="utf-8") as f:
            f.write("def run_or_bite(*a, **k): return {'merged': True}\n")

    def _write_merger(self, body):
        os.makedirs(os.path.dirname(self.merger), exist_ok=True)
        with open(self.merger, "w", encoding="utf-8") as f:
            f.write(body)

    def _write_caller(self, body):
        with open(self.caller, "w", encoding="utf-8") as f:
            f.write(body)

    def _write_orch_merger(self, body):
        with open(self.orch_merger, "w", encoding="utf-8") as f:
            f.write(body)

    def _run_against(self):
        # Import the audit module and call audit() with our fake roots
        sys.path.insert(0, os.path.join(WT, "scripts"))
        import b3_binding_audit as mod
        report = mod.audit(production_roots=[self.dw, self.orch])
        sys.path.pop(0)
        return report

    # -------- Test (a): token_refs populated, no real caller, merge exists => UNWIRED
    def test_a_token_refs_populated_but_no_real_caller_is_UNWIRED_not_WIRED(self):
        """v1 bug proof: even when seam tokens appear in production
        token_refs (e.g. a docstring mention or string literal that
        mentions 'human_go_gate'), if no production caller traverses
        the seam, the classification MUST be UNWIRED, never WIRED.
        This is the v1 -> v2 bug-fix proof."""
        self._write_seam()
        # Write a module that mentions a seam token in a string but
        # does NOT import the seam. token_refs will pick up the
        # mention, but production_caller_refs (which counts only
        # actual imports / executable references) will not.
        docstring_only_path = os.path.join(self.dw, "docs_mention.py")
        with open(docstring_only_path, "w", encoding="utf-8") as f:
            f.write(
                '"""Module that mentions human_go_gate in docstrings only."""\n'
                "import subprocess\n"
                "def nothing():\n"
                '    """See human_go_gate for context."""\n'
                "    pass\n"
            )
        # Real merge callable exists in production
        self._write_merger(
            "import subprocess\n"
            "def merge_pr(): subprocess.run(['gh', 'pr', 'merge', '1'])\n"
        )
        report = self._run_against()
        dw = next(r for r in report["per_root"]
                  if r["root"].endswith("directive_watcher"))
        # Preconditions: token_refs populated, production_caller_refs empty
        self.assertTrue(
            any(dw["seam_token_reverse_refs"].values()),
            "precondition: token_refs is populated (docstring mention)",
        )
        self.assertEqual(
            dw["production_caller_refs"], {},
            f"precondition: production_caller_refs must be empty, "
            f"got {dw['production_caller_refs']}",
        )
        self.assertTrue(
            dw["merge_callable_present_in_production"],
            "precondition: merger.py has gh pr merge in executable code",
        )
        # The bug-fix proof: classification must be UNWIRED, never WIRED.
        self.assertEqual(
            dw["classification"],
            "B3_PRODUCTION_BINDING = UNWIRED",
            f"v2 classification wrong: {dw['classification']} — "
            f"WIRED would be the v1 bug surfacing again",
        )
        self.assertIn("Direct merge calls are NOT gated",
                      dw["classification_reason"])

    # -------- Test (b): merge in orchestrator + no seam caller -------
    def test_b_orchestrator_merge_with_no_seam_caller_detected_UNWIRED(self):
        self._write_seam()
        self._write_adapter()
        # No merger in directive_watcher; merge only in orchestrator
        self._write_orch_merger(
            "import subprocess\n"
            "def orch_merge(): subprocess.run(['gh', 'pr', 'merge', '99'])\n"
        )
        report = self._run_against()
        dw = next(r for r in report["per_root"]
                  if r["root"].endswith("directive_watcher"))
        orch = next(r for r in report["per_root"]
                    if r["root"].endswith("orchestrator"))
        self.assertFalse(dw["merge_callable_present_in_production"])
        self.assertFalse(orch["production_caller_count"] > 0)
        self.assertTrue(orch["merge_callable_present_in_production"])
        # orchestrator MUST detect the unwired merge
        self.assertEqual(
            orch["classification"],
            "B3_PRODUCTION_BINDING = UNWIRED",
            f"orchestrator classification wrong: {orch['classification']}",
        )
        # Repo-wide rollup: any_unwired_root must be True
        self.assertTrue(
            report["repo_wide"]["any_unwired_root"],
            "repo-wide rollup must flag any_unwired_root when "
            "orchestrator has unwired merge callable",
        )
        self.assertEqual(
            report["binding_classification"],
            "B3_PRODUCTION_BINDING = UNWIRED (repo-wide; at least one root unwired)",
        )

    # -------- Test (c): real production caller + merge behind seam ---
    def test_c_real_caller_plus_merge_behind_seam_is_WIRED(self):
        self._write_seam()
        self._write_adapter()
        self._write_merger(
            "import subprocess\n"
            "def merge_pr(): subprocess.run(['gh', 'pr', 'merge', '1'])\n"
        )
        # Real production caller imports the seam and routes through it
        self._write_caller(
            "from seam import run_or_bite\n"
            "def do_merge(c):\n"
            "    return run_or_bite(c, lambda x: merge_pr())\n"
        )
        report = self._run_against()
        dw = next(r for r in report["per_root"]
                  if r["root"].endswith("directive_watcher"))
        self.assertTrue(
            any(dw["production_caller_refs"].values()),
            "precondition: production_caller_refs contains real_caller.py",
        )
        self.assertEqual(
            dw["classification"],
            "B3_PRODUCTION_BINDING = WIRED",
            f"expected WIRED when real caller + merge callable both present",
        )
        # Repo-wide must also be WIRED
        self.assertEqual(
            report["binding_classification"],
            "B3_PRODUCTION_BINDING = WIRED (repo-wide)",
        )

    # -------- Test (d): root with caller but no merge => WIRED_LIB_ONLY ---
    def test_d_root_with_caller_but_no_merge_is_LIB_ONLY(self):
        self._write_seam()
        self._write_adapter()
        # No merger anywhere
        self._write_caller(
            "from seam import run_or_bite\n"
            "def do_merge(c):\n"
            "    return run_or_bite(c, lambda x: None)\n"
        )
        report = self._run_against()
        dw = next(r for r in report["per_root"]
                  if r["root"].endswith("directive_watcher"))
        self.assertFalse(dw["merge_callable_present_in_production"])
        self.assertTrue(any(dw["production_caller_refs"].values()))
        self.assertEqual(
            dw["classification"],
            "B3_PRODUCTION_BINDING = WIRED_LIB_ONLY",
        )


class TestAuditRealWorld(unittest.TestCase):
    """Run the audit on the actual repo and verify the report
    structure: per_root + repo_wide keys present, JSON persists."""

    def test_real_repo_audit_persists_and_has_required_keys(self):
        # Execute the audit script as a subprocess so we exercise the
        # main() entry point, not just the audit() function.
        r = subprocess.run(
            [sys.executable, "scripts/b3_binding_audit.py"],
            capture_output=True, text=True, cwd=WT, timeout=60,
        )
        self.assertEqual(r.returncode, 0,
                         f"rc={r.returncode} stderr={r.stderr}")
        out = os.path.join(tempfile.gettempdir(),
                           "b3_binding_audit_report.json")
        self.assertTrue(os.path.exists(out),
                        f"audit did not persist {out}")
        with open(out, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Required keys
        for key in ("captured_at", "production_roots", "per_root",
                    "repo_wide", "binding_classification",
                    "binding_reason"):
            self.assertIn(key, data, f"missing key: {key}")
        # repo_wide required keys
        for key in ("any_merge_in_production", "any_caller_in_production",
                    "any_unwired_root", "repo_classification"):
            self.assertIn(key, data["repo_wide"],
                          f"repo_wide missing key: {key}")
        # per_root entries must each have classification
        for r in data["per_root"]:
            self.assertIn("classification", r)
            self.assertIn("production_caller_count", r)
            self.assertIn("merge_callable_present_in_production", r)
        # No classification may be a fabricated 'WIRED' without proof
        for r in data["per_root"]:
            if r["classification"] == "B3_PRODUCTION_BINDING = WIRED":
                self.assertTrue(
                    r["production_caller_count"] > 0
                    and r["merge_callable_present_in_production"],
                    f"WIRED without proof in {r['root']}",
                )


if __name__ == "__main__":
    unittest.main()
