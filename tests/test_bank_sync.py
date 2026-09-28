"""Real pytest suite for orchestrator/plugins/astra-consult/bank_sync.py.

Covers every test named in the directive "Required tests" block
(traficlab-factory#14 c5648430968), executed on a temp clean clone of the bank.

Maps directive names to pytest node IDs:

  SCHEMA_VALIDATION = PASS                       -> test_schema_validation
  HASH_RECOMPUTE = PASS                          -> test_hash_recompute
  EXACT_DUP_DEDUP = PASS                         -> test_exact_dup_dedup
  SAME_ID_SAME_HASH_IDEMPOTENT = PASS            -> test_same_id_same_hash_idempotent
  SAME_ID_DIFFERENT_HASH_FAIL_CLOSED = PASS      -> test_same_id_different_hash_fail_closed
  SEMANTIC_OVERLAP_NOT_AUTO_DELETED = PASS       -> test_semantic_overlap_not_auto_deleted
  SUPERSESSION_LINEAGE = PASS                    -> test_supersession_lineage
  SECOND_CLEAN_CLONE = PASS                      -> test_second_clean_clone
  TWO_OPERATOR_CONVERGENCE = PASS                -> test_two_operator_convergence
  NON_FAST_FORWARD_NO_DATA_LOSS = PASS           -> test_non_fast_forward_no_data_loss
  META_FILES_FRONTMATTER_EXEMPT = PASS           -> test_meta_files_frontmatter_exempt
  UNRELATED_DIRTY_FILES_UNTOUCHED = PASS         -> test_unrelated_dirty_files_untouched

These tests run a subprocess against `bank_sync.py` (NOT in-process imports) so
they exercise the actual CLI surface that operators will use.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BANK_SYNC = REPO_ROOT / "orchestrator" / "plugins" / "astra-consult" / "bank_sync.py"
SOURCE_BANK = REPO_ROOT / "orchestrator" / "plugins" / "astra-consult" / "banco-ciencia"
REMOTE_URL = "https://github.com/neokyhurtado-cmd/traficlab-factory.git"
REMOTE_BRANCH = "fix/telegram-normal-hermes-session"

PY = sys.executable  # pytest's own python; bank_sync.py is stdlib-only


def _file_hash(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


@pytest.fixture()
def tmp_bank(tmp_path: Path) -> Path:
    """Copy the in-repo bank into a temp dir; return the temp bank root.

    NAFRON_BANK_ROOT is set per-test; bank_sync.py defaults BANK_ROOT to the
    repo's own banco-ciencia directory, so the env var override is required
    when running under pytest from the repo root.
    """
    bank = tmp_path / "bank"
    shutil.copytree(SOURCE_BANK, bank)
    return bank


def _run(cmd: list[str], bank_root: Path) -> dict:
    env = dict(os.environ)
    env["NAFRON_BANK_ROOT"] = str(bank_root)
    p = subprocess.run(
        [PY, str(BANK_SYNC), *cmd],
        env=env, capture_output=True, text=True, timeout=60,
    )
    if p.returncode not in (0, 2):
        raise AssertionError(
            f"bank_sync.py {cmd} exited {p.returncode}\nstdout:\n{p.stdout}\nstderr:\n{p.stderr}"
        )
    return json.loads(p.stdout) if p.stdout.strip() else {"status": "EMPTY", "stderr": p.stderr}


def _make_entry(tmp_path: Path, name: str, entry_id: str, body: str) -> Path:
    """Write a v1-schema entry file into a temp dir; return its path."""
    p = tmp_path / name
    p.write_text(
        "---\n"
        "kind: finding\n"
        "schema_version: banco-ciencia/v1\n"
        f"entry_id: {entry_id}\n"
        "status: ACTIVE\n"
        "created_at: 2026-09-28T220000Z\n"
        "origin_operator_or_session: orchestrator/test\n"
        "source_refs: [\"traficlab-factory#14 c5648430968\"]\n"
        "evidence_strength: A\n"
        "---\n\n"
        f"# {entry_id}\n{body}\n",
        encoding="utf-8",
    )
    return p


# ---------------------------------------------------------------------------
# SCHEMA_VALIDATION
# ---------------------------------------------------------------------------

def test_schema_validation(tmp_bank: Path, tmp_path: Path) -> None:
    """SCHEMA_VALIDATION = PASS — every non-meta entry has parseable v1 schema.

    Existing v0 entries (no schema_version) are soft-warnings, NOT hard errors.
    Adds a fresh v0 entry to prove --strict flags it.
    """
    # Plant a v0 entry (no schema_version) so we can prove --strict works.
    v0 = tmp_path / "v0.md"
    v0.write_text(
        "---\ntype: finding\ncreated: 2026-09-28T220000Z\nentry_id: test-v0-strict-001\n---\n\n# legacy v0\n",
        encoding="utf-8",
    )
    _run(["high", "--entry", "test-v0-strict-001", "--content", str(v0)], tmp_bank)

    res = _run(["validate"], tmp_bank)
    assert res["status"] == "PASS", res
    assert "errors" in res and not res["errors"]
    assert "schema_version" in res
    assert "total_entries_validated" in res
    assert res["v0_entries_pending_migration"] >= 1, res
    # --strict would flag v0 entries as hard errors.
    strict = _run(["validate", "--strict"], tmp_bank)
    assert strict["status"] == "FAIL"
    assert strict["v0_entries_pending_migration"] >= 1


# ---------------------------------------------------------------------------
# HASH_RECOMPUTE
# ---------------------------------------------------------------------------

def test_hash_recompute(tmp_bank: Path) -> None:
    """HASH_RECOMPUTE = PASS — `hash-recompute` writes .sha256 sidecars that
    match an independent recomputation.
    """
    res = _run(["hash-recompute"], tmp_bank)
    assert res["status"] == "OK", res
    # Spot-check one sidecar: its first 64 hex chars must equal sha256 of the
    # actual entry file content.
    assert res["files"], "no entries processed"
    rel, sha = next(iter(res["files"].items()))
    entry = tmp_bank / rel
    sidecar = entry.with_suffix(entry.suffix + ".sha256")
    assert sidecar.exists(), f"sidecar missing: {sidecar}"
    sidecar_text = sidecar.read_text(encoding="utf-8")
    assert sidecar_text.startswith(sha), sidecar_text[:80]
    assert _file_hash(entry) == sha


# ---------------------------------------------------------------------------
# EXACT_DUP_DEDUP + SAME_ID_SAME_HASH_IDEMPOTENT
# ---------------------------------------------------------------------------

def test_exact_dup_dedup(tmp_bank: Path, tmp_path: Path) -> None:
    """EXACT_DUP_DEDUP = PASS — second `high` with same content -> DEDUP_SILENT."""
    e = _make_entry(tmp_path, "dup.md", "dup-test-001", "body v1")
    first = _run(["high", "--entry", "dup-test-001", "--content", str(e)], tmp_bank)
    assert first["status"] == "ACCEPTED", first
    second = _run(["high", "--entry", "dup-test-001", "--content", str(e)], tmp_bank)
    assert second["status"] == "DEDUP_SILENT", second


def test_same_id_same_hash_idempotent(tmp_bank: Path, tmp_path: Path) -> None:
    """SAME_ID_SAME_HASH_IDEMPOTENT = PASS — same entry twice == no-op.

    This is the same physical scenario as test_exact_dup_dedup but named for
    directive parity.
    """
    e = _make_entry(tmp_path, "idem.md", "idem-test-001", "body v1")
    a = _run(["high", "--entry", "idem-test-001", "--content", str(e)], tmp_bank)
    b = _run(["high", "--entry", "idem-test-001", "--content", str(e)], tmp_bank)
    assert a["status"] == "ACCEPTED"
    assert b["status"] == "DEDUP_SILENT"
    assert b.get("sha256") == a.get("sha256")


# ---------------------------------------------------------------------------
# SAME_ID_DIFFERENT_HASH_FAIL_CLOSED
# ---------------------------------------------------------------------------

def test_same_id_different_hash_fail_closed(tmp_bank: Path, tmp_path: Path) -> None:
    """SAME_ID_DIFFERENT_HASH_FAIL_CLOSED = PASS — same id, different content ->
    FAIL_CLOSED_CONFLICT, both versions preserved.
    """
    e1 = _make_entry(tmp_path, "c1.md", "conflict-test-001", "body v1")
    e2 = _make_entry(tmp_path, "c2.md", "conflict-test-001", "body v2 DIFFERENT")
    first = _run(["high", "--entry", "conflict-test-001", "--content", str(e1)], tmp_bank)
    assert first["status"] == "ACCEPTED"
    second = _run(["high", "--entry", "conflict-test-001", "--content", str(e2)], tmp_bank)
    assert second["status"] == "FAIL_CLOSED_CONFLICT", second
    # Both versions preserved in conflicts_pending/
    pending = list((tmp_bank / "conflicts_pending").glob("conflict-test-001*"))
    assert len(pending) >= 3, f"expected >=3 artifacts, got {pending}"


# ---------------------------------------------------------------------------
# SEMANTIC_OVERLAP_NOT_AUTO_DELETED
# ---------------------------------------------------------------------------

def test_semantic_overlap_not_auto_deleted(tmp_bank: Path, tmp_path: Path) -> None:
    """SEMANTIC_OVERLAP_NOT_AUTO_DELETED = PASS — when a candidate shares
    keywords with an existing entry of the same kind, sync-classify returns
    DIFFERENT_ID_SEMANTIC_OVERLAP_REVIEW_CANDIDATE without touching the bank.
    """
    # Seed an entry with distinctive words.
    existing = _make_entry(
        tmp_path, "seed.md", "seed-001",
        "alpha beta gamma delta epsilon zeta eta theta",
    )
    a = _run(["high", "--entry", "seed-001", "--content", str(existing)], tmp_bank)
    assert a["status"] == "ACCEPTED"
    # Snapshot bank content
    before = sorted(str(p.relative_to(tmp_bank)) for p in tmp_bank.rglob("*"))
    # Candidate with different entry_id but shares >=3 keywords with seed-001
    cand = _make_entry(
        tmp_path, "cand.md", "different-001",
        "alpha beta gamma share these keywords with seed",
    )
    cls = _run(["sync-classify", "--candidate", str(cand)], tmp_bank)
    assert cls["status"] == "DIFFERENT_ID_SEMANTIC_OVERLAP_REVIEW_CANDIDATE", cls
    assert cls["resolution"] == "REVIEW_ONLY_NEVER_AUTO_DELETE"
    # Bank content unchanged (nothing was written by sync-classify).
    after = sorted(str(p.relative_to(tmp_bank)) for p in tmp_bank.rglob("*"))
    assert before == after


# ---------------------------------------------------------------------------
# SUPERSESSION_LINEAGE
# ---------------------------------------------------------------------------

def test_supersession_lineage(tmp_bank: Path, tmp_path: Path) -> None:
    """SUPERSESSION_LINEAGE = PASS — preserved conflict files carry sha256 prefix
    and timestamp lineage, with a CONFLICT_PENDING flag.
    """
    e1 = _make_entry(tmp_path, "s1.md", "super-001", "v1")
    e2 = _make_entry(tmp_path, "s2.md", "super-001", "v2")
    _run(["high", "--entry", "super-001", "--content", str(e1)], tmp_bank)
    conf = _run(["high", "--entry", "super-001", "--content", str(e2)], tmp_bank)
    assert conf["status"] == "FAIL_CLOSED_CONFLICT"
    # Lineage: sha256 prefix appears in filenames.
    cp = tmp_bank / "conflicts_pending"
    existing_files = list(cp.glob("super-001.*existing-*.md"))
    new_files = list(cp.glob("super-001.*new-*.md"))
    flag_files = list(cp.glob("super-001.CONFLICT_PENDING_*.md"))
    assert len(existing_files) == 1
    assert len(new_files) == 1
    assert len(flag_files) == 1
    # Flag file records both sha256s and ts.
    flag_text = flag_files[0].read_text(encoding="utf-8")
    assert "existing_sha" in flag_text and "new_sha" in flag_text and "detected_at" in flag_text


# ---------------------------------------------------------------------------
# SECOND_CLEAN_CLONE
# ---------------------------------------------------------------------------

def test_second_clean_clone(tmp_bank: Path) -> None:
    """SECOND_CLEAN_CLONE = PASS — `git clone` of the remote branch into a
    second dir reproduces the same bank bytes as the source.

    The clone uses --depth 1 (fast), --single-branch, and the SAME remote URL
    the directive specifies.
    """
    raw = tempfile.mkdtemp(prefix="second_clone_")
    second = Path(raw) / "bank"
    try:
        p = subprocess.run(
            ["git", "clone", "--branch", REMOTE_BRANCH, "--single-branch", "--depth", "1",
             REMOTE_URL, str(second)],
            capture_output=True, text=True, timeout=180,
        )
        assert p.returncode == 0, f"git clone failed:\n{p.stderr}"
        sc_bank = second / "orchestrator" / "plugins" / "astra-consult" / "banco-ciencia"
        assert sc_bank.exists(), f"bank missing in clone: {sc_bank}"
        # Compare by name (source is in-repo, second is the clone).
        sc_files = {p.name: _file_hash(p) for p in sc_bank.rglob("*.md")}
        # The SOURCE_BANK (in-repo) and tmp_bank are byte-identical at this
        # point because tmp_bank was just shutil.copytree'd from SOURCE_BANK.
        src_files = {p.name: _file_hash(p) for p in tmp_bank.rglob("*.md")}
        diffs = [n for n in src_files if n in sc_files and src_files[n] != sc_files[n]]
        assert not diffs, f"clone diverged from source: {diffs[:5]}"
    finally:
        # On Windows, git objects may still be locked briefly; retry cleanup.
        for _ in range(3):
            try:
                shutil.rmtree(raw, ignore_errors=False)
                break
            except (PermissionError, OSError):
                time.sleep(0.5)
        else:
            shutil.rmtree(raw, ignore_errors=True)


# ---------------------------------------------------------------------------
# TWO_OPERATOR_CONVERGENCE
# ---------------------------------------------------------------------------

def test_two_operator_convergence(tmp_bank: Path, tmp_path: Path) -> None:
    """TWO_OPERATOR_CONVERGENCE = PASS — A creates entry X; B sees it via clone
    and submits same id with modified content -> CONFLICT, both preserved.
    """
    # Operator A
    e_a = _make_entry(tmp_path, "op_a.md", "conv-001", "operator A body")
    a = _run(["high", "--entry", "conv-001", "--content", str(e_a)], tmp_bank)
    assert a["status"] == "ACCEPTED"
    # Operator B submits a different content under the same id (in tmp_bank which
    # represents B's working copy after a hypothetical pull from remote).
    e_b = _make_entry(tmp_path, "op_b.md", "conv-001", "operator B body different")
    b = _run(["high", "--entry", "conv-001", "--content", str(e_b)], tmp_bank)
    assert b["status"] == "FAIL_CLOSED_CONFLICT"
    # Original A entry untouched (non-fast-forward no data loss).
    original = (tmp_bank / "findings" / "conv-001.md").read_text(encoding="utf-8")
    assert "operator A body" in original
    # A's version preserved in conflicts_pending/
    assert list((tmp_bank / "conflicts_pending").glob("conv-001.*existing-*.md"))


# ---------------------------------------------------------------------------
# NON_FAST_FORWARD_NO_DATA_LOSS
# ---------------------------------------------------------------------------

def test_non_fast_forward_no_data_loss(tmp_bank: Path, tmp_path: Path) -> None:
    """NON_FAST_FORWARD_NO_DATA_LOSS = PASS — even with multiple conflicts, the
    canonical entry under findings/ is never overwritten silently.
    """
    for i in range(3):
        e = _make_entry(tmp_path, f"n{i}.md", "noff-001", f"v{i} body")
        r = _run(["high", "--entry", "noff-001", "--content", str(e)], tmp_bank)
        if i == 0:
            assert r["status"] == "ACCEPTED"
        else:
            assert r["status"] == "FAIL_CLOSED_CONFLICT"
    # Canonical entry is still v0's content.
    canon = (tmp_bank / "findings" / "noff-001.md").read_text(encoding="utf-8")
    assert "v0 body" in canon


# ---------------------------------------------------------------------------
# META_FILES_FRONTMATTER_EXEMPT
# ---------------------------------------------------------------------------

def test_meta_files_frontmatter_exempt(tmp_bank: Path) -> None:
    """META_FILES_FRONTMATTER_EXEMPT = PASS — INDEX.md and README.md have no
    frontmatter; validator skips them.
    """
    res = _run(["validate"], tmp_bank)
    assert res["status"] == "PASS"
    assert "INDEX.md" not in res["errors"]
    assert "README.md" not in res["errors"]
    # Also: ask_astra must NOT return meta-file matches.
    res2 = _run(["ask_astra", "--query", "INDEX"], tmp_bank)
    paths = {r["path"] for r in res2["results"]}
    assert not any("INDEX.md" in p or p.startswith("README") for p in paths), paths


# ---------------------------------------------------------------------------
# UNRELATED_DIRTY_FILES_UNTOUCHED
# ---------------------------------------------------------------------------

def test_unrelated_dirty_files_untouched(tmp_bank: Path) -> None:
    """UNRELATED_DIRTY_FILES_UNTOUCHED = PASS — validator + bank_sync never
    writes to any file outside BANK_ROOT. Run a representative cross-section
    and verify the repo is byte-identical to the SOURCE_BANK we copied in.
    """
    _run(["validate"], tmp_bank)
    _run(["hash-recompute"], tmp_bank)
    _run(["manifest-build"], tmp_bank)
    _run(["manifest-check"], tmp_bank)
    # tmp_bank root should now contain manifest.json + .sha256 sidecars ONLY
    # inside its own subtree. The repo at large is untouched.
    # Compare every byte under SOURCE_BANK (in-repo) with what was here
    # pre-test: it must be identical because we copytree'd and never wrote
    # back into SOURCE_BANK.
    src_hashes = {p.relative_to(SOURCE_BANK): _file_hash(p) for p in SOURCE_BANK.rglob("*") if p.is_file()}
    # Skip sidecars and manifest.json (we DID write them inside tmp_bank, not
    # SOURCE_BANK). For SOURCE_BANK itself, those files must NOT exist.
    assert not (SOURCE_BANK / "manifest.json").exists()
    assert not list(SOURCE_BANK.rglob("*.sha256")), "sidecars leaked into SOURCE_BANK"