# Revision inicial de optimizacion: SUINI + IA-VISION

Fecha: 2026-09-30. Analisis de codigo, sin benchmark del servidor.
No se declaran porcentajes de mejora ni refactors ejecutados en los productos.

| Prioridad | Proyecto y evidencia | Problema observado | Siguiente accion y prueba |
|---|---|---|---|
| 1 | IA-VISION, `traffic_explorer/core/analytics.py`, `heatmap`, SHA `e0675014c41b300ebd2ad1023cc083f8848e42d4` | Los joins no fijan toda la identidad del run/track; cruces se une por video/frame, pudiendo multiplicar detecciones. Algunos filtros cambian significado y LIMIT antecede al histograma. | Primero corregir identidad y filtros dentro de la lane existente de analitica; comparar conteos con fixtures multirun/multicruce y revisar EXPLAIN QUERY PLAN. |
| 2 | SUINI, `src/motor_sim/worker_sim.js`, `runConflictAreaEmitter`, SHA `bf4a0887a4bed95f727483aff6b437cb02f3e8f3` | Ya hay indice de vehiculos por carril, pero cada vehiculo cerca del conflicto recorre todas las areas y vuelve a recorrer candidatos del otro carril. | Medir CPU por step con vehiculos/areas crecientes; evaluar indice areas-por-carril y mejores candidatos por carril, con invalidacion explicita. |
| 3 | SUINI, `src/suini/measure/snapshot.py`, `SnapshotProjector.project`, mismo SHA | Cada proyeccion normaliza, crea objetos, ordena vehiculos/eventos/senales y calcula content SHA. No esta demostrado que se repita innecesariamente. | Perfilar cada fase y frecuencia por run/seq. Evaluar reutilizacion solo si varias lecturas del mismo contenido inmutable repiten el costo. |

## 1. IA-VISION: mapa correcto antes de acelerar consultas

Fuente exacta: https://github.com/neokyhurtado-cmd/IA-VISION/blob/e0675014c41b300ebd2ad1023cc083f8848e42d4/traffic_explorer/core/analytics.py

Se observa en `heatmap`:

- `detecciones` se une a `tracks` por `video_id` y `track_id_yolo`; no aparece
  `corrida_id` en ese join. Con IDs reutilizados entre runs, debe demostrarse
  que la consulta no mezcla filas.
- `cruces` se une por `video_id` y `frame_idx`, sin relacionar el track.
  Varios cruces en el mismo frame pueden multiplicar filas; el inner join
  tambien puede excluir detecciones que no tengan un cruce en ese frame.
- `c.gate_id` se sustituye por `t.video_id`; cardinal/sentido por `t.cls_name`.
  Esas sustituciones no conservan el significado de los filtros.
- El LIMIT se aplica antes del histograma; el rango de coordenadas se calcula
  sobre las filas obtenidas. Debe declararse muestreo/truncamiento y una base
  espacial estable para comparar mapas.

Propuesta para el writer de analitica: verificar schema y unicidad reales;
usar identidad completa run/video/track, y EXISTS o un conjunto deduplicado
cuando se filtre pertenencia a una puerta. Elegir histograma agregado o
streaming acotado segun EXPLAIN y volumen real. No crear indices a ciegas.
Aplicar la misma auditoria de identidad/completitud a OD/TMC sin abrir otra lane.

Aceptacion: dos runs con el mismo YOLO ID; dos cruces en un frame; track sin
cruce; filtros de clase/puerta/cardinal/tiempo; total de detecciones esperado;
truncamiento explicito; mismas coordenadas de comparacion. Medir latencia,
filas intermedias y memoria antes/despues con exactamente las mismas entradas.
No reclasificar los 451 UNRESOLVED para hacer pasar un test.

## 2. SUINI: evitar busquedas repetidas por step

Fuente exacta: https://github.com/neokyhurtado-cmd/suini/blob/bf4a0887a4bed95f727483aff6b437cb02f3e8f3/src/motor_sim/worker_sim.js

`runConflictAreaEmitter` ya construye `byLane` una vez por step. El candidato
es la busqueda restante: todas las areas por cada vehiculo relevante y los
candidatos del carril opuesto por cada evento. El beneficio depende del numero
de vehiculos cerca del conflicto y de areas/candidatos; aun no se ha medido.

Evaluar `areasByLane` conservando el orden original de areas y reconstruirlo
cuando cambien red o registro de conflictos. Evaluar candidatos ordenados o
los mejores dos por carril para conservar la exclusion del propio vehiculo,
los empates y el caso de conflicto dentro del mismo carril.

Aceptacion: mismo seed, red, secuencia y eventos byte-equivalentes; mismo
`other_party` (incluido null), clasificacion, orden y deduplicacion. Medir p50/p95
del step y memoria con cargas crecientes, incluyendo red vacia y cambios de red.
No modificar el vendor como atajo ni cambiar semantica de seguridad.

## 3. SUINI: medir construccion de snapshots

Fuente exacta: https://github.com/neokyhurtado-cmd/suini/blob/bf4a0887a4bed95f727483aff6b437cb02f3e8f3/src/suini/measure/snapshot.py

Medir normalizacion, sort, conversion y hash por separado con 1.000 y 10.000
vehiculos; registrar cuantas proyecciones ocurren por `(run_id, snapshot_seq)`.
Si solo hay una por secuencia, una cache puede agregar costo sin beneficio.

Si existe repeticion, estudiar reutilizacion por identidad del contenido
realmente inmutable. Un dataclass frozen no vuelve inmutables sus diccionarios
internos: auditar tambien esa propiedad. No cachear solo por run/seq si el
contenido puede cambiar, ni quitar el hash o cambiar el sort lexicografico.

Aceptacion: snapshots y content SHA iguales, eventos/orden/provenance identicos,
monotonia y unidades preservadas; benchmark con mismas entradas y consumidores.

## Cadencia de la herramienta

Care hace triage estatico Python de archivos tracked y deja candidatos con
SHA de contenido. Esa inspeccion automatica no sustituye este analisis de
JS/SQL, el profiling, ni la review exact-SHA. GitHub y Obsidian conservan
punteros/contexto; Factory asigna el writer y evita competir con lanes activas.

El servidor es uno; las cuentas Windows David y Ashley son distintas. Medir
RAM/disco por host y atribuir ejecuciones por perfil/cuenta. No sumar las dos
observaciones como si fueran dos maquinas. No hay medicion fresca del host
real en este informe.
