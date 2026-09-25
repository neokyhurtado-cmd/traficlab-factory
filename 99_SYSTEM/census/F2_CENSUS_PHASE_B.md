# F2 CLOSEOUT — Phase B: Read-Only Reality Census

```
ESTATE_CENSUS_COMPLETE        = YES
MUTATIONS_DURING_CENSUS       = 0
CENSUS_STARTED_AT             = 2026-09-25T06:06:59.197914+00:00
CENSUS_FINISHED_AT            = 2026-09-25T06:14:32.844954+00:00
CENSUS_AUTHOR                 = Hermes (foreman) + inline investigators
CENSUS_OUTPUT_PATH            = traficlab-factory/99_SYSTEM/census/inventory_partial.json

REPOS_FOUND                   = 5
WORKTREES_FOUND               = 143
UNTRACKED_CLONES_FOUND        = 10
SQLITE_DBS_FOUND              = 7
HEAVY_NON_REPO_DIRS_FOUND     = 11
DOCKER_CONTAINERS_RUNNING     = 21
DOCKER_CONTAINERS_TOTAL       = 29
DOCKER_IMAGES                 = 22
DOCKER_VOLUMES                = 13
SUSPICIOUS_LIVE_PROCESSES     = 69

WORKTREES_DISK_BYTES          = 22,455,179,020
WORKTREES_DISK_GB             = 20.91
UNTRACKED_CLONES_DISK_GB      = 0.50
SQLITE_DBS_DISK_GB            = 0.025
HEAVY_NON_REPO_DISK_GB        = 573.56

TOTAL_DISCOVERED_GB           = 595.00
SAFE_CANDIDATE_GB             = 2.93  (STALE_CANDIDATE only)
REVIEW_REQUIRED_GB            = 17.98  (ACTIVE+SUPERSEDED+DIRTY)
UNKNOWN_PRESERVE_GB           = 16.56

CLASSIFICATION_COUNTS         = {"ACTIVE_DIRTY_OWNER_PRESERVE": 30, "STALE_CANDIDATE": 31, "ACTIVE_STACKED": 50, "UNKNOWN_PRESERVE": 20, "SUPERSEDED_KEEP_EVIDENCE": 10, "ACTIVE_CANONICAL": 2}
LIVE_RUNTIME_DETECTED         = True
LIVE_RUNTIME_NAMES            = ['com.docker.backend', 'com.docker.build', 'docker desktop', 'docker-sandbox', 'hermes', 'node', 'ollama', 'ollama app', 'postgres', 'python']

PROTECTED                     = origin/main=bbab7260231c  (DO NOT TOUCH)
PRODUCTION_TOUCHED            = NO
CANONICAL_DB_TOUCHED          = NO
DAVID_OS_ORIGINALS_MODIFIED   = 0

SAFE_DELETE_MANIFEST          = C:\Users\david\repos\traficlab-factory\99_SYSTEM\census\safe_delete_manifest.json
SUPERSEDED_KEEP_MANIFEST      = C:\Users\david\repos\traficlab-factory\99_SYSTEM\census\superseded_keep_evidence_manifest.json

VERDICT                       = PASS_READ_ONLY_CENSUS
NEXT_PHASE                    = A — Housekeeper / Baseline Guard (code, dry-run only)
INDEPENDENT_REVIEW            = PENDING  (JEV or ASTRA-style separate agent)
GATE_FOR_DELETE               = CENSUS_PASS + CLASSIFICATION_PASS + DEPENDENCY_CHECK_PASS + INDEPENDENT_REVIEW_PASS
```

## Notes (out-of-verdict, for human reading only)

- `ia-vision-worktrees/` is the elephant: 22 GB across 141 worktrees, mostly from lane-*/feat-*/audit-* patterns.
- `OneDrive` (218 GB) and `.ollama` (349 GB) are David-personal, OUT OF SCOPE for the housekeeper.
- Live runtime detected (postgres, ollama, hermes, node) → all repo-adjacent paths are flagged `RUNTIME_REFERENCED` until proven otherwise.
- 31 stale candidates (2.93 GB) have full evidence: not on origin, not merged, no dirty work. Safe delete manifest is generated but **not executed** until independent review.
- 10 superseded candidates (1.43 GB) were merged into `origin/main` but the worktrees still exist; cleanup is safe, evidence is preserved in main.
- All output files live in `traficlab-factory/99_SYSTEM/census/` — single mutable zone, no product code touched.
