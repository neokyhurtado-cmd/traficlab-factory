---
type: decision
created: 2026-09-12T15:08Z
owner: Nafron/David
project: ia-vision-cadena-corrective
refs: ["issue #93 c5647822982", "comment ASTRA_DIRECTIVE c5647818016", "PR #91", "PR #88", "commit 53554d72e2e7c4858d169a81483e4024ffdc5d06"]
evidence_strength: A (verbatim David dictum on #93)
---

# Decisión: Opción B — mantener #88/#91 + corregir hacia adelante

## Contexto
La cadena ASTRA_CORRECTIVE_CLOSEOUT arrancó porque Nafron reportó `NO_BLOCKERS_REMAINING` y cerró #92 con merges hechos. La auditoría adversarial encontró luego que el merge tuvo governance-bad (CHANGES_REQUESTED outstanding en #91, Codex bot usage limit en #88).

## Opciones evaluadas
| Opción | Pro | Con |
|---|---|---|
| A — Rollback + forward-fix limpio | gobierno desde cero | revert operacional caro, churn branches |
| **B** — **Mantener + corregir hacia adelante (elegido)** | **ninguna reversión, código productivo queda** | **admite que merge-button fue actuation-bad** |
| C — Pausar y consultar Astra/Codex | consulta externa antes de decisión | pausa con C4 corriendo |

## Dictamen verbatim de David (issue #93 c5647822982)
> "Recomiendo B: conservar #91/#88 y corregir hacia adelante. Esta revisión atiende la consulta de la opción C; preparar las correcciones no necesita otra decisión tuya."

## Implicación operativa (Nafron)
- main HEAD `53554d72e2e7c4858d169a81483e4024ffdc5d06` se preserva **sin rollback**
- C1, C2, C3 avanzan con correcciones forward-fix:
  - C1.bis → PR #98 enforcer SHA-based origin matrix
  - C2.bis → PR #97 R4 ID collision adversarial
  - C3.review → PR #96+v2 reconciliation
- C5.B audit final consolidado + David single GO pendientes

## Lo que NO se hace
- No se hace `git revert -m 1 187766d1` ni `53554d72`
- No se reabre ciencia ni entrenamientos
- No se borran PRs/PRs abiertas
