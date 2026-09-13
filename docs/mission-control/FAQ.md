# FAQ — Panorama Mission Control V1

## ¿Cada proyecto tiene su propio Obsidian?
Tiene su propio nodo y contrato dentro de una sola bóveda maestra. No se crean bóvedas competidoras por defecto.

## ¿Dónde está la verdad del proyecto?
Los hechos de ingeniería viven en GitHub; el estado operativo en Hermes; el estado físico en el runtime. Mission Control explica, conecta e indexa esas verdades.

## ¿Qué pasa con OneDrive?
Sigue siendo útil para archivos grandes, históricos o externos. No debe ser el sincronizador primario del working tree de Mission Control.

## ¿Cómo trabajo desde dos computadores?
Cada equipo usa su propio clon local del mismo repositorio privado. Git reconcilia los cambios. No se comparte un único working tree físico entre equipos.

## ¿Qué pasa si ambos equipos editan la misma nota?
Se conserva el conflicto. Si es puramente mecánico puede reconciliarse; si contiene dos decisiones distintas se marca `NEEDS_RECONCILIATION` y ninguna se descarta silenciosamente.

## ¿Metemos videos, planos y miles de PDFs al repo?
No por defecto. Se inventarían y se representarían mediante punteros cuando sean archivos externos o pesados.

## ¿Hermes puede reorganizar solo?
Sí para índices, metadata, enlaces, inventarios y clasificación determinística. No para decidir silenciosamente qué versión humana contradictoria es la correcta.

## ¿Astra qué hace?
Audita arquitectura, detecta contradicciones entre proyectos, revisa migraciones y ayuda a resolver decisiones transversales.

## ¿Mission Control reemplaza TrafficLab Control?
No. Mission Control es conocimiento. TrafficLab Control es la superficie operacional. Deben enlazarse, no duplicarse.

## ¿Mission Control reemplaza GitHub Issues?
No. Un issue sigue siendo durable para trabajo de ingeniería. La nota de Mission Control puede resumirlo y enlazarlo.

## ¿Qué ocurre con las bóvedas viejas?
Primero se inventarían y compararían. Después de aceptación pueden quedar `LEGACY_READ_ONLY`. Borrarlas o limpiarlas es otra decisión.

## ¿Cómo nace un proyecto nuevo?
Repo/objetivo + nodo Mission Control + owner + agente + fuentes autoritativas + relaciones. Esto forma parte del protocolo de creación del proyecto.

## ¿Podemos agregar búsqueda semántica o embeddings?
Sí más adelante si hay un caso medible. V1 empieza con Markdown, enlaces, metadata y búsqueda normal para evitar infraestructura innecesaria.

## ¿Qué significa DONE?
No basta con que existan carpetas. Deben estar probados inventario, trazabilidad, ambos equipos, sincronización, conflicto controlado y lectura/escritura gobernada por los agentes.
