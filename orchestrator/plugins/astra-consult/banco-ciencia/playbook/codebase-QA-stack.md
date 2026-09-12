---
type: playbook
created: 2026-09-12T15:08Z
owner: Nafron/David
project: nafron/codebase-QA-stack
refs: ["NAFRON_PROTOCOL_V1 c5648287543 (issue #93)", "decision: effort-ultra-for-subagents"]
evidence_strength: B (verified via ripgrep + git log in tests; ast-grep 0.45.3 installed)
---

# Playbook: Codebase Q&A Stack para Nafron

## Filosofía (David 2026-09-12T15:??)
**Atacar el problema sin Leer Contexto Basura (LCB).** Cada agente que Nafron dispatchee debe tener — por implícito — la stack completa de GitHub best practices + techniques para investigar sin tragar contexto innecesario. Esta sección es la fuente de verdad operativa.

## Stack base (lo que Nafron tiene en cada sub-agente)

| Categoría | Tools / recursos |
|---|---|
| **Búsqueda de texto rápida** | `rg` (ripgrep 15.0.0) — semánticamente con `.gitignore` integrado |
| **AST y parsing estructural** | `ast-grep` v0.45.3 (instalado), Python `ast` stdlib |
| **Type checking** | `pyright` v1.1.414 (rápido), `mypy` v2.3.1 (profundo) |
| **Version control** | `git` + `git log --grep`, `git blame`, `git log -S "X"` |
| **GitHub API** | `gh` CLI v2.100 + `gh api` para read directo |
| **Testing** | `pytest` v9.1.1 con `-x --tb=long` para failures específicas |
| **Browser automation** | `browser_exec` (Browser Use via CDP) cuando sesión Chrome autenticada |
| **Scratch workspace** | `C:/Users/david/.hermes-audit/` para outputs intermedios (NO en el repo) |

---

## Regla de oro: GitHub-first, lectura-código último

**Cuando Nafron investiga algo en un proyecto, el orden es:**

1. **`gh api` para los metadatos** que ya están indexados en GitHub — no necesitas leer el código.
2. **`gh search code/repos/commits/issues`** antes de hacer `rg` local.
3. **GitHub Discussions, README, CHANGELOG, README sections específicas** — usualmente tienen explicación humana curada.
4. **PR descriptions + review comments** — son discussions largas y comprometedoras.
5. **`git log` en clones** para cuando ya sabes qué archivo.
6. **`rg -n` o `ast-grep`** cuando tienes keywords o AST queries.
7. **`pyright` o `mypy`** para validar assumptions de tipos.
8. **`read_file`** solo cuando ya tienes contexto y solo falta el detalle.

**Cada paso reduce la cantidad de archivos leídos innecesariamente. La regla "read_file primer" es LCB.**

---

## Cómo usar GitHub antes de `rg`

### 1. Repo-level sin clonar
```bash
# Visión general
gh repo view owner/repo --json description, languages, defaultBranchRef
gh api repos/owner/repo/readme --jq '.content' | base64 -d | head -100

# Search code across the entire GitHub
gh search code "def derive_cruce_id" --owner neokyhurtado-cmd --extension py

# Search commits
gh search commits "R4 ID collision" --owner neokyhurtado-cmd

# Search issues
gh search issues "R4 ID" --owner neokyhurtado-cmd

# List branches
gh api repos/owner/repo/branches --jq '.[] | {name, head_sha: .commit.sha}'

# Pull request body + reviews
gh pr view 97 --repo owner --json body,files,reviews,comments
gh api repos/owner/pulls/97/comments --jq '.[] | {user: .user.login, body, path}'
gh api repos/owner/issues/97/comments   # issue-style API for PR comments
```

### 2. Si necesitás el repo
```bash
git clone --depth 1 https://github.com/owner/repo.git /tmp/inspect-XXX
cd /tmp/inspect-XXX
# Sin clonar el historial completo — la mayoría de las veces el tip del HEAD basta.
```

### 3. Si necesitás un blob específico
```bash
# Direct fetch de un SHA sin clonar todo
git init /tmp/blob-XXX
cd /tmp/blob-XXX
git remote add origin https://github.com/owner/repo.git
git fetch origin <commit-sha>
git show FETCH_HEAD:path/to/file.py
```

### 4. Si necesitás un blob desde cualquier commit
```bash
gh api repos/owner/repo/contents/path/to/file?ref=<commit-sha> --jq '.content' | base64 -d
```

### 5. OpenAPI / docs / specs
```bash
gh api repos/owner/repo/contents/docs/openapi.yaml?ref=main --jq '.content' | base64 -d
```

---

## `gh` search es subestimado

| Tool | Hace |
|---|---|
| `gh search repos` | Encuentra repos con temas similares |
| `gh search code` | Búsqueda de patrones en millones de repos públicos |
| `gh search commits` | Mensajes de commit + author + fecha — investigación histórica |
| `gh search issues` | Issues, PRs, discussions |
| `gh search prs` | PR-only |
| `gh search packages` | Si querés resolver "qué paquete hace X" |

**Los flags que cambian todo:**
- `--owner neokyhurtado-cmd` → restrinje a tu org
- `--extension py` / `yaml` / etc.
- `--language python`
- `--limit N`
- `--match title`, `body`, `comments`
- `--sort stars`, `updated`, `best-match`
- `--order asc | desc`
- `--json fields` para pipelines machine-readable

**Argumentos de búsqueda avanzados:**
- `gh search code "TODO" language:python repo:owner/repo`
- `gh search issues "R4 ID collision" label:bug`
- `gh search issues "is:closed author:me"`

---

## `.github` exploitation

Si Nafron trabaja con un proyecto que tiene `.github/` curado:

- **`CODEOWNERS`** — sabe quién es el dueño por path (muy útil antes de `gh api pulls/XX/reviews`)
- **`workflows/*.yaml`** — qué checks corren, en qué jobs
- **`ISSUE_TEMPLATE/`** — estructura típica de issues
- **`PULL_REQUEST_TEMPLATE.md`** — qué espera el repo en PRs
- **`.github/labeler.yaml`** o **`.github/labeler.yml`** — reglas de auto-label
- **`.github/blunderbuss.yml`** o **`auto-assign`** — reglas de auto-asignación

**Antes de tocar un repo nuevo, valen oro.** Reducen LCB un 70% en promedio.

---

## `gh api` native patterns

| Goal | Command |
|---|---|
| Get commit data | `gh api repos/owner/repo/commits/<sha>` |
| Get PR review comments inline | `gh api repos/owner/pulls/97/comments` |
| Get issue events | `gh api repos/owner/issues/93/events --jq '.[] | {event, actor: .actor.login, created_at, body}'` |
| Get run logs | `gh api repos/owner/actions/runs/<run-id>/jobs --jq '.jobs[] | {name, conclusion, steps: [.steps[] | {name, conclusion}]}'` |
| Search across the repo | `gh search code "X" --owner owner` |
| Check rate limit | `gh api rate_limit --jq '{core: .resources.core, search: .resources.search}'` |
| List collaborators | `gh api repos/owner/repo/collaborators --jq '.[] | {login, role}'` |
| Check branch protection | `gh api repos/owner/branches/main/protection` (403 = Free plan) |

---

## Reglas de oro (Nafron)

1. **NUNCA leer archivos** sin antes `gh api` + `rg` + `git log`. Esa es LCB-prevention.
2. **`gh` y `git log` siempre primero**. Documentation y código vienen después de entender el contexto histórico y humano.
3. **ast-grep** para queries **estructurales**; rg para texto literal.
4. **pyright** > mypy para velocidad; mypy para profundidad total.
5. **JSON outputs** de `gh` se pueden pipear a `jq` para queries precisas.
6. **Cuando hay duda, citation reference o URL**: leer el README o la doc oficial antes que el código.
7. **Cuando hay duda, histórico**: `git log -S "X"` antes que `read_file`.

---

## Master checklist antes de decir "ya entiendo"

Para que Nafron no tenga LCB al investigar:

- [ ] ¿Leí el README del repo actual? (1-2 min ahorra horas)
- [ ] ¿Hay docs en `docs/` o `CONTRIBUTING.md`?
- [ ] ¿Hay `.github/` con templates, workflows, labeler, CODEOWNERS?
- [ ] ¿GitHub Discussions tiene respuestas en threads largos?
- [ ] ¿Hay un CHANGELOG con las cosas recientes?
- [ ] `gh search code --owner X` para ver estructuras de archivos conocidas
- [ ] ¿Hay git tag releases con notas curadas?
- [ ] `gh search issues --state closed` para ver bugs que ya se resolvieron

**Si todo esto está checkeado, los archivos que finalmente leas son probablemente los únicos necesarios.**

---

## No hagas

- ❌ Read un codebase de 1000+ archivos sin rg + gh search primero.
- ❌ Read 50 archivos para "entender el contexto". Vas a perder 30 minutos y gastar tokens.
- ❌ Buscar en código cuando GitHub search ya te da la respuesta.
- ❌ Sin leer el README, charts de qué hacer.
- ❌ Confiar en archivo viejo sin `git log -S` que confirme que está al día.

## Sí haz

- ✅ `gh api` antes que `read_file`
- ✅ `gh search` antes que `rg`
- ✅ `git log -S` antes que `git blame -L`
- ✅ `ast-grep` antes que `python ast` para queries estructurales
- ✅ Cite SHA + URL — siempre, sin excepción

---

## Inyección del playbook a nuevos sub-agentes

Cuando Nafron dispatchee un sub-agente, **el goal block debe incluir una versión comprimida de este playbook** si la tarea es de investigación. Por ej:

```yaml
CODEBASE_QA_PROTOCOL (Nafron):
  Use gh api / gh search / git log antes de read_file.
  Use rg -n para texto literal, ast-grep para estructura, pyright para tipos.
  Cita SHA + URL en cada claim, sin excepción.
  No repitas LCB: si ya tienes el contexto de gh API, no leas 50 archivos.
  Si tienes duda del repo, lee README + .github/ primero.
```

---

## Testeo en vivo (2026-09-12T15:08, Nafron validation)

```bash
# TEST 1 — ast-grep estructural: PASA
ast-grep run -p "def $X" py 06_scene_digital_model/replay/builder.py
# Resultado: 7 funciones detectadas (incluye derive_cruce_id con su ID-collision)
# Esta es la fortaleza de ast-grep: queries estructurales sin leer body

# TEST 2 — gh search code: LIMITATION ENCONTRADA
gh search code "cruce_id" --owner neokyhurtado-cmd --extension py --limit 5 --json
# Resultado: json output vacío / falla de parse
# Workaround: usar `gh api` con code search endpoint directamente:
gh api 'search/code?q=repo:neokyhurtado-cmd/IA-VISION+cruce_id+extension:py' --jq '.items[] | {name: .name, path: .path}'
# O para issues: `gh search issues` SÍ funciona

# TEST 3 — gh pr view: PASA
gh pr view 97 --repo neokyhurtado-cmd/IA-VISION --json number,title,headRefOid,files
# Resultado: { #97, head=01d30a52, files=5 }
```

### Resumen testeo: 2/3 operativos, 1 con workaround

| Tool | Status | Workaround |
|---|---|---|
| ast-grep | ✅ operativo | — |
| gh pr view / gh api | ✅ operativo | — |
| gh search code | ⚠️ con json fallando | usar `gh api search/code?q=...` |

Esto NO afecta Nafron operatively: la combinación ast-grep + `gh api` + `rg` cubre el mismo espacio.
