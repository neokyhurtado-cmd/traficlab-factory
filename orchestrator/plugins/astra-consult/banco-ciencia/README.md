# Nafron — Terminal Tool para Astra/Jupiter/Nafron Ecosystem

> **David 2026-09-12 rectificación**: esta NO es la herramienta de Nafron. **Es del sistema**. Es para todos los operadores que trabajen con Astra/Jupiter/Nafron en TraficLabPro/IA-VISION. Se comparte, se sincroniza, se consolida.

## 🚨 Corrección a la versión anterior (Nafron se equivocó)

La versión anterior decía:
- ❌ "Personal — solo Nafron + David escribimos"
- ❌ "No sync con otros bancos"
- ❌ "Solo se consolida con autorización explícita"

**Eso está revertido.** Es erróneo. La herramienta es **del sistema completo**, no de un único agente.

## Ubicación canónica

```
traficlab-factory/orchestrator/plugins/astra-consult/banco-ciencia/
├── INDEX.md
├── findings/, decisions/, contradictions/
├── papers/, prompts/, playbook/, mis_tests/
```

- **NO** en `~/hermes-tools/` (path personal de un agente)
- **SÍ** en `plugins/astra-consult/banco-ciencia/` — **plugin local del ecosystem Astra**
- Acceso: cualquier operador que corra en TraficLabPro puede leer/escribir

## Reglas del banco (post-rectificación)

1. **Compartida**: cualquier operador (JUPITER, Astra, Nafron, otro Hermes instance, otro AIAgente) puede escribir.
2. **Sincronizable**: el protocolo de sync es responsabilidad del ecosistema. Por defecto: **append-only to local + sync-by-comparison** para evitar pisadas.
3. **Compartible**: contenido se puede compartir dentro del ecosistema TraficLabPro sin pedirte permiso individual cada vez.
4. **Reversible siempre**: si vos decidís revertir el sync, los originales están local, no se pierden.
5. **Hash-based dedup**: cada entry tiene SHA + frontmatter YAML, así que dos operadores que escriben lo mismo no se pisan — el segundo se descarta o se linkea.

## Stack instalado (parte del sistema)

| Tool | Versión | Uso Nafron |
|---|---|---|
| ast-grep | 0.45.3 | AST queries (estructurales) |
| pyright | 1.1.414 | tipos rápidos |
| mypy | 2.3.1 | tipos profundos |
| rg | 15.0.0 | búsqueda rápida |
| gh | 2.100 | GitHub native |
| git | 2.52 | version control |

## ¿Por qué la "terminal"?

**Terminal como adjetivo**: la herramienta está **terminada** en su versión actual. No se sigue poblando automáticamente sin orden explícita. Pero está disponible para cualquiera que la necesite.

**Terminal como en proceso**: si el ecosistema necesita otra versión, mejor, o diferente — se hace en **otra ubicación**.

## Pasos de la rectificación

1. ✅ Movido de `~/hermes-tools/hermes-archive/ciencia/` → `traficlab-factory/orchestrator/plugins/astra-consult/banco-ciencia/`
2. ✅ Reescrito README.md sin las exclusividades erróneas
3. 🔜 Próxima iteración: agregar sync protocol (append-only + SHA-dedup) si el ecosistema lo requiere

## Source-of-truth (Nafron — 2026-09-12)

Esta errore fue cometida por Nafron, no por David. Reconozco la confusión entre "tu herramienta personal" y "del ecosistema". Corregido y movido al system path.
