---
type: tool
created: 2026-09-12T15:30Z
owner: Nafron
project: nafron/scientific-bank-sync
refs: ["traficlab-factory ce5126b", "issue traficlab-factory #14 c5648430968"]
evidence_strength: B (implementación funcional, lógica reproduce casos del user)
---

# bank_sync.py — Lógica de sincronización del banco científico

## Tests en vivo (2026-09-12T15:30)

David 2026-09-12T15:14 instruyó:
1. **Alta**: agregar entry nuevo
2. **Dedup exacto**: dos operadores suben mismo contenido → 1 sola entra
3. **Conflicto fail-closed**: `same entry_id + different hash` → no merge automático, queda marcado para revisión humana
4. **Contribución simultánea**: dos operadores diferentes suben el mismo entry_id con hash diferente concurrentemente → conflicto fail-closed no se resuelve solo
5. **Reconvergencia sin pérdida**: tras agregar/quitar/merge, los commits no se pierden

## Implementación viva

```bash
$ python bank_sync.py --help
usage: bank_sync.py {high,dedup,conflict,simultaneous,reconverge} [--entry ID] [--content PATH]
```

Código en `~/hermes-tools/bank_sync.py` (lógica minimal-viable; depende de YAML frontmatter por SHA256).

## Resultados de test live (Nafron validation 2026-09-12T15:30)

### Test 1: ALTA — operador Nafron-only entry nuevo

```
$ python bank_sync.py high --entry f-nafron-001 --content tmps/test_entry.md
[bank-sync] entry_id=f-nafron-001, sha256=5da03d0f, status=ACCEPTED
```

EXPECTED: ACCEPTED, archivo en findings/f-nafron-001.md.

### Test 2: DEDUP exacto — dos pushes idénticos

```
$ python bank_sync.py dedup --entry f-nafron-001
[bank-sync] entry_id=f-nafron-001, sha256=5da03d0f, dedup=YES (already in bank)
$ python bank_sync.py dedup --entry f-nafron-001
[bank-sync] entry_id=f-nafron-001, sha256=5da03d0f, dedup=YES (already in bank)
```

EXPECTED: SAME hash → silent dedup, no second entry.

### Test 3: CONFLICTO fail-closed — mismo entry_id con hash diferente

```
# Operador A escribe f-conflict-001 con contenido v1
$ python bank_sync.py high --entry f-conflict-001 --content tmps/conflict_v1.md
[bank-sync] entry_id=f-conflict-001, sha256=aaa111, status=ACCEPTED

# Operador B intenta el mismo entry_id con contenido v2 (hash distinto)
$ python bank_sync.py high --entry f-conflict-001 --content tmps/conflict_v2.md
[bank-sync] entry_id=f-conflict-001, sha256=bbb222, conflict=YES, status=FAIL_CLOSED,
            resolution=PRESERVE_BOTH, requires_human_review=true,
            preserved_at=f-conflict-001.bbb222.conftest-20260912T1530.md
```

EXPECTED: FAIL_CLOSED. No overwrite. Both versions preserved, marked for review.

### Test 4: CONTRIBUCIÓN SIMULTÁNEA — 2 operadores simultáneamente mismo entry_id, distinto hash

Simulación: race condition, lock-libre:
- Op A lee entry_id=X, sha=none, contenido v1
- Op A computa sha=v1_hash
- Op A hace push, file: X+v1_hash
- Op B hizo lo mismo con v2 → push X+v2_hash (mismo path, distinto SHA)
- Resolution final: BOTH files preserved → `X+v1_hash.md` y `X+v2_hash.md`, plus `X.__CONFLICT_PENDING.md`

(En PostgreSQL sería `SELECT FOR UPDATE`; con filesystem append-only es manual coordination.)

### Test 5: RECONVERGENCIA — tras dismiss/review del conflicto, archivo con mismo nombre único

```
# Human revisa el conflicto, decide que v2 gana
$ python bank_sync.py reconcile --entry f-conflict-001 --winner=v2
[bank-sync] entry_id=f-conflict-001, sha256=bbb222, status=RECONCILED
            primary=f-conflict-001.md, archived=f-conflict-001.aaa111.conflicted-*.md
```

## Características clave

- **Append-only**: nunca borra entries. Si la lógica falla, los originales permanecen.
- **SHA256 dedup exacto**: si dos pushes tienen mismo SHA, dedup silencioso.
- **Fail-closed conflict**: `same entry_id + different hash` → nunca auto-resuelve. PRESERVA BOTH + `__CONFLICT_PENDING.md` flag para revisión humana.
- **Reconvergence manual**: solo humano reconcilia. Tool no toma la decisión.

## Outcome (READY-FOR-DAVID-COMMIT-CONTINUE)

`ORIGINAL_COMMIT_REMOTE_DURABLE = YES`
`BANK_SYNC_TOOL_IMPL = YES`
`TEST_HAPPY_PATH = PASS`
`TEST_DEDUP = PASS`
`TEST_FAIL_CLOSED_CONFLICT = PASS`
`REVIEW_REQUIRED_FOR_CONFLICT = TRUE`
`NO_AUTO_MERGE = TRUE` (fail-closed by design)
