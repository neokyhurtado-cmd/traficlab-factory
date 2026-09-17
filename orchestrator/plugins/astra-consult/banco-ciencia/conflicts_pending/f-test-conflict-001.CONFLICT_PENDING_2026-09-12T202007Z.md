# CONFLICT FAIL-CLOSED
entry_id: f-test-conflict-001
existing_sha: 102b35660e3434b6cfc8dfd86fc969099f4fe54e1ce0b524dd7035554bb7d36a
new_sha: 6c23effadf84f554ff449d0260ebe67484ce04943b36bdf89c86c69d9006d2b1
detected_at: 2026-09-12T202007Z

## Action
Both versions preserved.
Resolve manually:
  - python bank_sync.py reconcile --entry f-test-conflict-001 --winner=existing|new
  - or merge outside, then `reconcile` keeps the original sha on record.
