# Operating Protocol

Before editing, synchronize with remote. After editing, review the diff, commit by project scope, reconcile remote changes and publish.

Roles:
- David: authority and material decisions.
- Astra: architecture, audit and cross-project synthesis.
- Hermes ORCH: inventory, routing, automation and maintenance.
- Product agents: write only inside assigned ownership.

Every new project receives a Mission Control node at creation time.

Current SHA, PR status, runtime health, test results and active ownership must be refreshed from their authoritative source. A stale note cannot override GitHub or runtime evidence.

When two computers produce incompatible semantic decisions, preserve both and mark `NEEDS_RECONCILIATION`. Do not choose silently.

Hermes may generate indexes, backlinks, inventories and freshness reports. It may not invent an unresolved human decision just to make the graph consistent.
