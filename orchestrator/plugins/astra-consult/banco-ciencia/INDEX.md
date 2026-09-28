# INDEX — Banco Científico de TraficLabPro (2026-09-12)

> **Origen**: idea nuestra. Este vault científico es **específico de Nafron**, trabaja con David en el ecosistema TraficLabPro. Otras personas que trabajen con Astra/Jupiter deberían tener su propio banco.
>
> **Regla de consolidación**: NO mezclar bancos individuales sin protocolo formal. Cada operador mantiene su propio cuaderno.

## Capítulos del banco (Nafron + David)

### `papers/` — evidencias con SHA + URL + texto verbatim
- `lane-a-r5-201911.md` — observación del subagente Lane A sobre `feat/scene-auto-01` REAUDIT R5
- `m591-pedestrian-preliminary-v1.md` — evidencia pedestrian v1.0 con sha256 de los 4 assets

### `findings/` — observaciones reproducibles
- `r4-id-collision-crossing-ids.md` — defecto en ID generation (frame*1000+gate) que colapsa 2 tracks mismo gate mismo frame
- `protected-false-not-missing-GO.md` — main branch protected=false NO prueba GO faltante en #92
- `merges-octubre-2026-fail-cascade.md` — race entre PR #91 + PR #88 con C5B audit previo

### `contradictions/` — contradicciones resueltas
- `ad4-stay-as-bounded-vs-doc-stale.md` — A4 audit decisión vs mensajes contradictorios en v1.0.1 docs
- `enforcer-rule-misinterp.md` — el enforcer no misfires en `gh[bot]` (Pusher=neokyhurtado-cmd directo)

### `decisions/` — decisiones operativas cerradas
- `opcion-B-mantener-merges.md` — Opción B (mantener #88/#91 + forward-fix), David 2026-09-12
- `effort-ultra-for-subagents.md` — David 2026-09-12T14:45Z
- `merges-pueden-venir-de-prompt-injection.md` —	checkeo cruzado fue correcto

### `prompts/` — prompts reutilizables (Nafron-N°)
- `how-to-launch-nafron.md`
- `protocolize-as-github-comment.md`

### `mis_tests/` — capturas crudas de mis propios tests
- `asfgrep-install-20260912.md`
- `pyright-install-20260912.md`

### `playbook/` — guiones de operación
- `codebase-QA-stack.md` — Nafron + rg + ast-grep + pyright + gh protocol

## Metadata de captura (v1 schema, banco-ciencia/v1)

Cada archivo `.md` arranca con YAML frontmatter:

```yaml
---
kind: finding | decision | contradiction | playbook | test | other   # alias: type
entry_id: <stable logical id, must match filename>
schema_version: banco-ciencia/v1
status: ACTIVE | SUPERSEDED | REJECTED
created_at: 2026-09-12T15:08Z   # alias: created
updated_at: 2026-09-12T15:08Z   # optional
origin_operator_or_session: nafron/jupiter/astra/...   # alias: owner
source_refs: ["traficlab-factory#14 c5648430968"]      # alias: refs
content_sha256: <recomputed by tool>                    # optional, tool-managed
supersedes: ["older-entry-id"]                          # optional, lineage
evidence_strength: A=peer-reviewed/verified | B=reproducible | C=claimed
---
```

Validate with: `python ../bank_sync.py validate` (exits 2 on FAIL).
META files (`INDEX.md`, `README.md`) and artifacts under `conflicts_pending/`,
`mis_tests/` are exempt from validation.

## Reglas de consolidación (Sync protocol v1)

S0/S2/S3 — Sync protocol v1 lives in `../bank_sync.py`. Use:

```text
python ../bank_sync.py validate           # schema gate
python ../bank_sync.py hash-recompute     # per-entry sha256 sidecars
python ../bank_sync.py manifest-build     # manifest.json
python ../bank_sync.py manifest-check     # drift detection
python ../bank_sync.py sync-classify --candidate <file>  # NEW/DUP/CONFLICT/OVERLAP
```

1. Cada operador mantiene su banco local **sin** sync automática silenciosa.
2. La sync se dispara via `git pull` + `manifest-check` (drift) + `validate`
   (schema gate); nunca merge global overwrite.
3. Conflictos = FAIL_CLOSED: ambos preservados en `conflicts_pending/`,
   resueltos vía `reconcile --entry X --winner=existing|new` (HUMAN-only).
4. Cualquier operador (JUPITER, Astra, Nafron, otra instancia Hermes)
   puede escribir; el consult loop usa `ask_astra --query "..."` para
   discovery read-only.
5. Bank entries son evidencia, no autoridad; el banco nunca autoriza
   merge / HUMAN_GO.

---
_Nafton arranca:_ `[qa-search]` 7 entries reales que verifico en la session actual.
