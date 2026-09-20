---
type: contradiction
created: 2026-09-12T15:08Z
owner: Nafron/David
project: ia-vision-cadena-corrective
refs: ["comment A4 audit 5647520218", "PR #96 a3b4ac5", "M591_Pedestrian_Report_v1.0.1.md"]
evidence_strength: A (audit decision 5647520218 verbatim)
---

# Contradicción resuelta: A4 audit pending vs decision ya publicada

## Síntoma
Los documentos v1.0.1 (MD/PDF/XLSX) contienen mensajes contradictorios sobre el audit A4:
- `LIM-04`, `LIM-05`, `LIM-12` en `06_LIMITACIONES` dicen: *"A4 audit will decide final certification"*
- El front-matter de sección §4.1 dice: *"STAY_AS_BOUNDED_SAMPLE_DIAGNOSTIC; valid_gate_crossings_count = null; NOT_RUN for full jornada"*

Pero el **subagente A4 ya emitió veredicto** con comment id `5647520218` (issue #79 /mirror #93).

## Decisión del A4 (verbatim, comment 5647520218)
```
GATE_CROSSINGS_FINAL_DECISION = STAY_AS_BOUNDED_SAMPLE_DIAGNOSTIC
VALID_GATE_CROSSINGS_READY    = NO
CERTIFIED_ROWS                 = 0
DELIVERY_CLASS                 = PRELIMINARY
FINAL_VERDICT                  = PEDESTRIAN_FINAL_DELIVERY_READY
```

## Cómo se resuelve (per Astra consulta con 5 guardrails)
- Reemplazar `"A4 audit pending"` → `"A4 audit COMPLETED 2026-09-12 17:30Z (PR comment 5647520218); decision: STAY_AS_BOUNDED_SAMPLE_DIAGNOSTIC"`
- Reemplazar `"awaiting reviewer"` → `"awaiting David HUMAN_GO_REAL_REQUIRED for C1.bis + C2.bis + C3 addition before merge"`
- `LIM-04/05/12` deben preservar el limitation ID y agregar nota `v101_A4_DECISION_RECONCILED` que apunte a §4.1 + comment id 5647520218
- NO borrar texto contradictorio — anotarlo, no eliminar

## Estado actual
- **C3 original directiva era imposible literal** (artifacts viven en `a3b4ac5`, no en main) → subagente paró con HARD_STOP honesto
- **C3.v2 path approved by Astra** (cherry-pick a3b4ac5 a rama `feat/pedestrian-v1.0.1-a4-clarify-v2`)
- **C3.v2 aún pendiente de ejecución** (per tu directiva "conservar worktree")

## Lo que se aprende
- Los audit comments deben ser referenciados verbatim, no paraphraseados
- Per-frontmatter `A4_DECISION_QUOTED` idealmente es bloque de contrato en todo docs v101+
