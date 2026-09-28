#!/usr/bin/env python3
"""
bank_sync.py — Sync minimal-viable for the Nafron scientific bank.

Per David directive 2026-09-12 (traficlab-factory issue #14 c5648430968):
- HIGH entry: append-only (write to bank, never delete)
- DEDUP exact: same sha256 silent dedup
- CONFLICT fail-closed: same entry_id + different sha256 -> preserve BOTH + flag for human review, NO auto-merge
- RECONCILE: human-only command
- ASK_ASTRA: discover & read-only query
- VALIDATE: check every non-meta entry has parseable frontmatter + required v1 fields
- HASH-RECOMPUTE: write per-entry .sha256 sidecar files
- MANIFEST-BUILD: emit manifest.json with sha256 of every entry
- MANIFEST-CHECK: read manifest.json, recompute, fail on mismatch
- SYNC-CLASSIFY: classify a candidate as NEW / EXACT_DUPLICATE / SAME_ID_SAME_HASH /
                 SAME_ID_DIFFERENT_HASH (CONFLICT) / DIFFERENT_ID_SEMANTIC_OVERLAP
                 (REVIEW_CANDIDATE) — read-only, never mutates

Append-only. Never delete. No race-condition shortcuts. Pure-Python stdlib only.

Bank v1 schema (frozen in directive):
- Required frontmatter fields: kind (alias: type), entry_id, schema_version, status
  (kind ∈ finding|decision|contradiction|playbook|test|other; status ∈
  ACTIVE|SUPERSEDED|REJECTED).
- Optional frontmatter fields: created_at (alias: created), updated_at,
  origin_operator_or_session (alias: owner), source_refs (alias: refs),
  content_sha256 (recomputed by tool), supersedes[].
- META files (INDEX.md, README.md) and conflicts_pending/* and mis_tests/*
  are exempt from the schema validator.
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

def _default_bank_root() -> Path:
    """Default to the repo's own bank directory (sibling of this script)."""
    return Path(__file__).resolve().parent / "banco-ciencia"


BANK_ROOT = Path(os.environ.get("NAFRON_BANK_ROOT", str(_default_bank_root())))


# Subdirectories that hold real scientific entries (subject to schema validation).
ENTRY_SUBDIRS = ["findings", "decisions", "contradictions", "papers", "prompts", "playbook"]

# Subdirectories that are exempt from schema validation (test artifacts,
# conflict markers, index meta).
EXEMPT_PATH_PREFIXES = ("conflicts_pending/", "mis_tests/")
EXEMPT_META_FILES = {"INDEX.md", "README.md"}

# v1 schema constants.
VALID_KINDS = {"finding", "decision", "contradiction", "playbook", "test", "other"}
VALID_STATUSES = {"ACTIVE", "SUPERSEDED", "REJECTED"}
SCHEMA_VERSION = "banco-ciencia/v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")


def sha256_of(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def parse_frontmatter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    fm = {}
    for line in parts[1].strip().split("\n"):
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        fm[k.strip()] = v.strip()
    return fm


def existing_entry_sha(entry_id: str) -> tuple[Path | None, str | None]:
    """Find an existing entry by ID, return (path, sha256)."""
    for sub in ENTRY_SUBDIRS:
        candidate = BANK_ROOT / sub / f"{entry_id}.md"
        if candidate.exists():
            return candidate, sha256_of(candidate)
    return None, None


def _posix(rel_path: str) -> str:
    """Normalize path separators to forward slash (Windows Path.relative_to
    returns backslash-separated strings on Windows)."""
    return rel_path.replace("\\", "/")


def is_meta_file(rel_path: str) -> bool:
    """A path under BANK_ROOT is a meta/test artifact, exempt from schema validation."""
    rel = _posix(rel_path)
    name = rel.rsplit("/", 1)[-1]
    if name in EXEMPT_META_FILES:
        return True
    for prefix in EXEMPT_PATH_PREFIXES:
        if rel.startswith(prefix):
            return True
    return False


def normalize_field(fm: dict, canonical: str, *aliases: str) -> str | None:
    """Get a frontmatter field by canonical name, falling back to aliases (v0 -> v1 compat)."""
    v = fm.get(canonical)
    if v is not None and v != "":
        return v.strip() if isinstance(v, str) else str(v).strip()
    for alias in aliases:
        v = fm.get(alias)
        if v is not None and v != "":
            return v.strip() if isinstance(v, str) else str(v).strip()
    return None


def validate_entry(rel_path: str, fm: dict, body: str) -> tuple[list[str], list[str]]:
    """Return (hard_errors, soft_warnings) for one entry file.

    Hard errors block acceptance. Soft warnings flag migration needs but
    grandfather pre-existing v0 entries (those without schema_version).
    """
    hard: list[str] = []
    soft: list[str] = []
    if is_meta_file(rel_path):
        return hard, soft

    kind = normalize_field(fm, "kind", "type")
    entry_id = normalize_field(fm, "entry_id")
    schema_version = normalize_field(fm, "schema_version")
    status = normalize_field(fm, "status")

    if not kind:
        soft.append("missing kind (alias: type); v0 grandfathered")
    elif kind not in VALID_KINDS:
        hard.append(f"invalid kind: {kind!r} (must be one of {sorted(VALID_KINDS)})")

    if not entry_id:
        # entry_id is the only field every entry MUST have to be discoverable
        # by `ask_astra` and `existing_entry_sha`. Missing entry_id is hard.
        hard.append("missing required field: entry_id")
    else:
        posix_rel = _posix(rel_path)
        expected_id = posix_rel.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        if entry_id != expected_id:
            hard.append(
                f"entry_id {entry_id!r} does not match filename {expected_id!r}"
            )

    if not schema_version:
        # v0 entries pre-date the schema_version field. Soft warning only.
        soft.append("missing schema_version (v0 grandfathered; add banco-ciencia/v1 to migrate)")
    elif schema_version != SCHEMA_VERSION:
        hard.append(
            f"unsupported schema_version: {schema_version!r} (expected {SCHEMA_VERSION!r})"
        )

    if not status:
        soft.append("missing status; v0 grandfathered (add ACTIVE|SUPERSEDED|REJECTED)")
    elif status not in VALID_STATUSES:
        hard.append(f"invalid status: {status!r} (must be one of {sorted(VALID_STATUSES)})")

    return hard, soft


def cmd_validate() -> dict:
    """Walk every non-meta entry; report per-entry errors; exit 1 if any hard error."""
    total = 0
    errors_by_file: dict[str, list[str]] = {}
    warnings_by_file: dict[str, list[str]] = {}
    v0_count = 0
    for p in sorted(BANK_ROOT.rglob("*.md")):
        rel = str(p.relative_to(BANK_ROOT))
        if is_meta_file(rel):
            continue
        total += 1
        text = p.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(text)
        hard, soft = validate_entry(rel, fm, text)
        if hard:
            errors_by_file[rel] = hard
        if soft:
            warnings_by_file[rel] = soft
        if any("schema_version" in w for w in soft):
            v0_count += 1
    return {
        "status": "PASS" if not errors_by_file else "FAIL",
        "total_entries_validated": total,
        "v0_entries_pending_migration": v0_count,
        "errors": errors_by_file,
        "warnings": warnings_by_file,
        "schema_version": SCHEMA_VERSION,
    }


def cmd_hash_recompute(subdir: str = "") -> dict:
    """Write a .sha256 sidecar file next to each entry, holding its content sha256.

    Returns a dict of {rel_path: sha256} for every entry processed.
    """
    out: dict[str, str] = {}
    targets = [BANK_ROOT / subdir] if subdir else [BANK_ROOT]
    for root in targets:
        if not root.exists():
            return {"status": "ERROR", "reason": f"subdir not found: {subdir}", "files": {}}
        for p in sorted(root.rglob("*.md")):
            rel = str(p.relative_to(BANK_ROOT))
            if is_meta_file(rel):
                continue
            sha = sha256_of(p)
            sidecar = p.with_suffix(p.suffix + ".sha256")
            sidecar.write_text(sha + "  " + p.name + "\n", encoding="utf-8")
            out[rel] = sha
    return {
        "status": "OK",
        "files": out,
        "schema_version": SCHEMA_VERSION,
    }


def cmd_manifest_build(out_path: Path | None = None) -> dict:
    """Write manifest.json with sha256 of every entry (excluding meta/test artifacts)."""
    if out_path is None:
        out_path = BANK_ROOT / "manifest.json"
    entries: dict[str, str] = {}
    for p in sorted(BANK_ROOT.rglob("*.md")):
        rel = str(p.relative_to(BANK_ROOT))
        if is_meta_file(rel):
            continue
        entries[rel] = sha256_of(p)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "bank_root": str(BANK_ROOT),
        "entry_count": len(entries),
        "entries": entries,
    }
    out_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "status": "OK",
        "manifest_path": str(out_path),
        "entry_count": len(entries),
    }


def cmd_manifest_check(manifest_path: Path) -> dict:
    """Read an existing manifest.json, recompute sha256 for each entry, fail on mismatch."""
    if not manifest_path.exists():
        return {"status": "ERROR", "reason": f"manifest not found: {manifest_path}"}
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    diffs: list[dict[str, str]] = []
    missing: list[str] = []
    for rel, expected in sorted(m.get("entries", {}).items()):
        p = BANK_ROOT / rel
        if not p.exists():
            missing.append(rel)
            continue
        actual = sha256_of(p)
        if actual != expected:
            diffs.append({"path": rel, "expected": expected, "actual": actual})
    # Also catch files in the bank that aren't in the manifest (drift).
    in_bank = {
        str(p.relative_to(BANK_ROOT))
        for p in BANK_ROOT.rglob("*.md")
        if not is_meta_file(str(p.relative_to(BANK_ROOT)))
    }
    not_in_manifest = sorted(in_bank - set(m.get("entries", {})))
    return {
        "status": "PASS" if not diffs and not missing and not not_in_manifest else "FAIL",
        "diff_count": len(diffs),
        "missing_count": len(missing),
        "drift_count": len(not_in_manifest),
        "diffs": diffs,
        "missing": missing,
        "drift": not_in_manifest,
    }


def cmd_sync_classify(candidate_path: Path) -> dict:
    """Read-only classification of a candidate entry file. Never mutates the bank.

    Returns one of:
      NEW                            — entry_id does not exist yet
      EXACT_DUPLICATE                — entry_id exists, sha256 matches
      SAME_ID_SAME_HASH_IDEMPOTENT   — alias for EXACT_DUPLICATE (kept for directive parity)
      SAME_ID_DIFFERENT_HASH_CONFLICT — entry_id exists with different sha256
      DIFFERENT_ID_SEMANTIC_OVERLAP_REVIEW_CANDIDATE
                                    — candidate has a different entry_id but shares
                                      ≥3 head/body keywords with an existing entry
                                      of the same kind. Read-only; never deletes.
    """
    if not candidate_path.exists():
        return {"status": "ERROR", "reason": f"candidate not found: {candidate_path}"}
    text = candidate_path.read_text(encoding="utf-8", errors="replace")
    fm = parse_frontmatter(text)
    entry_id = normalize_field(fm, "entry_id")
    if not entry_id:
        return {
            "status": "ERROR",
            "reason": "candidate lacks parseable entry_id frontmatter; cannot classify",
        }
    new_sha = sha256_of(candidate_path)

    existing_path, existing_sha = existing_entry_sha(entry_id)
    if existing_path is None:
        result = {
            "status": "NEW",
            "entry_id": entry_id,
            "candidate_sha256": new_sha,
        }
    elif existing_sha == new_sha:
        result = {
            "status": "EXACT_DUPLICATE",
            "substatus": "SAME_ID_SAME_HASH_IDEMPOTENT",
            "entry_id": entry_id,
            "sha256": new_sha,
            "existing_path": str(existing_path),
        }
    else:
        result = {
            "status": "SAME_ID_DIFFERENT_HASH_CONFLICT",
            "entry_id": entry_id,
            "existing_sha256": existing_sha,
            "candidate_sha256": new_sha,
            "existing_path": str(existing_path),
            "resolution": "FAIL_CLOSED_PRESERVE_BOTH",
        }

    # Semantic overlap check (read-only, only when status is NEW).
    if result["status"] == "NEW":
        candidate_kind = normalize_field(fm, "kind", "type") or "other"
        candidate_body = text.lower()
        stop = {"the", "and", "for", "with", "from", "this", "that", "are", "was", "not"}
        cand_words = {
            w.strip(".,:;()[]{}!?'\"")
            for w in candidate_body.split()
            if len(w) > 4 and w not in stop
        }
        best: dict | None = None
        for sub in ENTRY_SUBDIRS:
            for p in sorted((BANK_ROOT / sub).glob("*.md")):
                rel = str(p.relative_to(BANK_ROOT))
                # Skip self by name (candidate may live outside BANK_ROOT, so
                # relative_to would raise).
                if p.name == candidate_path.name and sha256_of(p) == new_sha:
                    continue
                efm = parse_frontmatter(p.read_text(encoding="utf-8", errors="replace"))
                if normalize_field(efm, "entry_id") == entry_id:
                    continue
                ekind = normalize_field(efm, "kind", "type") or "other"
                if ekind != candidate_kind:
                    continue
                ewords = {
                    w.strip(".,:;()[]{}!?'\"")
                    for w in p.read_text(encoding="utf-8", errors="replace").lower().split()
                    if len(w) > 4 and w not in stop
                }
                overlap = cand_words & ewords
                if len(overlap) >= 3:
                    score = len(overlap)
                    if best is None or score > best["overlap_count"]:
                        best = {
                            "path": rel,
                            "kind": ekind,
                            "overlap_count": score,
                            "overlap_sample": sorted(overlap)[:10],
                        }
        if best:
            result["status"] = "DIFFERENT_ID_SEMANTIC_OVERLAP_REVIEW_CANDIDATE"
            result["semantic_overlap"] = best
            result["resolution"] = "REVIEW_ONLY_NEVER_AUTO_DELETE"

    return result


def cmd_high(entry_id: str, content_path: Path, entry_type: str = "findings") -> dict:
    """HIGH entry: dedup if exact match, fail-closed if conflict with same entry_id."""
    new_sha = sha256_of(content_path)
    new_text = content_path.read_text(encoding="utf-8")
    if not parse_frontmatter(new_text):
        return {
            "status": "REJECTED",
            "reason": "missing or invalid YAML frontmatter",
            "entry_id": entry_id,
        }

    existing_path, existing_sha = existing_entry_sha(entry_id)

    if existing_sha is None:
        # No conflict; just append
        target = BANK_ROOT / entry_type / f"{entry_id}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(new_text, encoding="utf-8")
        return {
            "status": "ACCEPTED",
            "entry_id": entry_id,
            "sha256": new_sha,
            "path": str(target),
            "ts": utc_now(),
        }

    if existing_sha == new_sha:
        return {
            "status": "DEDUP_SILENT",
            "entry_id": entry_id,
            "sha256": new_sha,
            "note": "exact sha match, already in bank",
        }

    # Conflict: same entry_id, different content. Fail-closed.
    conflict_dir = BANK_ROOT / "conflicts_pending"
    conflict_dir.mkdir(parents=True, exist_ok=True)
    ts = utc_now()
    preserved_existing = conflict_dir / f"{entry_id}.{existing_sha[:12]}.existing-{ts}.md"
    preserved_new = conflict_dir / f"{entry_id}.{new_sha[:12]}.new-{ts}.md"
    preserved_existing.write_bytes(existing_path.read_bytes())
    preserved_new.write_bytes(content_path.read_bytes())
    flag = conflict_dir / f"{entry_id}.CONFLICT_PENDING_{ts}.md"
    flag.write_text(
        f"# CONFLICT FAIL-CLOSED\n"
        f"entry_id: {entry_id}\n"
        f"existing_sha: {existing_sha}\n"
        f"new_sha: {new_sha}\n"
        f"detected_at: {ts}\n"
        f"\n## Action\n"
        f"Both versions preserved.\n"
        f"Resolve manually:\n"
        f"  - python bank_sync.py reconcile --entry {entry_id} --winner=existing|new\n"
        f"  - or merge outside, then `reconcile` keeps the original sha on record.\n",
        encoding="utf-8",
    )
    return {
        "status": "FAIL_CLOSED_CONFLICT",
        "entry_id": entry_id,
        "existing_sha": existing_sha,
        "new_sha": new_sha,
        "preserved_existing": str(preserved_existing),
        "preserved_new": str(preserved_new),
        "flag": str(flag),
        "ts": ts,
        "requires_human_review": True,
        "resolution": "PRESERVE_BOTH",
    }


def cmd_dedup(entry_id: str) -> dict:
    """Check dedup status of an entry_id without adding new content."""
    p, sha = existing_entry_sha(entry_id)
    if sha is None:
        return {"status": "NOT_FOUND", "entry_id": entry_id}
    return {
        "status": "FOUND",
        "entry_id": entry_id,
        "sha256": sha,
        "path": str(p) if p else None,
    }


def cmd_reconcile(entry_id: str, winner: str, content_path: Path | None = None) -> dict:
    """Resolve a fail-closed conflict. HUMAN-ONLY command; never auto-invoked."""
    p, sha = existing_entry_sha(entry_id)
    if sha is None:
        return {"status": "NOT_FOUND", "entry_id": entry_id}
    return {
        "status": "RECONCILED_REQUIRES_MANUAL_GIT_OPS",
        "entry_id": entry_id,
        "current_sha": sha,
        "winner": winner,
        "note": "real reconcile needs git mv + commit; tool only flags intent; HUMAN must run git",
    }


def cmd_ask_astra(query: str) -> dict:
    """Discovery interface for Astra/Jupiter/other operators."""
    results = []
    for p in BANK_ROOT.rglob("*.md"):
        if "INDEX" in p.name or p.name.startswith("README"):
            continue
        txt = p.read_text(encoding="utf-8", errors="replace")
        if query.lower() in txt.lower():
            fm = parse_frontmatter(txt)
            results.append({
                "path": str(p.relative_to(BANK_ROOT)),
                "entry_id": fm.get("entry_id") or p.stem,
                "type": fm.get("type"),
                "evidence_strength": fm.get("evidence_strength"),
                "snippet": txt[:300],
            })
    return {"status": "OK", "query": query, "matches": len(results), "results": results}


def cmd_list_conflicts() -> dict:
    """List pending conflicts for human review."""
    conflicts_dir = BANK_ROOT / "conflicts_pending"
    if not conflicts_dir.exists():
        return {"status": "OK", "pending": 0}
    flags = sorted(conflicts_dir.glob("*.CONFLICT_PENDING_*.md"))
    items = [str(p.relative_to(BANK_ROOT)) for p in flags]
    return {"status": "OK", "pending": len(items), "files": items}


def main() -> int:
    ap = argparse.ArgumentParser(description="Nafron scientific bank sync (append-only, fail-closed)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    h = sub.add_parser("high", help="add or update entry; dedup/fail-closed")
    h.add_argument("--entry", required=True)
    h.add_argument("--content", required=True, type=Path)
    h.add_argument("--type", default="findings", choices=ENTRY_SUBDIRS + ["mis_tests"])

    d = sub.add_parser("dedup", help="check dedup status of an entry_id")
    d.add_argument("--entry", required=True)

    r = sub.add_parser("reconcile", help="HUMAN-only conflict reconcile")
    r.add_argument("--entry", required=True)
    r.add_argument("--winner", choices=["existing", "new"], required=True)
    r.add_argument("--content", type=Path)

    a = sub.add_parser("ask_astra", help="discovery interface")
    a.add_argument("--query", required=True)

    sub.add_parser("list_conflicts", help="list pending conflicts for human review")

    v = sub.add_parser("validate", help="validate every non-meta entry against v1 schema")
    v.add_argument("--strict", action="store_true",
                   help="treat v0 entries (missing schema_version) as HARD errors")

    hr = sub.add_parser("hash-recompute", help="write .sha256 sidecars for entries")
    hr.add_argument("--subdir", default="", help="restrict to one subdir under BANK_ROOT")

    mb = sub.add_parser("manifest-build", help="write manifest.json with per-entry sha256")
    mb.add_argument("--out", type=Path, default=None,
                    help="manifest output path (default: <BANK_ROOT>/manifest.json)")

    mc = sub.add_parser("manifest-check", help="verify manifest.json against current bank")
    mc.add_argument("--manifest", type=Path, default=None,
                    help="manifest path (default: <BANK_ROOT>/manifest.json)")

    sc = sub.add_parser("sync-classify", help="read-only classify a candidate entry file")
    sc.add_argument("--candidate", required=True, type=Path)

    args = ap.parse_args()
    if args.cmd == "high":
        result = cmd_high(args.entry, args.content, args.type)
    elif args.cmd == "dedup":
        result = cmd_dedup(args.entry)
    elif args.cmd == "reconcile":
        result = cmd_reconcile(args.entry, args.winner, args.content)
    elif args.cmd == "ask_astra":
        result = cmd_ask_astra(args.query)
    elif args.cmd == "list_conflicts":
        result = cmd_list_conflicts()
    elif args.cmd == "validate":
            result = cmd_validate()
            if args.strict and result.get("v0_entries_pending_migration", 0) > 0:
                # Under --strict, v0 entries become HARD errors.
                v0_paths: list[str] = []
                for p in sorted(BANK_ROOT.rglob("*.md")):
                    rel = str(p.relative_to(BANK_ROOT))
                    if is_meta_file(rel):
                        continue
                    fm = parse_frontmatter(p.read_text(encoding="utf-8", errors="replace"))
                    if not normalize_field(fm, "schema_version"):
                        v0_paths.append(rel)
                if v0_paths:
                    errors = result.setdefault("errors", {})
                    for vp in v0_paths:
                        errors.setdefault(vp, []).append("missing schema_version (--strict)")
                    result["status"] = "FAIL"
    elif args.cmd == "hash-recompute":
        result = cmd_hash_recompute(args.subdir)
    elif args.cmd == "manifest-build":
        result = cmd_manifest_build(args.out)
    elif args.cmd == "manifest-check":
        manifest_path = args.manifest or (BANK_ROOT / "manifest.json")
        result = cmd_manifest_check(manifest_path)
    elif args.cmd == "sync-classify":
        result = cmd_sync_classify(args.candidate)
    else:
        ap.error("unknown cmd")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    # Non-zero exit when any command signals FAIL.
    if isinstance(result, dict) and result.get("status") == "FAIL":
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
