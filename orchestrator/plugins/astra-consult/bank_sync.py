#!/usr/bin/env python3
"""
bank_sync.py — Sync minimal-viable for the Nafron scientific bank.

Per David directive 2026-09-12 (traficlab-factory issue #14 c5648430968):
- HIGH entry: append-only (write to bank, never delete)
- DEDUP exact: same sha256 silent dedup
- CONFLICT fail-closed: same entry_id + different sha256 -> preserve BOTH + flag for human review, NO auto-merge
- RECONCILE: human-only command
- ASK_ASTRA: discover & read-only query

Append-only. Never delete. No race-condition shortcuts. Pure-Python stdlib only.
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

BANK_ROOT = Path(os.environ.get("NAFRON_BANK_ROOT", "C:/Users/david/repos/traficlab-factory/orchestrator/plugins/astra-consult/banco-ciencia"))


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
    for sub in ["findings", "decisions", "contradictions", "papers", "prompts"]:
        candidate = BANK_ROOT / sub / f"{entry_id}.md"
        if candidate.exists():
            return candidate, sha256_of(candidate)
    return None, None


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
    h.add_argument("--type", default="findings", choices=["findings","decisions","contradictions","papers","prompts","mis_tests","playbook"])

    d = sub.add_parser("dedup", help="check dedup status of an entry_id")
    d.add_argument("--entry", required=True)

    r = sub.add_parser("reconcile", help="HUMAN-only conflict reconcile")
    r.add_argument("--entry", required=True)
    r.add_argument("--winner", choices=["existing","new"], required=True)
    r.add_argument("--content", type=Path)

    a = sub.add_parser("ask_astra", help="discovery interface")
    a.add_argument("--query", required=True)

    sub.add_parser("list_conflicts", help="list pending conflicts")

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
    else:
        ap.error("unknown cmd")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
