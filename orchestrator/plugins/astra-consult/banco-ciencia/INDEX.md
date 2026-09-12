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

## Metadata de captura (Nafron-discoverable)

Cada archivo `.md` arranca con YAML frontmatter:
```yaml
---
type: finding | decision | paper | contradiction | prompt | test | playbook
created: 2026-09-12T15:08Z
owner: Nafron/David
project: ia-vision-cadena-corrective
refs: [<issue-id>, <pr-id>, <commit-sha>]
evidence_strength: A=peer-reviewed/verified | B= reproducible | C= claimed
---
```

## Reglas de consolidación (cuando llegue el momento)
1. Cada operador mantiene su banco individual **sin** sync automática
2. Consolidación solo cuando vos o el master-GO lo dispare
3. Consolidación = MANUAL o con diff check explícito; no global overwrite
4. El banco global vive en `_orchestrator_memory/ciencia_consolidada/`

---
_Nafton arranca:_ `[qa-search]` 7 entries reales que verifico en la session actual.
