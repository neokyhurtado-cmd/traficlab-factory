---
type: finding
created: 2026-09-12T15:08Z
owner: Nafron/David
project: ia-vision-cadena-corrective
refs: ["PR #97", "PR #95", "commit 01d30a52", "BR feat/rt-c2-r4-id-collision"]
evidence_strength: B (reproducible: 52/52 tests pass on fix branch, FAIL on baseline)
---

# R4 ID collision: dos tracks mismo gate mismo frame = mismo ID

## Tesis reproducible
En `06_scene_digital_model/replay/builder.py`, el `cruce_id` se derivaba como `frame_idx*1000+gate_id`. Esta fórmula **NO incluye `track_id` ni `video_id`**. Si dos personas cruzan la misma línea al mismo frame, reciben el mismo ID — la lógica de cruzamientos colapsa identidad.

## Reproducción (baseline en `5cae2a7+`)
```
frame_idx=100, gate_id=5, track_ids=[101, 102]
COLLISION: cruce_id=[100005, 100005]   # ← wrong, debería ser 2 distintos
```

## Fix propuesto por C2.bis
```python
# C2.bis canonical helper:
derive_cruce_id(track_id, gate_id, frame_idx, video_id=0) =
  v*1e13 + t*1e10 + g*1e7 + f*1e4
# donde v=video_id, t=track_id, g=gate_id, f=frame_idx
```

## Adopción
PR #97 (`feat/rt-c2-r4-id-collision` @ `01d30a52`) incluye:
- builder.py + sdm_builder.py patch
- 16 tests previos R1-R7 (preservados)
- 10 adversarial tests nuevos (2/3 tracks mismo gate mismo frame → 2/3 IDs distintos)
- 26 RT1 contract tests pre-existentes
- **52/52 tests pass en fix branch**
- CI run 34714163185 SUCCESS

## Ligado a PR #95
PR #95 (V2 correctivo) tenía este bug latente. C2.bis es el fix adversarial completo.

## Open question (out of scope aquí)
- ¿Cómo se sincroniza C2.bis con la rama del PR #95 al momento del merge final?
- ¿Tiene scope creep? El audit encontró `rt_visual_01.js` tocado también, fuera del scope declarado — no bloqueador pero documentado.
