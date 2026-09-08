# Authority Hierarchy

## Highest to lowest

```
GitHub remote       = hechos, SHAs, PRs, branches, merges, issues
.hermes/control-plane/ = operación/ownership en tiempo real
PROJECT_STATE / WORKLOG / docs = estado documental de producto
Obsidian            = conocimiento, arquitectura, decisiones, investigación
Chat                = transporte temporal, NO autoridad durable
```

## Product ownership

```
HERMES-ORCH  → TRAFFICLABPRO_CONTROL
HERMES-IA    → IA-VISION
HERMES-SUINI → SUINI
```

## Cross-product rule

```
if target_product != assigned_product:
  STOP
  PRODUCT_OWNERSHIP_MISMATCH
  RETURN_TO_ORCHESTRATOR
```
