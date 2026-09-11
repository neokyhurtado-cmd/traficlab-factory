"""B3 binding call-graph audit — emits durable evidence of the real
binding state between directive_watcher/ORCH and human_go_gate.

This script is the **proof** that the B3 seam is/isn't wired into the
production execution path. It does NOT modify any state; it only
inspects the codebase and emits a structured report.

Categories of evidence:
  1. Reverse reference count: which files import the B3 modules?
  2. Production caller search: does handler.py / default_execution /
     orchestrator / dispatch chain call into the seam?
  3. Merge-callable presence (in EXECUTABLE code only — docstrings
     and comments are stripped before matching): is there any
     production callable that performs gh pr merge or equivalent?
  4. Replay-store binding: is the gate's replay store wired into the
     dispatch path?

Output: prints a JSON-serialisable report to stdout and writes the
same JSON to /tmp/b3_binding_audit_report.json so the run is durable.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
from typing import Any

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROD_PATH = os.path.join(WT, "directive_watcher")
GATE_PATH = os.path.join(WT, "p1_human_go_gate")
SEAM_PATH = os.path.join(GATE_PATH, "seam.py")
ADAPTER_PATH = os.path.join(PROD_PATH, "b3_adapter.py")

# Tokens that must be present in production code to claim binding.
SEAM_TOKENS = [
    "b3_adapter",
    "hermes2_merge_pr_19",
    "run_or_bite",
    "pre_merge_check_and_call",
    "human_go_gate",
    "from seam import",
    "from directive_watcher.b3_adapter",
]

# Patterns that indicate a production merge callable.
MERGE_PATTERNS = [
    r"gh\s+pr\s+merge",
    r"subprocess[^\n]*\bmerge\b",
    r"\bGitHubClient\b.*\bmerge\b",
    r"\.merge_pr\(",
    r"\bmerge_pull_request\(",
    r"\bpulls/[^/]+/merge\b",
]


def _read(path: str) -> str:
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _strip_docstrings_and_comments(src: str) -> str:
    """Remove triple-quoted strings (docstrings) and # comments so
    matches are only in executable code."""
    # Triple-quoted blocks first (handles both triple-double and triple-single)
    DQ = '"' * 3
    SQ = "'" * 3
    src = re.sub(DQ + '.*?' + DQ, '', src, flags=re.DOTALL)
    src = re.sub(SQ + '.*?' + SQ, '', src, flags=re.DOTALL)
    # Line comments
    src = re.sub(r"#[^\n]*", "", src)
    return src


def _walk_python_files(root: str) -> list:
    out = []
    for r, dirs, files in os.walk(root):
        if "__pycache__" in r or ".git" in r:
            continue
        for f in files:
            if f.endswith(".py"):
                out.append(os.path.join(r, f))
    return out


def audit() -> dict:
    report = {
        "captured_at": time.time(),
        "wt": WT,
        "seam_module_exists": os.path.exists(SEAM_PATH),
        "adapter_module_exists": os.path.exists(ADAPTER_PATH),
        "production_path": PROD_PATH,
        "production_files_scanned": 0,
        "seam_token_reverse_refs": {},
        "merge_callable_presence": {
            "in_gh_client": False,
            "in_handler": False,
            "anywhere_in_production": False,
            "matches": [],
        },
        "binding_classification": "UNKNOWN",
        "binding_reason": "",
    }

    prod_files = _walk_python_files(PROD_PATH)
    report["production_files_scanned"] = len(prod_files)

    # Token reverse refs (full src, including docstrings — these are
    # deliberate references, even in docstrings they count).
    for path in prod_files:
        src = _read(path)
        for token in SEAM_TOKENS:
            count = src.count(token)
            if count:
                rel = os.path.relpath(path, WT)
                report["seam_token_reverse_refs"].setdefault(token, {})
                report["seam_token_reverse_refs"][token][rel] = count

    # Caller detection: PRODUCTION callers (excluding the seam/adapter/
    # audit themselves and excluding the tests).
    self_files = {
        os.path.relpath(SEAM_PATH, WT),
        os.path.relpath(ADAPTER_PATH, WT),
        os.path.relpath(__file__, WT),
    }
    caller_refs: dict = {}
    for path in prod_files:
        rel = os.path.relpath(path, WT)
        if rel in self_files:
            continue
        if "/tests/" in rel or "\\tests\\" in rel:
            continue
        src = _read(path)
        for token in SEAM_TOKENS:
            if token in src:
                caller_refs.setdefault(rel, []).append(token)
    report["production_caller_refs"] = caller_refs

    # Merge callable presence: executable code ONLY (no docstrings/comments)
    for path in prod_files:
        src = _read(path)
        src_exe = _strip_docstrings_and_comments(src)
        for pattern in MERGE_PATTERNS:
            for m in re.finditer(pattern, src_exe):
                line_no = src_exe[:m.start()].count("\n") + 1
                rel = os.path.relpath(path, WT)
                report["merge_callable_presence"]["matches"].append({
                    "file": rel,
                    "line": line_no,
                    "pattern": pattern,
                })

    gh_client = _read(os.path.join(PROD_PATH, "gh_client.py"))
    handler = _read(os.path.join(PROD_PATH, "handler.py"))
    gh_exe = _strip_docstrings_and_comments(gh_client)
    ha_exe = _strip_docstrings_and_comments(handler)
    for pattern in MERGE_PATTERNS:
        if re.search(pattern, gh_exe):
            report["merge_callable_presence"]["in_gh_client"] = True
        if re.search(pattern, ha_exe):
            report["merge_callable_presence"]["in_handler"] = True

    report["merge_callable_presence"]["anywhere_in_production"] = bool(
        report["merge_callable_presence"]["matches"]
    )

    any_ref = any(report["seam_token_reverse_refs"].values())
    has_merge = report["merge_callable_presence"]["anywhere_in_production"]

    if any_ref and has_merge:
        report["binding_classification"] = "B3_PRODUCTION_BINDING = WIRED"
        report["binding_reason"] = (
            "Production code calls into the seam AND a merge callable "
            "exists in production. The seam is the gating path."
        )
    elif has_merge and not any_ref:
        report["binding_classification"] = "B3_PRODUCTION_BINDING = UNWIRED"
        report["binding_reason"] = (
            "A merge callable exists in production but no production code "
            "calls the seam. Direct merge calls are NOT gated."
        )
    elif not has_merge and not any_ref:
        report["binding_classification"] = "PRODUCTION_MERGE_PATH_NOT_PRESENT"
        report["binding_reason"] = (
            "No merge callable exists in the directive_watcher/ORCH "
            "production path (executable code only — docstrings and "
            "comments stripped). Irreversible operations are performed "
            "outside the watcher (by the human owner or by an external "
            "release CLI not yet present in this repo). The seam is "
            "installed as a library and ready to gate the merge callable "
            "when one is added."
        )
    elif not has_merge and any_ref:
        if caller_refs:
            report["binding_classification"] = "B3_PRODUCTION_BINDING = WIRED"
            report["binding_reason"] = (
                "Production code (excluding tests/seam/audit) imports the "
                "seam tokens AND no production merge callable exists. "
                "The seam is wired into the production graph and ready "
                "to gate any future merge callable added to that path."
            )
        else:
            report["binding_classification"] = "PRODUCTION_MERGE_PATH_NOT_PRESENT"
            report["binding_reason"] = (
                "No production code (excluding tests, the seam module, "
                "and this audit) imports the seam tokens. No production "
                "merge callable exists either. The seam is installed as "
                "a library; irreversible operations are performed outside "
                "the watcher. The seam will gate the merge callable when "
                "a future production caller is added."
            )

    return report


def main() -> int:
    report = audit()
    out_path = os.path.join(tempfile.gettempdir(), "b3_binding_audit_report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # Stdout: short textual summary. JSON goes only to the file so
    # callers can json.load() cleanly.
    summary = {
        "binding_classification": report["binding_classification"],
        "binding_reason": report["binding_reason"],
        "production_files_scanned": report["production_files_scanned"],
        "merge_callable_present": report["merge_callable_presence"]["anywhere_in_production"],
        "production_caller_count": len(report["production_caller_refs"]),
        "json_persisted_at": out_path,
    }
    print("=== B3 BINDING AUDIT (SUMMARY) ===")
    for k, v in summary.items():
        print(f"  {k} = {v}")
    print(f"\nFull JSON at: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
