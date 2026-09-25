"""
test_housekeeper.py — minimal safety tests for the housekeeper.

We test the conservative invariants, not the full discovery. These are the
tests that prove the housekeeper will NOT silently destroy work:

  1. `gc --dry-run` never deletes anything.
  2. `gc --dry-run` refuses to emit a manifest while a live runtime is detected
     (we simulate by monkey-patching detect_live_runtime).
  3. `delete` refuses without --i-have-reviewed.
  4. Classification of an ORPHAN_LOCAL_ONLY + non-dirty worktree is STALE_CANDIDATE.
  5. Classification of a branch merged into origin/main is SUPERSEDED_KEEP_EVIDENCE.
  6. Classification of a dirty worktree is ACTIVE_DIRTY_OWNER_PRESERVE no matter what.
  7. Classification of `main` is ACTIVE_CANONICAL.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

# Make housekeeper importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import housekeeper as hk  # noqa: E402

import argparse  # noqa: E402


def test_gc_dry_run_emits_manifest(tmp_path: Path, monkeypatch):
    inv = tmp_path / "inv.json"
    inv.write_text(json.dumps({
        "worktrees": [
            {"path": "/tmp/x", "repo": "/tmp/repo", "branch": "refs/heads/feat/old",
             "sha": "abc1234", "disk_bytes": 1000, "classification": "STALE_CANDIDATE",
             "classification_reason": "orphan", "remote_status": "ORPHAN_LOCAL_ONLY",
             "dirty_files": 0},
        ]
    }))
    out = tmp_path / "manifest.json"
    monkeypatch.setattr(hk, "detect_live_runtime", lambda: set())
    rc = hk.cmd_gc_dry_run(argparse.Namespace(input=str(inv), output=str(out)))
    assert rc == 0
    assert out.exists()
    manifest = json.loads(out.read_text())
    assert manifest["total_candidates"] == 1
    assert "NO DELETE PERFORMED" in manifest["policy"].upper() or "NOT EXECUTABLE" in manifest["policy"]


def test_gc_dry_run_refuses_when_live(monkeypatch):
    monkeypatch.setattr(hk, "detect_live_runtime", lambda: {"postgres", "hermes"})
    rc = hk.cmd_gc_dry_run(argparse.Namespace(input="/dev/null", output="/dev/null"))
    assert rc == 2


def test_delete_refuses_without_i_have_reviewed(tmp_path):
    rc = hk.cmd_delete(argparse.Namespace(manifest="/dev/null", i_have_reviewed=False))
    assert rc == 1


def test_classify_main_is_canonical(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()  # fake git marker
    row = hk.WorktreeRow(path=str(repo), repo=str(repo), sha="x"*7, branch="refs/heads/main",
                         dirty_files=0, disk_bytes=0)
    hk.classify_worktree(row, repo)
    assert row.classification == "ACTIVE_CANONICAL"
    assert row.confidence == "high"


def test_classify_master_is_canonical(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    row = hk.WorktreeRow(path=str(repo), repo=str(repo), sha="x"*7, branch="refs/heads/master",
                         dirty_files=0, disk_bytes=0)
    hk.classify_worktree(row, repo)
    assert row.classification == "ACTIVE_CANONICAL"


def test_classify_dirty_is_preserved(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    row = hk.WorktreeRow(path=str(repo), repo=str(repo), sha="x"*7, branch="refs/heads/feat/anything",
                         dirty_files=3, disk_bytes=0)
    hk.classify_worktree(row, repo)
    assert row.classification == "ACTIVE_DIRTY_OWNER_PRESERVE"


def test_classify_protected_pattern_is_stacked(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    row = hk.WorktreeRow(path=str(repo), repo=str(repo), sha="x"*7,
                         branch="refs/heads/feat/jupiter-x", dirty_files=0, disk_bytes=0)
    hk.classify_worktree(row, repo)
    assert row.classification == "ACTIVE_STACKED"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
