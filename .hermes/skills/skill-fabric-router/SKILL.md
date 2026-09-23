---
name: skill-fabric-router
description: Task-scoped skill router for the TraficLab Factory Skill Fabric. Use when a Hermes worker wants to know which external skills apply to the current task without loading every skill in the registry.
version: 1.0.0
metadata:
  hermes:
    tags: [skills, fabric, router, registry, progressive-discovery]
---

# Skill Fabric Router

The Skill Fabric Router resolves a free-text task intent to the smallest relevant subset of skills from `.hermes/skills-registry/skills.yaml`. It is the task-scoped gate referenced in the SKILL FABRIC V1 macrogoal (issue neokyhurtado-cmd/traficlab-factory#51), sections **C** (task-scoped router) and **G2** (progressive discovery).

## Why this exists

Without a router, a fresh worker loads every registered skill on every prompt. The macrogoal rejects that pattern. The Router returns either:

- a small ordered list of skill ids that match the intent, or
- the empty list (meaning "fall back to canonical Factory behavior").

Loading the empty list is the right answer for the overwhelming majority of tasks. The router is intentionally conservative.

## Procedure

### 1. Read the registry, not the upstream

```python
from agent_body.skill_registry import load_registry, resolve_skill_router
reg = load_registry()  # default path: .hermes/skills-registry/skills.yaml
```

### 2. Resolve with intent + project

```python
paths = resolve_skill_router(
    intent=prompt_text,
    registry=reg,
    project="neokyhurtado-cmd/traficlab-factory",
    intent_keywords=None,        # optional; caller can boost specific ids
)
```

`project` is the durable authority pointer. If the project is not in an entry's `allowed_projects`, the entry is HARD-EXCLUDED.

### 3. Confirm registry validity before routing

`resolve_skill_router` does NOT validate entries. Run `validate_registry(reg)` first when:

- a fork may have edited `skills.yaml`, or
- upstream SHAs may have drifted.

```python
from agent_body.skill_registry import validate_registry
result = validate_registry(reg)
if result.any_failures:
    return [{"id": k, "errors": v} for k, v in result.fail_messages.items()]
```

### 4. Honor activation_scope

| Activation scope | Behavior |
|---|---|
| `task-scoped` | Load on router hit |
| `per-subskill-on-demand` | Router returns the parent id; load subskills on demand |
| `read-only-derived-adapter` | Load on router hit; consumer treats output as derived cache |
| `cataloged-only` | Reference material; router surfaces ONLY when caller supplies explicit `intent_keywords` |
| `cataloged-discovery-feed` | Discovery role; never loads as a skill itself |

### 5. Conflict preflight

Before activating two skills simultaneously, run:

```python
from agent_body.skill_registry import detect_authority_conflicts
chosen = [reg.by_id(sid) for sid in paths if reg.by_id(sid)]
conflicts = detect_authority_conflicts(chosen)
if conflicts:
    return {"status": "CONFLICT", "surfaces": conflicts}
```

Authority-keyword flagging is conservative: the analyzer surfaces intent evidence. The orchestrator decides whether the evidence is real.

### 6. Rollback discipline

Every active entry declares `rollback.disable_command`. Record the chosen skills and their disable commands in the task checkpoint so rollback is a single command per skill.

## Pitfalls

- Do NOT inject the entire registry into the worker's prompt. The router returns an ordered list, not the bodies.
- Do NOT auto-activate any skill whose mode is `CATALOG`. Catalog is reference-only.
- Do NOT promote a `SHADOW` entry to `ACTIVE` based on routing alone — the macrogoal gate **G4 (live shadow canary)** is required first.
- Do NOT cache router output across sessions: the registry can be edited in PRs; always reload.
- Do NOT bypass the validation gate on confidence. Even local-only checkout is fine, but the validator must run.

## Cross-references

- `.hermes/skills-registry/skills.yaml` — the canonical registry.
- `agent_body/skill_registry.py` — module + public surface.
- `agent_body/skill_discovery.py` — repo-local skill discovery (older).
- `policies/skill-fabric-intake.md` — intake policy.
- `policies/license-gate.md` — license gate.
- `policies/no-go-boundaries.md` — the 14 hard no-go constants.
- `audits/` — G0 upstream-audit reports (one per candidate repo).
