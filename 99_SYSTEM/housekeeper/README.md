# Housekeeper / Baseline Guard — `99_SYSTEM/housekeeper`

Built from observed reality, not from a planned-but-missing infrastructure.

## What this is

A read-only-first, dry-run-default tool for the IA-VISION / TrafficLab
ecosystem. Discovers worktrees, classifies them with **real evidence** (origin
existence, merge into `origin/main`, dirty state, live runtime), and emits a
`SAFE_DELETE_MANIFEST` — without deleting anything.

The Baseline Guard piece (later) will block new experiments that try to create
indistinguishable or provenance-less baselines.

## Policy (hardcoded)

1. **UNKNOWN → PRESERVE.** Default unsafe.
2. **`gc` is always `--dry-run`** unless you call `delete --i-have-reviewed`.
3. **`delete` refuses while live runtime detected** (postgres, ollama, hermes,
   node, jupyter).
4. **Memory is CONTEXT, not AUTHORITY.** We never trust `MEMORY.md` for delete
   decisions. Trust: origin/main, live filesystem, durable GitHub evidence.
5. **One mutable zone.** This script only writes inside
   `traficlab-factory/99_SYSTEM/housekeeper/`. Never touches product code.

## Subcommands

```
python 99_SYSTEM/housekeeper/housekeeper.py scan \
    --repo C:/Users/david/repos/IA-VISION \
    --out 99_SYSTEM/census/inventory.json

python 99_SYSTEM/housekeeper/housekeeper.py gc --dry-run \
    --input 99_SYSTEM/census/inventory.json \
    --output 99_SYSTEM/census/safe_delete_manifest.json

python 99_SYSTEM/housekeeper/housekeeper.py verify \
    --manifest 99_SYSTEM/census/safe_delete_manifest.json

python 99_SYSTEM/housekeeper/housekeeper.py delete \
    --manifest 99_SYSTEM/census/safe_delete_manifest.json \
    --i-have-reviewed
```

## Classification tree

```
ACTIVE_CANONICAL              main/master
ACTIVE_STACKED                matches feat/jupiter, feat/wo, feat/visor, feat/evidence, release/*
ACTIVE_DIRTY_OWNER_PRESERVE   dirty_files > 0
SUPERSEDED_KEEP_EVIDENCE      branch merged into origin/main; evidence is in main
ACTIVE_STACKED (open)         branch exists on origin, not merged
STALE_CANDIDATE               not on origin, not merged, not dirty, not protected
UNKNOWN_PRESERVE              detached HEAD / no branch / no remote info
```

## Tests

```
python -m pytest 99_SYSTEM/housekeeper/tests/ -v
```

## What this is NOT

- Not a replacement for `git gc` or `git worktree prune`. Use those separately.
- Not an autoremove tool. The first version NEVER deletes without an explicit
  manifest + `--i-have-reviewed`.
- Not authoritative over `MEMORY.md`. The Baseline Guard uses the live
  filesystem and GitHub as the source of truth.
