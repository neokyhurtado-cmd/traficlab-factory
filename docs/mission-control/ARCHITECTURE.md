# Architecture

Mission Control usa una sola bóveda lógica. Cada proyecto es un nodo dentro de ella.

```text
David -> Obsidian Mission Control
       -> IA-VISION -> GitHub/runtime
       -> SUINI -> GitHub/runtime
       -> TrafficLab Control -> GitHub/control-plane
       -> Panorama -> empresa/clientes
```

Autoridad: GitHub conserva hechos durables; Hermes conserva estado operativo; cada runtime conserva estado físico; Mission Control conserva conocimiento, decisiones, investigación e índices.

Cada computador mantiene su propio clon local del repositorio privado. Git sincroniza Markdown entre equipos. No usar simultáneamente otro sincronizador automático sobre el mismo working tree.

Archivos pesados pueden permanecer en almacenamiento externo. Mission Control guarda punteros e inventario, no copias innecesarias.

Cada proyecto debe contener: `PROJECT.md`, `STATE_POINTERS.md`, `ARCHITECTURE.md`, `DECISIONS.md`, `RESEARCH.md`, `INVENTORY.md`, `EVIDENCE_INDEX.md`, `OPEN_QUESTIONS.md` y `PROJECT_PROTOCOL.md`.

V1 usa enlaces y metadatos de Obsidian como grafo. No se introduce otra base de verdad.
