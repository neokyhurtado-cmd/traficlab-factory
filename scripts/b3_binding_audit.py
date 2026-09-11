"""B3 binding call-graph audit — emits durable evidence of the real
binding state between watcher/ORCH and human_go_gate.

This script is the **proof** that the B3 seam is/isn't wired into the
production execution path. It does NOT modify any state; it only
inspects the codebase and emits a structured report.

Scope policy (v2 — Astra review 5181335515):
  - The script scans ALL explicitly sanctioned production roots.
    By default: directive_watcher/ and orchestrator/.
  - Each root is reported independently (per-root classification).
  - A repo-wide rollup is computed as the OR of all roots:
      * any_merge_in_any_root  -> merge-callable-present-at-repo-level
      * any_caller_in_any_root -> seam-called-from-production
  - WIRED / UNWIRED decisions are based on `caller_refs` ONLY,
    never on `seam_token_reverse_refs` (which includes the adapter
    itself and would otherwise produce false WIRED).

Categories of evidence:
  1. Reverse reference count (audit-only — for transparency)
  2. Production caller count (excluding tests/seam/adapter/audit)
  3. Merge-callable presence in executable code (docstrings stripped)
  4. Per-root + repo-wide classification with explicit reasoning

Output:
  - Stdout: short textual summary
  - File:   /tmp/b3_binding_audit_report.json (durable, CI-consumable)
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
GATE_PATH = os.path.join(WT, "p1_human_go_gate")
SEAM_PATH = os.path.join(GATE_PATH, "seam.py")
ADAPTER_PATH = os.path.join(WT, "directive_watcher", "b3_adapter.py")
AUDIT_PATH = os.path.abspath(__file__)

# v2: list of production roots to scan. Each is a directory containing
# runtime code that could plausibly execute a merge.
DEFAULT_PRODUCTION_ROOTS = [
    os.path.join(WT, "directive_watcher"),
    os.path.join(WT, "orchestrator"),
]

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
    r"\bgit\s+merge\b",
]


def _read(path: str) -> str:
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _strip_docstrings_and_comments(src: str) -> str:
    """Remove triple-quoted strings (docstrings) and # comments so
    matches are only in executable code."""
    DQ = "\"" * 3
    SQ = "'" * 3
    src = re.sub(DQ + ".*?" + DQ, "", src, flags=re.DOTALL)
    src = re.sub(SQ + ".*?" + SQ, "", src, flags=re.DOTALL)
    src = re.sub(r"#[^\n]*", "", src)
    return src


def _walk_python_files(root: str) -> list:
    out = []
    if not os.path.isdir(root):
        return out
    for r, dirs, files in os.walk(root):
        if "__pycache__" in r or ".git" in r:
            continue
        for f in files:
            if f.endswith(".py"):
                out.append(os.path.join(r, f))
    return out


def _is_test_path(rel: str) -> bool:
    """A path is a test if it's under any tests/ directory or its
    filename starts with test_ or ends with _test.py."""
    rel_lower = rel.lower().replace("\\", "/")
    if "/tests/" in rel_lower:
        return True
    fname = os.path.basename(rel_lower)
    if fname.startswith("test_") or fname.endswith("_test.py"):
        return True
    return False


def _scan_root(root: str, self_files: set) -> dict:
    """Scan one production root. Returns per-root evidence."""
    files = _walk_python_files(root)
    # The root may be outside the WT (e.g. adversarial tests build a
    # fake repo on a different drive). Use the basename as the root
    # label when relpath would cross mounts.
    try:
        rel_root = os.path.relpath(root, WT)
    except ValueError:
        rel_root = os.path.basename(root.rstrip("\\/")) or root

    # Same fallback for per-file relpath (used in caller_refs + token_refs keys)
    def _rel_path(p):
        try:
            return os.path.relpath(p, WT)
        except ValueError:
            return p

    token_refs: dict = {}     # all references including self (audit)
    caller_refs: dict = {}    # production callers only (binding decision)
    merge_matches: list = []

    for path in files:
        rel = _rel_path(path)
        src = _read(path)
        src_exe = _strip_docstrings_and_comments(src)

        # Token reverse refs (full src) — for transparency
        for token in SEAM_TOKENS:
            count = src.count(token)
            if count:
                token_refs.setdefault(token, {})
                token_refs[token][rel] = count

        # Merge-callable presence in executable code
        for pattern in MERGE_PATTERNS:
            for m in re.finditer(pattern, src_exe):
                line_no = src_exe[:m.start()].count("\n") + 1
                merge_matches.append({
                    "file": rel,
                    "line": line_no,
                    "pattern": pattern,
                    "is_test": _is_test_path(rel),
                })

        # Production callers: exclude self files + tests
        if rel in self_files:
            continue
        if _is_test_path(rel):
            continue
        for token in SEAM_TOKENS:
            if token in src_exe:
                caller_refs.setdefault(rel, []).append(token)

    production_merge_matches = [m for m in merge_matches if not m["is_test"]]
    return {
        "root": rel_root,
        "files_scanned": len(files),
        "seam_token_reverse_refs": token_refs,
        "production_caller_refs": caller_refs,
        "merge_callable_matches_all": merge_matches,
        "merge_callable_matches_production": production_merge_matches,
        "merge_callable_present_in_production": bool(production_merge_matches),
        "production_caller_count": len(caller_refs),
    }


def _classify_root(scan: dict) -> dict:
    """Classify a single root scan. WIRED/UNWIRED/PATH_NOT_PRESENT
    is decided on production_caller_refs + merge_callable_matches_production,
    NEVER on seam_token_reverse_refs."""
    has_merge = scan["merge_callable_present_in_production"]
    has_caller = bool(scan["production_caller_refs"])

    if has_merge and has_caller:
        return {
            "classification": "B3_PRODUCTION_BINDING = WIRED",
            "reason": (
                "Production code (excluding tests/seam/audit) imports the "
                "seam tokens AND a merge callable exists in production "
                "executable code. The seam is the gating path."
            ),
        }
    elif has_merge and not has_caller:
        return {
            "classification": "B3_PRODUCTION_BINDING = UNWIRED",
            "reason": (
                "A merge callable exists in production executable code "
                "but no production caller (excluding tests/seam/audit) "
                "imports the seam tokens. Direct merge calls are NOT "
                "gated — the seam is installed but unwired."
            ),
        }
    elif not has_merge and has_caller:
        return {
            "classification": "B3_PRODUCTION_BINDING = WIRED_LIB_ONLY",
            "reason": (
                "Production code imports the seam tokens but no merge "
                "callable exists in production. The seam is wired into "
                "the dispatch path but has nothing irreversible to gate "
                "yet."
            ),
        }
    else:
        return {
            "classification": "PRODUCTION_MERGE_PATH_NOT_PRESENT",
            "reason": (
                "Neither a production merge callable nor a production "
                "seam caller exists in this root. Irreversible "
                "operations, if any, are performed outside this code."
            ),
        }


def _rollup(per_root: list) -> dict:
    """Repo-wide rollup of per-root classifications."""
    any_merge = any(r["merge_callable_present_in_production"] for r in per_root)
    any_caller = any(bool(r["production_caller_refs"]) for r in per_root)
    any_unwired = any(
        _classify_root(r)["classification"] == "B3_PRODUCTION_BINDING = UNWIRED"
        for r in per_root
    )

    if any_merge and any_caller and not any_unwired:
        cls = "B3_PRODUCTION_BINDING = WIRED (repo-wide)"
    elif any_unwired:
        cls = "B3_PRODUCTION_BINDING = UNWIRED (repo-wide; at least one root unwired)"
    elif any_merge and not any_caller:
        cls = "B3_PRODUCTION_BINDING = UNWIRED (repo-wide; merge callable exists, no caller)"
    elif not any_merge and any_caller:
        cls = "B3_PRODUCTION_BINDING = WIRED_LIB_ONLY (repo-wide)"
    else:
        cls = "PRODUCTION_MERGE_PATH_NOT_PRESENT (repo-wide)"

    return {
        "any_merge_in_production": any_merge,
        "any_caller_in_production": any_caller,
        "any_unwired_root": any_unwired,
        "repo_classification": cls,
    }



def _rel_root_or_basename(r):
    try:
        return os.path.relpath(r, WT)
    except ValueError:
        return os.path.basename(r.rstrip("\\/")) or r


def audit(production_roots: list = None) -> dict:
    roots = production_roots or DEFAULT_PRODUCTION_ROOTS

    # self-files excluded from caller detection. Use try/except to
    # handle adversarial tests where paths may cross drives.
    def _rel(p):
        try:
            return os.path.relpath(p, WT)
        except ValueError:
            return None
    self_files = {
        _rel(SEAM_PATH),
        _rel(ADAPTER_PATH),
        _rel(AUDIT_PATH),
    }
    # Drop None entries (paths that crossed mounts)
    self_files.discard(None)

    per_root = [_scan_root(r, self_files) for r in roots]
    for r in per_root:
        cls = _classify_root(r)
        r["classification"] = cls["classification"]
        r["classification_reason"] = cls["reason"]

    rollup = _rollup(per_root)

    return {
        "captured_at": time.time(),
        "wt": WT,
        "seam_module_exists": os.path.exists(SEAM_PATH),
        "adapter_module_exists": os.path.exists(ADAPTER_PATH),
        "production_roots": [_rel_root_or_basename(r) for r in roots],
        "per_root": per_root,
        "repo_wide": rollup,
        "binding_classification": rollup["repo_classification"],
        "binding_reason": _explain_rollup(per_root, rollup),
    }


def _explain_rollup(per_root: list, rollup: dict) -> str:
    parts = [f"Repo classification: {rollup['repo_classification']}."]
    parts.append(
        f"any_merge_in_production={rollup['any_merge_in_production']}, "
        f"any_caller_in_production={rollup['any_caller_in_production']}."
    )
    parts.append("Per-root:")
    for r in per_root:
        parts.append(
            f"  - {r['root']}/: {r['classification']} "
            f"(production_caller_count={r['production_caller_count']}, "
            f"merge_in_production={r['merge_callable_present_in_production']})"
        )
    return " ".join(parts)


def main() -> int:
    report = audit()
    out_path = os.path.join(tempfile.gettempdir(),
                            "b3_binding_audit_report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    summary = {
        "binding_classification": report["binding_classification"],
        "repo_classification": report["repo_wide"]["repo_classification"],
        "production_roots": report["production_roots"],
        "any_merge_in_production": report["repo_wide"]["any_merge_in_production"],
        "any_caller_in_production": report["repo_wide"]["any_caller_in_production"],
        "per_root_summary": [
            {
                "root": r["root"],
                "classification": r["classification"],
                "production_caller_count": r["production_caller_count"],
                "merge_in_production": r["merge_callable_present_in_production"],
            }
            for r in report["per_root"]
        ],
        "json_persisted_at": out_path,
    }
    print("=== B3 BINDING AUDIT (v2 SUMMARY) ===")
    for k, v in summary.items():
        print(f"  {k} = {v}")
    print(f"\nFull JSON at: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
