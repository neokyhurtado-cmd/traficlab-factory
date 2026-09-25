# SAFE_DELETE_MANIFEST — Final, reviewer-passed

**Manifest ID:** `SAFE_DELETE_MANIFEST_20260925_015424`
**Generated:** 2026-09-25T06:54:24.992740+00:00
**Review packet:** `C:\Users\david\repos\traficlab-factory\99_SYSTEM\census\state\callbacks\ASTRA_REAUDIT_HOUSEKEEPER_V1_20260925_015351.json`
**Review verdict:** `PASS_TRULY_STALE`

## What this is

A manifest of worktrees that an independent reviewer (ASTRA-style) verified as **safe to delete**.
It is NOT auto-executed. `housekeeper delete --i-have-reviewed` still requires your explicit go.

## Summary

- **Total candidates:** 23
- **Total recoverable space:** **1.811 GB**
- **Review method:** independent re-verification against git origin, gh pr list, git log, merge-base, dirty-check
- **Mutations during census + review:** 0

## Candidates (full path list)

- `C:/c/c/c/Users/david/repos/corrective-closeout/baseline-check` (0.012 GB, sha=53554d72e2e7)
- `C:/c/c/Users/david/repos/corrective-closeout/feat-pedestrian-v1.0.1-a4-clarify` (0.012 GB, sha=53554d72e2e7)
- `C:/c/c/Users/david/repos/IA-VISION-cert-read` (0.0124 GB, sha=e90ec1ff7464)
- `C:/c/c/Users/david/repos/IA-VISION-docs` (0.0124 GB, sha=3fa6e107ef13)
- `C:/c/c/Users/david/repos/IA-VISION-docs-ps` (0.0124 GB, sha=6f805de26e0d)
- `C:/c/c/Users/david/repos/IA-VISION-product-fix` (0.0279 GB, sha=6c12fec741b2)
- `C:/c/Users/david/repos/corrective-closeout/feat-combined-closeout` (0.0126 GB, sha=51dc9252db0a)
- `C:/c/Users/david/repos/IA-VISION-pr109` (0.0126 GB, sha=52bfb93810ad)
- `C:/c/Users/david/repos/M591-sidecar-inspect` (0.1083 GB, sha=0ee5ff417fd9)
- `C:/c/x/00_PROYECTOS/IA-VISION.worktrees/rt4a-evidence-orthomosaic` (0.0195 GB, sha=777c2363ef75)
- `C:/Users/david/orca/workspaces/IA-VISION/h2-canonical-fresh-from-b723202` (0.1387 GB, sha=b723202528aa)
- `C:/Users/david/orca/workspaces/IA-VISION/test-orca-h3-cursor` (0.1387 GB, sha=b723202528aa)
- `C:/Users/david/repos/IA-VISION-cert-template` (0.0124 GB, sha=ce4cc2364eca)
- `C:/Users/david/repos/IA-VISION-g5sha37` (0.0299 GB, sha=0955f87d333a)
- `C:/Users/david/repos/IA-VISION.worktrees/owner-view-v1` (0.139 GB, sha=85756284e0fb)
- `C:/Users/david/repos/IA-VISION.worktrees/pr-v2a-layer-inspector` (0.1391 GB, sha=bc627eb49e46)
- `C:/Users/david/repos/IA-VISION.worktrees/pr-v2b-click-select` (0.1391 GB, sha=3d78a5307bf3)
- `C:/Users/david/repos/IA-VISION.worktrees/pr-v3a-trayectorias` (0.1387 GB, sha=195d89a3578d)
- `C:/Users/david/repos/IA-VISION.worktrees/pr-v3b-trayectorias-toggle` (0.1387 GB, sha=b47271a061bd)
- `C:/Users/david/repos/IA-VISION.worktrees/pr-v4a-gates-aforos` (0.1387 GB, sha=732ee5affef4)
- `C:/Users/david/repos/IA-VISION.worktrees/pr-v5-kpi-tracks` (0.1387 GB, sha=6e8fdadd364d)
- `C:/Users/david/repos/IA-VISION.worktrees/pr-v5b-gate-listener` (0.1387 GB, sha=55ba686eba9a)
- `C:/Users/david/repos/IA-VISION.worktrees/pr-v6-timeline-events` (0.1388 GB, sha=8f610501f3fb)

## Rollback

- `git worktree remove --force` does NOT delete git refs.
- Refs and commits remain reachable via reflog for 90+ days.
- Recovery: `git worktree add <path> <branch>`.

## Out of scope (deliberately not in this manifest)

- `IA-VISION :7921` production runtime
- `origin/main = bbab726` (DO NOT TOUCH)
- Canonical DBs (production)
- Live Docker volumes
- `DAVID_OS` originals
- 30 ACTIVE_DIRTY_OWNER_PRESERVE worktrees (your active work)
- 10 SUPERSEDED_KEEP_EVIDENCE worktrees (kept as evidence per ASTRA)

## Next step

Run ON YOUR EXPLICIT GO:

```
python 99_SYSTEM/housekeeper/housekeeper.py delete \
    --manifest C:\Users\david\repos\traficlab-factory\99_SYSTEM\census\SAFE_DELETE_MANIFEST_20260925_015424.json \
    --i-have-reviewed
```

If you prefer not to delete, just close the carrier issue and the manifest stays as evidence.