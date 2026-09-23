#!/usr/bin/env python3
"""G0 audit harness for Skill Fabric V1 (issue #51).

For each of the 10 upstream candidate repositories, this harness prints:

    REPO                 = owner/repo
    UPSTREAM_SHA         = exact 40-char hex from refs/heads/main
    DEFAULT_BRANCH       = main | master | <other>
    ARCHIVED             = YES | NO
    LICENSE              = SPDX id from GitHub API (UNRESOLVED if absent)
    DESCRIPTION          = repo description
    INSTALL_HOOKS        = inferred from README presence (heuristic, NOT proof)
    EVAL_OUTCOME         = CANDIDATE | BLOCKED (initial; subject to G1-G5)

USAGE:
    python scripts/g0_audit.py > evidence/skill-fabric-v1/g0-audit/g0_initial.json

The harness is READ-ONLY (only `gh api` calls). It does NOT clone,
vendor, or install anything. It does NOT mutate any local file.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict


CANDIDATES = [
    "obra/superpowers",
    "DietrichGebert/ponytail",
    "Graphify-Labs/graphify",
    "JuliusBrussee/caveman",
    "Egonex-AI/Understand-Anything",
    "mvanhorn/last30days-skill",
    "ayghri/i-have-adhd",
    "sickn33/agentic-awesome-skills",
    "K-Dense-AI/scientific-agent-skills",
    "cathrynlavery/diagram-design",
]


def gh(*args: str) -> Dict[str, Any]:
    proc = subprocess.run(
        ["gh", "api", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return {"_error": proc.stderr.strip()[:500], "_stdout": proc.stdout.strip()[:500]}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"_error": "non-json response", "_stdout": proc.stdout[:500]}


def audit_repo(slug: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {"REPO": slug}
    repo = gh(f"repos/{slug}")
    if "_error" in repo:
        out["EVAL_OUTCOME"] = "BLOCKED"
        out["REASON"] = "gh api repos/<slug> failed: " + repo["_error"][:200]
        return out

    out["UPSTREAM_SHA"] = repo.get("default_branch", "")
    out["DEFAULT_BRANCH"] = repo.get("default_branch", "")
    out["ARCHIVED"] = bool(repo.get("archived", False))
    out["DESCRIPTION"] = (repo.get("description") or "").strip()

    # Resolve exact HEAD SHA on default branch.
    branch = gh(f"repos/{slug}/branches/{out['DEFAULT_BRANCH']}")
    if "_error" not in branch:
        commit = branch.get("commit", {})
        sha = commit.get("sha", "")
        out["UPSTREAM_SHA"] = sha
    else:
        out["EVAL_OUTCOME"] = "BLOCKED"
        out["REASON"] = "could not resolve default branch SHA: " + branch["_error"][:200]
        return out

    # License resolution.
    lic = repo.get("license")
    if lic and lic.get("spdx_id"):
        out["LICENSE"] = lic["spdx_id"]
    else:
        out["LICENSE"] = "UNRESOLVED"

    # Heuristic install-hook indicator (README presence only).
    readme = gh(f"repos/{slug}/readme")
    if "_error" in readme:
        out["INSTALL_HOOKS"] = "no readme resolved"
    else:
        out["INSTALL_HOOKS"] = "readme present (manual review required for hooks)"

    # Initial intake gate outcome (heuristic; G1 validator refines).
    if out["ARCHIVED"]:
        out["EVAL_OUTCOME"] = "BLOCKED"
        out["REASON"] = "repo is archived"
    elif out["LICENSE"] in ("UNRESOLVED", "NOASSERTION", None):
        out["EVAL_OUTCOME"] = "BLOCKED"
        out["REASON"] = "no SPDX license"
    else:
        out["EVAL_OUTCOME"] = "CANDIDATE_PENDING_G1"
    return out


def main() -> int:
    results = []
    for slug in CANDIDATES:
        results.append(audit_repo(slug))
    payload = {
        "directive": "skill-fabric-v1-implant-20260922-01",
        "issue": "neokyhurtado-cmd/traficlab-factory#51",
        "candidate_count": len(CANDIDATES),
        "results": results,
        "note": (
            "Heuristic G0 evidence only. A skill cannot leave CANDIDATE_PENDING_G1 "
            "state until the G1 intake validator (registry.validate_entry) accepts "
            "a manually-authored entry with full provenance, scope, and capability "
            "declaration."
        ),
    }
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
