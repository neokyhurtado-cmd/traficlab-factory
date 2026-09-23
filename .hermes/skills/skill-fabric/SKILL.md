---
name: skill-fabric
description: Governed external skill integration — registry, intake, router, conflict resolution
version: 0.1.0-implant-20260922-01
status: SCAFFOLD
metadata:
  hermes:
    tags: [skill-fabric, registry, external-skills, intake, router, conflict-resolution]
    soT_authority: "GitHub issue neokyhurtado-cmd/traficlab-factory#51"
    parent_directive: skill-fabric-v1-implant-20260922-01
    upstream: "native (no external skills registered at SCAFFOLD state)"
---

# Skill Fabric — Governed External Skill Integration

## Purpose

Implant a professional layer for **external** skills into the Hermes/Factory control plane that already exists. Skills are subordinate to canonical Factory authority:

```text
GitHub durable truth
> TrafficLab Factory policies / authority
> Agent Body capability boundaries
> project contracts
> external skill instructions
```

An external skill can add capability. It can NEVER override authority, merge policy, HUMAN_GO_REAL, source-of-truth rules, secrets rules, one-writer rules, or product ownership.

## When to Use

Use this skill when:

- A new external skill candidate is proposed for Factory adoption.
- A task intent should resolve to the smallest relevant skill subset (not all skills).
- A skill-conflict scenario needs deterministic resolution in favor of canonical Factory policy.
- Auditing whether an installed skill meets the intake gates (license, pinned SHA, isolation, etc.).

Do NOT use this skill when:

- The task is a normal in-process Python edit (use the language tool).
- The task is a one-shot read-only git/gh lookup (no skill routing needed).
- The user explicitly asks for a specific skill by name and it is already ACTIVE in the registry.

## Architecture (V1 — SCAFFOLD state)

```text
                +----------------------------+
                | Task intent (Hermes worker)|
                +-------------+--------------+
                              |
                              v
                +-------------+--------------+
                | Progressive skill router   |  <-- .hermes/skills/skill-fabric/router.py
                | (smallest relevant subset) |
                +-------------+--------------+
                              |
                              v
                +-------------+--------------+
                | Registry consult           |  <-- agent_body/skill_fabric/registry.py
                | (mode + pin + allowlist)   |
                +-------------+--------------+
                              |
                +-------------+-------------+
                | Approved skill subset      |
                | loaded on demand           |
                +-------------+--------------+
                              |
                              v
                +-------------+--------------+
                | Conflict resolver          |  <-- agent_body/skill_fabric/conflict.py
                | (canonical Factory wins)   |
                +----------------------------+
```

Components (V1 SCAFFOLD):

- `agent_body/skill_fabric/registry.py` — schema, loader, validator
- `agent_body/skill_fabric/intake.py` — fail-closed intake policy gate
- `agent_body/skill_fabric/router.py` — task-intent → smallest relevant skill subset
- `agent_body/skill_fabric/conflict.py` — deterministic conflict resolver
- `agent_body/skill_fabric/graph_adapter.py` — read-only derived graph adapter (SHADOW only at SCAFFOLD)
- `docs/skill-fabric-v1/` — human-readable policies, intake policy, conflict matrix

## Registry schema (per skill)

```yaml
id:                       # stable id, e.g. diagram-design
upstream_repo:            # owner/repo
upstream_commit:          # exact 40-char SHA (no floating refs for ACTIVE)
upstream_license:         # SPDX id; null = REJECTED
mode:                     # BLOCKED | CANDIDATE | SHADOW | ACTIVE | CATALOG
capabilities:             # free-form list, used by router
network_access:           # true | false
filesystem_read:          # glob
filesystem_write:         # glob or none
shell_exec:               # true | false
subagent_spawn:           # true | false
prompt_injection_surface: # none | low | medium | high
dependency_install:       # none | isolated_test_only
conflicts:                # list of other skill ids known to conflict
allowed_projects:         # list of project ids, ["*"] = any
activation_scope:         # on_demand | always | shadow_only
rollback:                 # reversible via removing registry row + clearing cache
evidence:                 # path to evidence directory (G0 audit, canary logs)
```

## Intake gates (fail-closed)

1. License must be SPDX-known AND compatible with the project (default Apache-2.0/MIT/BSD-2/BSD-3).
2. Floating upstream refs (`main`, `latest`, branch-only) are REJECTED for ACTIVE mode.
3. Network access beyond declared endpoints is REJECTED.
4. Public bind / scheduled daemon / auto-update from upstream is REJECTED.
5. Skill MUST NOT request merge/release authority, secret write, config mutation, gateway/channel mutation, env mutation, model/provider change.
6. Skill MUST NOT redefine system instructions or authority hierarchy.
7. Any skill file copy MUST carry provenance (source URL + commit SHA + license).
8. Dependency install happens ONLY in isolated test scope (no global pip/npm against Factory env).

## Router behavior

Given a task intent, the router returns the **smallest** set of skills whose declared `capabilities` overlap with the intent and whose `mode in {ACTIVE, SHADOW}` AND `allowed_projects ⊇ current project`. SHADOW skills are loaded only for shadow canary tasks. CATALOG skills are NEVER auto-loaded (they only inform candidate discovery).

## Conflict resolver behavior

When two loaded skills produce conflicting instructions, the resolver applies these rules in order:

1. If conflict is between an external skill and canonical Factory policy → Factory wins.
2. If conflict is between two external skills → consult `conflicts:` field; if both are listed as conflicting, REJECT both for that task scope.
3. If conflict is structural (e.g., both want to redefine authority) → REJECT both.

## Hard no-go (mirrors issue #51 no-go list)

```text
DIRECT_MAIN_WRITE    = NO
FORCE_PUSH           = NO
AUTO_MERGE_MAIN      = NO
SECRETS_MUTATION     = NO
CONFIG_YAML_MUTATION = NO
ENV_MUTATION         = NO
GATEWAY_MUTATION     = NO
TELEGRAM_MUTATION    = NO
DISCORD_MUTATION     = NO
WHATSAPP_MUTATION    = NO
MODEL_PROVIDER_CHANGE = NO
NEW_ORCHESTRATOR     = NO
NEW_VECTOR_DB        = NO
NEW_KNOWLEDGE_BASE   = NO
PUBLIC_LISTENER      = NO
SECOND_SOURCE_OF_TRUTH = NO
```

If a proposed skill demands any of the above, intake returns `BLOCKED` with evidence.

## V1 rollout intent (initial, security may downgrade)

```text
diagram-design              -> CANDIDATE -> SHADOW -> ACTIVE (on evidence)
last30days-skill            -> CANDIDATE -> SHADOW (network research only)
agentic-awesome-skills      -> CATALOG ONLY (discovery, never auto-install)
superpowers                 -> SHADOW/COMPARE; never overrides Factory protocol
graphify                    -> READ-ONLY SHADOW adapter
Understand-Anything         -> READ-ONLY SHADOW adapter
ponytail                    -> CANDIDATE; conflict-tested before activation
caveman                     -> CANDIDATE; conflict-tested before activation
i-have-adhd                 -> OPTIONAL presentation/profile layer only, never authority
scientific-agent-skills     -> CATALOG/CANDIDATE; load specialized skills only on demand
```

## V1 SCAFFOLD state (this commit)

- Router scaffold exists (returns empty list on no candidates — canonical behavior preserved).
- Registry schema defined; loader accepts a YAML file with validation per intake gates.
- Conflict resolver implements rule 1 (canonical Factory wins) deterministically.
- Graph adapter is a stub that raises `NotImplementedError` until SHADOW canary activates it.
- Zero external skills registered yet (all 10 candidates awaiting G0 audit evidence).
- Zero runtime / config / secrets / gateway mutations introduced.

The next safe gate is G0 evidence ingestion from the 10 upstream repos, which must land before any candidate can leave `CANDIDATE` state.

## Definition of done (V1)

```text
EXTERNAL_SKILL_REGISTRY        = PASS
PINNED_PROVENANCE              = PASS
LICENSE_GATE                   = PASS
SUPPLY_CHAIN_GATE              = PASS
TASK_SCOPED_ROUTER             = PASS
PROGRESSIVE_DISCOVERY          = PASS
CANONICAL_AUTHORITY_PRECEDENCE = PASS
CONFLICT_RESOLUTION            = PASS
CATALOG_NO_AUTO_INSTALL        = PASS
GRAPH_READ_ONLY                = PASS
NO_SECOND_KB                   = PASS
NO_VECTOR_DB                   = PASS
NO_PRODUCT_MUTATION            = PASS
LIVE_SHADOW_CANARIES           = PASS
FULL_REGRESSION                = PASS
ADVERSARIAL                    = PASS
ROLLBACK                       = VERIFIED
GLOBAL_RUNTIME_MUTATED         = NO
SECRETS_CONFIG_MUTATED         = NO
```

A skill cannot be declared `ACTIVE` until every gate above is PASS for that skill's row.
