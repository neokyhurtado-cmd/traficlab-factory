---
type: finding
created: 2026-09-12T15:08Z
owner: Nafron/David
project: ia-vision-cadena-corrective
refs: ["issue #93 c5647822982", "comment ASTRA_CLOSEOUT_RECTIFICATION", "PR #91", "PR #92"]
evidence_strength: A (verified by adversarial auditor on 34710115636)
---

# main `protected: false` NO prueba GO faltante

## Origen del error (Nafron propio)
El primer reporte de Nafron (voseo) sobre el enforcer failure dijo:
> "PR #88 y PR #91 entraron con governance-bad: CHANGES_REQUESTED outstanding + 6 hilos P1 sin responder"

David rectificó (verbatim):
> "protected:false no demuestra que faltara tu autorización. El historial de #92 registra un GO. Lo comprobado es que faltaba protección preventiva y se declaró el cierre antes de resolver los defectos."

## Lo que verifiqué después
- `gh api repos/neokyhurtado-cmd/IA-VISION/branches/main/protection` → 403 forbidden (GitHub Free plan NO soporta branch protection API / rulesets)
- `gh api repos/.../actions/runs/34710115636/jobs` → enforcer log: `Pusher=neokyhurtado-cmd` directo, no `gh[bot]`
- Es decir: **GO humano ya existía en #92**, lo que faltó fue **protección PREVENTIVA** (rulesets, PAT, pre-receive hook) — ambiental limit, no invasion

## Tesis corregida (lo que opera Nafron ahora)
- "merge-button actuation-bad" → **incorrecto**. Era "gate débil + GO legítimo".
- "fix enforcer YAML in main" → **insuficiente**. El enforcer post-push ES detector, no blocker. Prevención real requiere GitHub Pro o repo público o pre-receive hook — fuera del control del ASTRA_PROTOCOL.

## Implicación operativa
- C1 (enforcer re-write) está OK como documentation/honest-better-detector
- Pero NO aborta merges. Documentado en HONEST_BOUNDARIES HB-3..HB-7 dentro del YAML
- El bloqueador real es environmental: GitHub Free no soporta rulesets → blocker externo si queremos preventive bloqueo

## Link
- c5647822982 (rectificación David)
- c5647837991 (JUPITER_ACK retractado Nafron)
- C1.bis PR #98 branch `feat/enforcer-origin-matrix-v2` @ `20c5019f`
