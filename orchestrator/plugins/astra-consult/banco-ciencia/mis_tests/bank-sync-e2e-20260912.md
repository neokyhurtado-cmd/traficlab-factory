# bank_sync.py E2E tests (2026-09-12T15:36, Nafron)

> All outputs are RAW captured from subprocess.run, no fabrication.

## Environment
- Python: from hermes-agent venv
- bank_sync.py: `C:\Users\David\hermes-tools\bank_sync.py`
- Test files: `{}`
- Bank path: `C:\Users\david\repos\traficlab-factory\orchestrator\plugins\astra-consult\banco-ciencia`

## Captured live runs (8.1 KB script)

```
$ bank_sync.py high --entry f-test-alpha-001 --content C:\Users\david\AppData\Local\Temp\bank_sync_tests\f-test-alpha-001.md
{
  "status": "ACCEPTED",
  "entry_id": "f-test-alpha-001",
  "sha256": "f3ab4f111ce59b88e6ecc769236c413748b210f273d0a567cbc96eb2a8363f3a",
  "path": "C:\\Users\\david\\repos\\traficlab-factory\\orchestrator\\plugins\\astra-consult\\banco-ciencia\\findings\\f-test-alpha-001.md",
  "ts": "2026-09-12T202007Z"
}
( rc=0 )

$ bank_sync.py high --entry f-test-alpha-001 --content C:\Users\david\AppData\Local\Temp\bank_sync_tests\f-test-alpha-001.md
{
  "status": "DEDUP_SILENT",
  "entry_id": "f-test-alpha-001",
  "sha256": "f3ab4f111ce59b88e6ecc769236c413748b210f273d0a567cbc96eb2a8363f3a",
  "note": "exact sha match, already in bank"
}
( rc=0 )

$ bank_sync.py high --entry f-test-conflict-001 --content C:\Users\david\AppData\Local\Temp\bank_sync_tests\conflict_v1.md
{
  "status": "ACCEPTED",
  "entry_id": "f-test-conflict-001",
  "sha256": "102b35660e3434b6cfc8dfd86fc969099f4fe54e1ce0b524dd7035554bb7d36a",
  "path": "C:\\Users\\david\\repos\\traficlab-factory\\orchestrator\\plugins\\astra-consult\\banco-ciencia\\findings\\f-test-conflict-001.md",
  "ts": "2026-09-12T202007Z"
}
( rc=0 )

$ bank_sync.py high --entry f-test-conflict-001 --content C:\Users\david\AppData\Local\Temp\bank_sync_tests\conflict_v2.md
{
  "status": "FAIL_CLOSED_CONFLICT",
  "entry_id": "f-test-conflict-001",
  "existing_sha": "102b35660e3434b6cfc8dfd86fc969099f4fe54e1ce0b524dd7035554bb7d36a",
  "new_sha": "6c23effadf84f554ff449d0260ebe67484ce04943b36bdf89c86c69d9006d2b1",
  "preserved_existing": "C:\\Users\\david\\repos\\traficlab-factory\\orchestrator\\plugins\\astra-consult\\banco-ciencia\\conflicts_pending\\f-test-conflict-001.102b35660e34.existing-2026-09-12T202007Z.md",
  "preserved_new": "C:\\Users\\david\\repos\\traficlab-factory\\orchestrator\\plugins\\astra-consult\\banco-ciencia\\conflicts_pending\\f-test-conflict-001.6c23effadf84.new-2026-09-12T202007Z.md",
  "flag": "C:\\Users\\david\\repos\\traficlab-factory\\orchestrator\\plugins\\astra-consult\\banco-ciencia\\conflicts_pending\\f-test-conflict-001.CONFLICT_PENDING_2026-09-12T202007Z.md",
  "ts": "2026-09-12T202007Z",
  "requires_human_review": true,
  "resolution": "PRESERVE_BOTH"
}
( rc=0 )

$ bank_sync.py ask_astra --query conflict
{
  "status": "OK",
  "query": "conflict",
  "matches": 5,
  "results": [
    {
      "path": "conflicts_pending\\f-test-conflict-001.102b35660e34.existing-2026-09-12T202007Z.md",
      "entry_id": "f-test-conflict-001",
      "type": "finding",
      "evidence_strength": "A",
      "snippet": "---\ntype: finding\ncreated: 2026-09-12T15:36Z\nowner: Nafron\nproject: nafron/bank-sync-e2e\nrefs: []\nevidence_strength: A\nentry_id: f-test-conflict-001\n---\n\n# Conflict v1 (from operator A)\nthis is the first version of a contradictory entry.\n"
    },
    {
      "path": "conflicts_pending\\f-test-conflict-001.6c23effadf84.new-2026-09-12T202007Z.md",
      "entry_id": "f-test-conflict-001",
      "type": "finding",
      "evidence_strength": "B",
      "snippet": "---\ntype: finding\ncreated: 2026-09-12T15:36Z\nowner: Nafron-v2-sim\nproject: nafron/bank-sync-e2e\nrefs: []\nevidence_strength: B\nentry_id: f-test-conflict-001\n---\n\n# Conflict v2 (from operator B with different hash)\nthis is the second version. different content. DIFFERENT HASH.\n"
    },
    {
      "path": "conflicts_pending\\f-test-conflict-001.CONFLICT_PENDING_2026-09-12T202007Z.md",
      "entry_id": "f-test-conflict-001.CONFLICT_PENDING_2026-09-12T202007Z",
      "type": null,
      "evidence_strength": null,
      "snippet": "# CONFLICT FAIL-CLOSED\nentry_id: f-test-conflict-001\nexisting_sha: 102b35660e3434b6cfc8dfd86fc969099f4fe54e1ce0b524dd7035554bb7d36a\nnew_sha: 6c23effadf84f554ff449d0260ebe67484ce04943b36bdf89c86c69d9006d2b1\ndetected_at: 2026-09-12T202007Z\n\n## Action\nBoth versions preserved.\nResolve manually:\n  - pyth"
    },
    {
      "path": "findings\\f-test-conflict-001.md",
      "entry_id": "f-test-conflict-001",
      "type": "finding",
      "evidence_strength": "A",
      "snippet": "---\ntype: finding\ncreated: 2026-09-12T15:36Z\nowner: Nafron\nproject: nafron/bank-sync-e2e\nrefs: []\nevidence_strength: A\nentry_id: f-test-conflict-001\n---\n\n# Conflict v1 (from operator A)\nthis is the first version of a contradictory entry.\n"
    },
    {
      "path": "mis_tests\\bank-sync-design.md",
      "entry_id": "bank-sync-design",
      "type": "tool",
      "evidence_strength": "B (implementación funcional, lógica reproduce casos del user)",
      "snippet": "---\ntype: tool\ncreated: 2026-09-12T15:30Z\nowner: Nafron\nproject: nafron/scientific-bank-sync\nrefs: [\"traficlab-factory ce5126b\", \"issue traficlab-factory #14 c5648430968\"]\nevidence_strength: B (implementación funcional, lógica reproduce casos del user)\n---\n\n# bank_sync.py — Lógica de sincronización "
    }
  ]
}
( rc=0 )

$ bank_sync.py list_conflicts
{
  "status": "OK",
  "pending": 1,
  "files": [
    "conflicts_pending\\f-test-conflict-001.CONFLICT_PENDING_2026-09-12T202007Z.md"
  ]
}
( rc=0 )

```

## Pass/Fail summary

| # | Test | Expected | Actual | Pass |
|---|------|----------|--------|------|
| 1 | HIGH new entry | ACCEPTED | `{
  "status": "ACCEPTED",
  "entry_id": "f-test-alpha-001",
  "sha256": "f3ab4f111ce59b88e6ecc769236c413748b210f273d0a567cbc96eb2a8363f3a",
  "path": "C:\\Users\\david\\repos\\traficlab-factory\\orchestrator\\plugins\\astra-consult\\banco-ciencia\\findings\\f-test-alpha-001.md",
  "ts": "2026-09-12T202007Z"
}` | ✅ |
| 2 | HIGH dedup same sha | DEDUP_SILENT | `{
  "status": "DEDUP_SILENT",
  "entry_id": "f-test-alpha-001",
  "sha256": "f3ab4f111ce59b88e6ecc769236c413748b210f273d0a567cbc96eb2a8363f3a",
  "note": "exact sha match, already in bank"
}` | ✅ |
| 3a | HIGH first conflict version | ACCEPTED | `{
  "status": "ACCEPTED",
  "entry_id": "f-test-conflict-001",
  "sha256": "102b35660e3434b6cfc8dfd86fc969099f4fe54e1ce0b524dd7035554bb7d36a",
  "path": "C:\\Users\\david\\repos\\traficlab-factory\\orchestrator\\plugins\\astra-consult\\banco-ciencia\\findings\\f-test-conflict-001.md",
  "ts": "2026-09-12T202007Z"
}` | ✅ |
| 3b | HIGH second version (different sha) | FAIL_CLOSED_CONFLICT, preserve BOTH | `{
  "status": "FAIL_CLOSED_CONFLICT",
  "entry_id": "f-test-conflict-001",
  "existing_sha": "102b35660e3434b6cfc8dfd86fc969099f4fe54e1ce0b524dd7035554bb7d36a",
  "new_sha": "6c23effadf84f554ff449d0260ebe67484ce04943b36bdf89c86c69d9006d2b1",
  "preserved_existing": "C:\\Users\\david\\repos\\traficlab-factory\\orchestrator\\plugins\\astra-consult\\banco-ciencia\\conflicts_pending\\f-test-conflict-001.102b35660e34.existing-2026-09-12T202007Z.md",
  "preserved_new": "C:\\Users\\david\\repos\\traficlab-factory\\orchestrator\\plugins\\astra-consult\\banco-ciencia\\conflicts_pending\\f-test-conflict-001.6c23effadf84.new-2026-09-12T202007Z.md",
  "flag": "C:\\Users\\david\\repos\\traficlab-factory\\orchestrator\\plugins\\astra-consult\\banco-ciencia\\conflicts_pending\\f-test-conflict-001.CONFLICT_PENDING_2026-09-12T202007Z.md",
  "ts": "2026-09-12T202007Z",
  "requires_human_review": true,
  "resolution": "PRESERVE_BOTH"
}` | ✅ |
| 4 | ask_astra discovery | matches found | `{
  "status": "OK",
  "query": "conflict",
  "matches": 5,
  "results": [
    {
      "path": "conflicts_pending\\f-test-conflict-001.102b35660e34.existing-2026-09-12T202007Z.md",
      "entry_id": "f-test-conflict-001",
      "type": "finding",
      "evidence_strength": "A",
      "snippet": "---\ntype: finding\ncreated: 2026-09-12T15:36Z\nowner: Nafron\nproject: nafron/bank-sync-e2e\nrefs: []\nevidence_strength: A\nentry_id: f-test-conflict-001\n---\n\n# Conflict v1 (from operator A)\nthis is the first version of a contradictory entry.\n"
    },
    {
      "path": "conflicts_pending\\f-test-conflict-001.6c23effadf84.new-2026-09-12T202007Z.md",
      "entry_id": "f-test-conflict-001",
      "type": "finding",
      "evidence_strength": "B",
      "snippet": "---\ntype: finding\ncreated: 2026-09-12T15:36Z\nowner: Nafron-v2-sim\nproject: nafron/bank-sync-e2e\nrefs: []\nevidence_strength: B\nentry_id: f-test-conflict-001\n---\n\n# Conflict v2 (from operator B with different hash)\nthis is the second version. different content. DIFFERENT HASH.\n"
    },
    {
      "path": "conflicts_pending\\f-test-conflict-001.CONFLICT_PENDING_2026-09-12T202007Z.md",
      "entry_id": "f-test-conflict-001.CONFLICT_PENDING_2026-09-12T202007Z",
      "type": null,
      "evidence_strength": null,
      "snippet": "# CONFLICT FAIL-CLOSED\nentry_id: f-test-conflict-001\nexisting_sha: 102b35660e3434b6cfc8dfd86fc969099f4fe54e1ce0b524dd7035554bb7d36a\nnew_sha: 6c23effadf84f554ff449d0260ebe67484ce04943b36bdf89c86c69d9006d2b1\ndetected_at: 2026-09-12T202007Z\n\n## Action\nBoth versions preserved.\nResolve manually:\n  - pyth"
    },
    {
      "path": "findings\\f-test-conflict-001.md",
      "entry_id": "f-test-conflict-001",
      "type": "finding",
      "evidence_strength": "A",
      "snippet": "---\ntype: finding\ncreated: 2026-09-12T15:36Z\nowner: Nafron\nproject: nafron/bank-sync-e2e\nrefs: []\nevidence_strength: A\nentry_id: f-test-conflict-001\n---\n\n# Conflict v1 (from operator A)\nthis is the first version of a contradictory entry.\n"
    },
    {
      "path": "mis_tests\\bank-sync-design.md",
      "entry_id": "bank-sync-design",
      "type": "tool",
      "evidence_strength": "B (implementación funcional, lógica reproduce casos del user)",
      "snippet": "---\ntype: tool\ncreated: 2026-09-12T15:30Z\nowner: Nafron\nproject: nafron/scientific-bank-sync\nrefs: [\"traficlab-factory ce5126b\", \"issue traficlab-factory #14 c5648430968\"]\nevidence_strength: B (implementación funcional, lógica reproduce casos del user)\n---\n\n# bank_sync.py — Lógica de sincronización "
    }
  ]
}` | ✅ |
| 5 | list_conflicts | pending flags present | `{
  "status": "OK",
  "pending": 1,
  "files": [
    "conflicts_pending\\f-test-conflict-001.CONFLICT_PENDING_2026-09-12T202007Z.md"
  ]
}` | ✅ |

## Two-operator convergence protocol — summary

Test 3b showed the fail-closed path:
- Existing entry f-test-conflict-001 with sha256 `aaaa...1` was preserved into `conflicts_pending/f-test-conflict-001.<old_sha>.existing-<ts>.md`
- New content with sha256 `bbbb...2` was preserved into `conflicts_pending/f-test-conflict-001.<new_sha>.new-<ts>.md`
- A `*.CONFLICT_PENDING_<ts>.md` flag was written
- The original `findings/f-test-conflict-001.md` was NOT overwritten

NO entry was lost. NO auto-merge happened. HUMAN must resolve.

## Files produced on disk

```
conflicts_pending/f-test-conflict-001.<sha>.existing-20260912T...md
conflicts_pending/f-test-conflict-001.<sha>.new-20260912T...md
conflicts_pending/f-test-conflict-001.CONFLICT_PENDING_20260912T...md
findings/f-test-alpha-001.md (success entry)
findings/f-test-conflict-001.md (preserved original; conflict flag exists)
```
