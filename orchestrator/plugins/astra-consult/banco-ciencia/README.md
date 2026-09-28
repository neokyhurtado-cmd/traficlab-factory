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
3. ✅ Sync protocol v1 implementado (banco-ciencia/v1) — ver "Sync protocol v1" abajo

## Sync protocol v1 (2026-09-12, directive astra-scientific-bank-distributed-sync-20260912-01)

The bank now exposes a deterministic, fail-closed, multi-operator sync protocol
implemented in `../bank_sync.py`. Stdlib-only Python; no extra services.

### Entry identity (v1 frontmatter)

```yaml
---
kind: finding|decision|contradiction|playbook|test|other
entry_id: <stable logical id, must match filename>
schema_version: banco-ciencia/v1
status: ACTIVE|SUPERSEDED|REJECTED
created_at: 2026-09-12T15:08Z
updated_at: 2026-09-12T15:08Z   # optional
origin_operator_or_session: nafron/jupiter-astra/...   # optional, non-secret
source_refs: ["traficlab-factory#14 c5648430968"]      # optional, alias: refs
content_sha256: <recomputed by tool>                    # optional, tool-managed
supersedes: ["older-entry-id"]                          # optional, lineage
---
```

`type` is accepted as a v0 alias for `kind` (back-compat).

### Where it lives

META files (`INDEX.md`, `README.md`) and conflict/test artifacts under
`conflicts_pending/`, `mis_tests/` are exempt from schema validation.

### CLI subcommands

| Command | What it does |
|---|---|
| `high --entry X --content file.md` | Append/dedup/fail-closed HIGH entry. |
| `dedup --entry X` | Check existing sha256 for entry X. |
| `reconcile --entry X --winner=existing\|new` | HUMAN-only conflict resolution. |
| `ask_astra --query "..."` | Read-only discovery for Astra/Jupiter consult loop. |
| `list_conflicts` | List pending CONFLICT_PENDING flags. |
| `validate [--strict]` | Validate every non-meta entry against v1 schema. |
| `hash-recompute [--subdir X]` | Write `.sha256` sidecar files next to each entry. |
| `manifest-build [--out path]` | Emit `manifest.json` with per-entry sha256. |
| `manifest-check [--manifest path]` | Verify manifest against current bank (FAIL on drift/diff/missing). |
| `sync-classify --candidate file.md` | Read-only classification: NEW / EXACT_DUPLICATE / SAME_ID_DIFFERENT_HASH_CONFLICT / DIFFERENT_ID_SEMANTIC_OVERLAP_REVIEW_CANDIDATE. Never deletes. |

### Convergence rule

Git/GitHub is durable truth for shared bank content. Local operator banks
are working copies.

1. Read remote bank manifest/index.
2. Validate local candidate schema + hash.
3. Classify exact duplicate / conflict / new via `sync-classify`.
4. Append-only new entries; flag conflicts (FAIL_CLOSED, preserve both).
5. Update generated/index metadata deterministically.
6. Test from a second clean clone (`git clone --branch fix/telegram-normal-hermes-session`).
7. Publish via feature branch / PR under normal governance.

**No silent overwrite. No deletion merely because another operator has a
newer entry.**

### Consult-loop integration (S6)

- `ask_astra --query "..."` is the read-only discovery surface used by
  Astra/Jupiter when answering scientific or architecture questions.
- Bank entries are **evidence**, not infallible authority. Contradictions
  are surfaced; superseded entries are excluded by default but remain
  traceable. Source refs are preserved. The bank never authorizes
  merge/HUMAN_GO.

## Source-of-truth (Nafron — 2026-09-12)

Esta errore fue cometida por Nafron, no por David. Reconozco la confusión entre "tu herramienta personal" y "del ecosistema". Corregido y movido al system path.
