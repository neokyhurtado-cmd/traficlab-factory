# Templates

## PROJECT.md

```yaml
---
type: project
project: PROJECT_NAME
repo: owner/repo
owner: OWNER
agent: AGENT
status_source: GITHUB_OR_RUNTIME
related: []
---
```

Required sections: Mission, Scope, Out of Scope, Authoritative Sources, Related Projects, Current Goal, Storage Classes and Open Questions.

## Pointer record

```yaml
---
type: external-file
project: PROJECT_NAME
storage_class: external
location_alias: HUMAN_READABLE_ALIAS
provenance: SOURCE
verified_at: YYYY-MM-DD
---
```

## Decision record

```yaml
---
type: decision
project: PROJECT_NAME
decision_id: DEC-YYYY-NNN
status: PROPOSED|APPROVED|SUPERSEDED
owner: OWNER
---
```

Required sections: Context, Decision, Alternatives, Evidence, Consequences and Supersedes.

## Research record

Always separate `OBSERVED`, `INFERRED`, `PROPOSED` and `UNKNOWN`. A research note must link the project or projects it affects.
