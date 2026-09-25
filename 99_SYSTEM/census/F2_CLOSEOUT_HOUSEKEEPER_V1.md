# F2 CLOSEOUT — REALITY-FIRST HOUSEKEEPER / BASELINE GUARD

## Carrier (durable anchor)

```
DURABLE_GITHUB_ISSUE    = neokyhurtado-cmd/traficlab-factory#56
DURABLE_GITHUB_COMMENT  = https://github.com/neokyhurtado-cmd/traficlab-factory/issues/56#issuecomment-5827811183
DURABLE_GITHUB_PR       = https://github.com/neokyhurtado-cmd/traficlab-factory/pull/55
BRANCH                  = feat/housekeeper-baseline-guard-v1
HEAD_SHA                = 32cf590
BASE_SHA                = 2cbc4b2  (origin/main, JEV-merged)
```

## Reality correction (verified)

```
EXISTS_tools/baseline_guard.py             = NO
EXISTS_99_SYSTEM/baselines/BASELINE_REGISTRY.json = NO
EXISTS_housekeeper_evidence/               = NO
EXISTS_WORKTREE_GARBAGE_CHECK.md           = NO
EXISTS_GITHUB_COMMENT_5827172808           = NO  (404 on real repo)
TREATED_AS_PHANTOM                        = YES (no repair attempted)
```

## Phase B — Read-Only Reality Census

```
ESTATE_CENSUS_COMPLETE       = YES
MUTATIONS_DURING_CENSUS      = 0
REPOS_FOUND                  = 5
WORKTREES_FOUND              = 141
UNTRACKED_CLONES_FOUND       = 10
SQLITE_DBS_FOUND             = 7
HEAVY_NON_REPO_DIRS_FOUND    = 11
DOCKER_CONTAINERS_RUNNING    = 21
DOCKER_CONTAINERS_TOTAL      = 29
DOCKER_IMAGES                = 22
DOCKER_VOLUMES               = 13
SUSPICIOUS_LIVE_PROCESSES    = 69
TOTAL_DISCOVERED_GB          = 595.00
SAFE_CANDIDATE_GB            =   2.93   (NOT executed)
REVIEW_REQUIRED_GB           =  18.49
UNKNOWN_PRESERVE_GB          =   0.78
CLASSIFICATION_ACTIVE_DIRTY  =  30
CLASSIFICATION_ACTIVE_STACKED=  50
CLASSIFICATION_STALE         =  31
CLASSIFICATION_SUPERSEDED    =  10
CLASSIFICATION_UNKNOWN       =  20
CLASSIFICATION_CANONICAL     =   2
```

## Phase A — Housekeeper code

```
HOUSEKEEPER_PATH             = traficlab-factory/99_SYSTEM/housekeeper/housekeeper.py
TESTS_PATH                   = traficlab-factory/99_SYSTEM/housekeeper/tests/
TESTS_PASSING                = 7 / 7
GC_DRY_RUN_REFUSES_LIVE      = YES  (exit 2 verified)
DELETE_REFUSES_NO_REVIEW     = YES  (exit 1 verified)
CLASSIFIES_MAIN_CANONICAL    = YES  (verified by test)
CLASSIFIES_DIRTY_PRESERVE    = YES  (verified by test)
PROTECTS_PROTECTED_PATTERNS  = YES  (feat/jupiter, feat/wo, feat/visor, release/*)
PROTECTED                    = origin/main = bbab726
PRODUCTION_TOUCHED           = NO
CANONICAL_DB_TOUCHED         = NO
DAVID_OS_ORIGINALS_MODIFIED  = 0
ONE_MUTABLE_ZONE             = traficlab-factory/99_SYSTEM/
```

## Gate for actual deletion

```
DELETE_GATE_REQUIRED = CENSUS_PASS + CLASSIFICATION_PASS + DEPENDENCY_CHECK_PASS + INDEPENDENT_REVIEW_PASS
DELETE_GATE_CURRENT  = CENSUS_PASS + CLASSIFICATION_PASS + DEPENDENCY_CHECK_PENDING + INDEPENDENT_REVIEW_PENDING
DELETE_EXECUTED      = NO
```

## Verdict

```
VERDICT = PASS_READ_ONLY_CENSUS + PASS_HOUSEKEEPER_SCAFFOLDING
OWNER_GATE = REQUIRED  (for: independent review + safe-delete execution)
NEXT = independent review of the 31-candidate manifest by a separate agent (JEV/ASTRA-style)
```

## Files added (all in `traficlab-factory/99_SYSTEM/`)

- `census/inventory_partial.json`
- `census/inventory_housekeeper.json` (reclassified by housekeeper tool)
- `census/inventory_trimmed.json`
- `census/safe_delete_manifest.json` (31 candidates, NOT executed)
- `census/superseded_keep_evidence_manifest.json`
- `census/F2_CENSUS_PHASE_B.md`
- `census/README.md`
- `census/GITHUB_CARRIER.md`
- `housekeeper/housekeeper.py`
- `housekeeper/README.md`
- `housekeeper/tests/test_housekeeper.py`
