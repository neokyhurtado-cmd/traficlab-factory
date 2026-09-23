# ASHLEY-AGENT — Onboarding Blueprint v1
## HERMES-ASHLEY-01 | Read-only team member pilot

---

## 1. Identity

```yaml
AGENT_ID: HERMES-ASHLEY-01
HUMAN_OWNER: Ashley
MEMBER_STATE: ONBOARDING_READ_ONLY
ASSIGNED_PRODUCT: NONE
ACTIVE_WORK_ORDER: WO-TEAM-ASHLEY-01
```

---

## 2. Bootstrap workflow (step by step)

### Step 1 — Discover this host
Detecta de forma read-only:
- hostname
- usuario
- Git / GitHub auth
- Hermes version
- Hermes home actual
- repos autorizados

```bash
hostname
whoami
gh auth status
hermes --version 2>/dev/null || hermes -v 2>/dev/null
gh repo list neokyhurtado-cmd --limit 5
```

### Step 2 — Verify access
```bash
gh repo clone neokyhurtado-cmd/suini /tmp/verify-suini -- --depth 1 2>&1
gh repo clone neokyhurtado-cmd/IA-VISION /tmp/verify-iavision -- --depth 1 2>&1
```

### Step 3 — Read canonical sources (en orden)
1. `neokyhurtado-cmd/suini#29` — WO-TEAM-ASHLEY-01
2. `neokyhurtado-cmd/suini#31` — WO-TEAM-SKILLS-01
3. `neokyhurtado-cmd/suini#19` — ORCH-V1
4. `neokyhurtado-cmd/suini#20` — ORCH-V1.1

### Step 4 — Create CLAIM
En `suini#29`, comentar:
```
CLAIM WO-TEAM-ASHLEY-01
agent = HERMES-ASHLEY-01
member_state = ONBOARDING_READ_ONLY
host = <hostname detectado>
scope = onboarding/read-only
```

### Step 5 — Create local profile
```bash
mkdir -p $HOME/.hermes/profiles/ashley
```
Copiar estructura del perfil ia-vision (sin secrets):
- `profile.yaml` → ajustar descripción
- `SOUL.md` → ajustar para Ashley
- `config.yaml` → NO copiar tokens
- `memories/` → vacío al inicio

### Step 6 — Skills inventory
```bash
hermes skills_list --json > skills-inventory.json
```
Clasificar según WO-TEAM-SKILLS-01.

### Step 7 — Execute read-only pilot
Auditar:
- ¿puede leer repos?
- ¿puede hacer CLAIM en GitHub?
- ¿puede reconstruir contexto desde GitHub?
- ¿puede hacer reporte en Issue?

### Step 8 — Publicar resultado
En `suini#29`:
```
ASHLEY_AGENT_ID = HERMES-ASHLEY-01
ASHLEY_HOST = <host>
HERMES_VERSION = <versión>
HERMES_PROFILE = ashley
GITHUB_ACCESS = PASS/FAIL
IA_VISION_ACCESS = PASS/FAIL
SUINI_ACCESS = PASS/FAIL
WORK_ORDER_READ = PASS/FAIL
CLAIM_CREATED = PASS/FAIL
READ_ONLY_PILOT = PASS/FAIL
PRODUCT_FILES_CHANGED = 0
CONTEXT_RECONSTRUCTION = PASS/FAIL
ASHLEY_ONBOARDING = PASS / PARTIAL / BLOCKED
```

---

## 3. Permissions

| Puede | No puede |
|-------|----------|
| READ repos autorizados | WRITE en producto |
| READ Issues/WO | MERGE |
| CLAIM en Issues | DELETE |
| RESEARCH | Global config write |
| AUDIT | Cross-product write |
| TEST_READ_ONLY | Compartir secretos |
| PREPARE_PLAN | Asumir paths de David |
| REVIEW | Copiar Hermes home de David |

---

## 4. File structure (copy template, NOT David's actual files)

```
policies/
  authority-hierarchy.md    ← jerarquía GitHub > control-plane > Obsidian > chat
  work-order-contract.md   ← formato WO
  stop-go-protocol.md      ← regla STOP/GO
  security-rules.md        ← no secrets, RBAC

profiles/
  ashley/
    profile.yaml           ← plantilla perfil Ashley
    SOUL.md                ← plantilla SOUL para Ashley
    memories/
      memory.md            ← vacío, se llena con contexto propio
      user.md              ← identidad Ashley

.hermes/skills/                  ← repo-local skills (descubribles por agent_body/skill_discovery.py)
  internal-consult/SKILL.md
  skill-fabric-router/SKILL.md

.hermes/skills-registry/
  skills.yaml                    ← external skill registry (skill-fabric/v1)

agent_body/                       ← bootstrap sidecar (BODY-0..BODY-2)
  skill_discovery.py             ← repo-local skill discovery
  skill_registry.py              ← skill-fabric/v1 registry + validator + router

scripts/                          ← scripts de soporte
  install_hermes_runtime.py      ← smoke-check del runtime Hermes


---

## 5. Security rules

- NUNCA publicar API keys, tokens, .env, SSH private keys, cookies, 2FA
- NO copiar Hermes home de David
- NO compartir profile vivo con otro Hermes
- Secrets viven en secrets manager local, NO en GitHub/Obsidian/chat
