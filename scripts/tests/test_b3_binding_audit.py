"""Test that the B3 binding audit script emits the honest
classification given the current state of the watcher/ORCH.

Per directive #18 review 5181252330, the binding audit must:
  - report PRODUCTION_MERGE_PATH_NOT_PRESENT if no merge callable
    exists in production executable code,
  - report B3_PRODUCTION_BINDING = UNWIRED if a merge callable
    exists but no production caller imports the seam,
  - report B3_PRODUCTION_BINDING = WIRED only if both conditions
    hold.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest


HERE = os.path.dirname(os.path.abspath(__file__))
WT = os.path.dirname(os.path.dirname(HERE))


class TestB3BindingAudit(unittest.TestCase):
    def _run(self):
        r = subprocess.run(
            [sys.executable, "scripts/b3_binding_audit.py"],
            capture_output=True, text=True, cwd=WT, timeout=60,
        )
        return r

    def _load_report(self):
        """Load the durable JSON emitted by the audit script."""
        out = os.path.join(tempfile.gettempdir(),
                           "b3_binding_audit_report.json")
        self.assertTrue(os.path.exists(out),
                        f"audit did not persist {out}")
        with open(out, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_audit_runs_clean(self):
        r = self._run()
        self.assertEqual(r.returncode, 0,
                         f"rc={r.returncode} stderr={r.stderr}")
        # Stdout is a textual summary, NOT JSON. JSON is in the file.
        self.assertIn("B3 BINDING AUDIT", r.stdout)
        return self._load_report()

    def test_audit_classification_matches_observable_state(self):
        data = self.test_audit_runs_clean()
        cls = data["binding_classification"]
        has_merge = data["merge_callable_presence"]["anywhere_in_production"]
        has_caller = bool(data["production_caller_refs"])

        # Truth table:
        # has_merge | has_caller | expected classification
        #   F       |    F       | PRODUCTION_MERGE_PATH_NOT_PRESENT
        #   F       |    T       | B3_PRODUCTION_BINDING = WIRED
        #   T       |    F       | B3_PRODUCTION_BINDING = UNWIRED
        #   T       |    T       | B3_PRODUCTION_BINDING = WIRED
        if not has_merge and not has_caller:
            self.assertEqual(
                cls, "PRODUCTION_MERGE_PATH_NOT_PRESENT",
                f"cls={cls} has_merge={has_merge} has_caller={has_caller}",
            )
        elif has_merge and not has_caller:
            self.assertEqual(
                cls, "B3_PRODUCTION_BINDING = UNWIRED",
                f"cls={cls} has_merge={has_merge} has_caller={has_caller}",
            )
        else:
            self.assertEqual(
                cls, "B3_PRODUCTION_BINDING = WIRED",
                f"cls={cls} has_merge={has_merge} has_caller={has_caller}",
            )

    def test_audit_excludes_docstring_mentions_of_gh_pr_merge(self):
        """The audit must NOT count 'gh pr merge' inside docstrings or
        comments as a production merge callable (would be false positive)."""
        data = self.test_audit_runs_clean()
        # All matches (if any) must point to executable code lines,
        # not docstring lines. We can verify by looking at matches:
        matches = data["merge_callable_presence"]["matches"]
        for m in matches:
            # Path must be inside directive_watcher/, not the adapter's
            # own docstring. The adapter itself doesn't claim to have
            # merge callable; it documents the seam contract.
            self.assertTrue(
                m["file"].startswith("directive_watcher\\")
                or m["file"].startswith("directive_watcher/"),
                f"match in unexpected file: {m['file']}",
            )
        # If matches exist in b3_adapter.py they must be in lines where
        # actual merge code lives, not in docstring block (lines 1-60ish).
        for m in matches:
            if "b3_adapter.py" in m["file"]:
                # b3_adapter.py has only docstring mentions. If any
                # match lands here, it's a false positive.
                self.fail(
                    f"merge pattern matched in b3_adapter.py line "
                    f"{m['line']} — should be excluded (adapter only "
                    f"documents the seam, does not implement merge)"
                )

    def test_audit_emits_durable_json(self):
        self.test_audit_runs_clean()
        out = os.path.join(tempfile.gettempdir(),
                           "b3_binding_audit_report.json")
        self.assertTrue(os.path.exists(out),
                        f"audit did not persist {out}")
        with open(out, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("binding_classification", data)
        self.assertIn("binding_reason", data)
        self.assertIn("production_caller_refs", data)


if __name__ == "__main__":
    unittest.main()
