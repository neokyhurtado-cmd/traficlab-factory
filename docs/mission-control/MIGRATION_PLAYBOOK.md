# Migration Playbook

Migration is non-destructive and starts read-only.

1. Inventory every discovered vault, note tree, project folder and external storage root.
2. Classify each item as `CANONICAL_KNOWLEDGE`, `PROJECT_KNOWLEDGE`, `EXTERNAL_FILE`, `DUPLICATE_CANDIDATE`, `ARCHIVE_CANDIDATE`, `GENERATED` or `UNKNOWN`.
3. Build a deduplication report before moving anything.
4. Create project nodes in the private master vault.
5. Import clear Markdown knowledge first.
6. Represent heavy/external files by pointer records unless there is a reason to version them directly.
7. Keep original locations intact until acceptance.
8. Bootstrap PC-A, then PC-B, from the same private remote.
9. Run a normal sync canary and an intentional same-note conflict canary.
10. Only after both pass, mark old vaults `LEGACY_READ_ONLY`; cleanup is a separate decision.

Never treat file count equality as proof of semantic equivalence. Migration closes only when important decisions, inventories and project identities are traceable in the master vault.
