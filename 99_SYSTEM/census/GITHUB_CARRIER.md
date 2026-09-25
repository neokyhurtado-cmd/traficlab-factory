## Housekeeper / Baseline Guard — Phase B + Phase A complete (read-only, dry-run only)

**Branch:** `feat/housekeeper-baseline-guard-v1` @ `1ad712e` in `neokyhurtado-cmd/traficlab-factory`
**Commit:** `1ad712e feat(housekeeper): reality-first census + dry-run-only worktree classifier`

### Reality correction (verified before building)

The directive referenced these as existing — **none exist on disk**:

- `tools/baseline_guard.py` — ❌ not found
- `99_SYSTEM/baselines/BASELINE_REGISTRY.json` — ❌ not found
- `housekeeper_evidence/` — ❌ not found
- `WORKTREE_GARBAGE_CHECK.md` — ❌ not found
- GitHub comment `5827172808` — ❌ 404 (and the repo isn't `davidgomezcol/ia-vision`; the canonical is `neokyhurtado-cmd/IA-VISION`)

So I did **not** try to repair any of them. Built from observed reality only.

### Phase B — Reality Census (READ-ONLY, MUTATIONS=0)

```
REPOS_FOUND                    = 5
WORKTREES_FOUND                = 141
UNTRACKED_CLONES_FOUND         = 10
SQLITE_DBS_FOUND               = 7
DOCKER_CONTAINERS_RUNNING      = 21
DOCKER_IMAGES                  = 22
DOCKER_VOLUMES                 = 13
SUSPICIOUS_LIVE_PROCESSES      = 69  (postgres, ollama, hermes, node)

WORKTREES_DISK_GB              = 20.91
UNTRACKED_CLONES_DISK_GB       =  0.50
SQLITE_DBS_DISK_GB             =  0.02
HEAVY_NON_REPO_DISK_GB         = 573.56  (OneDrive 218 + ollama 349 — David-personal, OUT OF SCOPE)

TOTAL_DISCOVERED_GB            = 595.00
SAFE_CANDIDATE_GB              =   2.93  (STALE_CANDIDATE only — NOT EXECUTED)
REVIEW_REQUIRED_GB             =  18.49
UNKNOWN_PRESERVE_GB            =   0.78

CLASSIFICATION_COUNTS:
  ACTIVE_DIRTY_OWNER_PRESERVE  =  30  (~ 4.32 GB)
  ACTIVE_STACKED               =  50  (~11.41 GB)
  STALE_CANDIDATE              =  31  (~ 2.93 GB)
  SUPERSEDED_KEEP_EVIDENCE     =  10  (~ 1.43 GB)
  UNKNOWN_PRESERVE             =  20  (~ 0.78 GB)
  ACTIVE_CANONICAL             =   2  (~ 0.03 GB)

PROTECTED                      = origin/main = bbab726 (DO NOT TOUCH)
PRODUCTION_TOUCHED             = NO
CANONICAL_DB_TOUCHED           = NO
DAVID_OS_ORIGINALS_MODIFIED    = 0

VERDICT                        = PASS_READ_ONLY_CENSUS
```

### Phase A — Housekeeper code (built on real evidence)

`traficlab-factory/99_SYSTEM/housekeeper/housekeeper.py`:

- **Read-only-first, dry-run-default.** `gc --dry-run` refuses while live runtime is detected (verified — exit 2).
- **`delete` refuses without `--i-have-reviewed`** (verified — exit 1).
- **UNKNOWN → PRESERVE** default.
- **One mutable zone:** `traficlab-factory/99_SYSTEM/housekeeper/`. Never touches product code.
- **7/7 unit tests passing** (`pytest 99_SYSTEM/housekeeper/tests/`).

### What I did NOT do (deliberately)

- Did not delete anything.
- Did not `git clean`, `git gc`, `git remote prune`, `docker system prune`, or `rm` anything.
- Did not touch `origin/main` (`bbab726`).
- Did not touch `IA-VISION :7921` production.
- Did not touch any DB or Docker volume.
- Did not auto-execute the safe-delete manifest. It is emitted as `safe_delete_manifest.json` for review.

### Gate for actual deletion

Delete only happens when ALL of these pass:

```
CENSUS_PASS  +  CLASSIFICATION_PASS  +  DEPENDENCY_CHECK_PASS  +  INDEPENDENT_REVIEW_PASS
```

**No `delete --i-have-reviewed` will run** until a separate reviewer (JEV or ASTRA-style agent) confirms the 31-candidate manifest is honest (no false stale, no hidden refs, no live DBs, no active PRs on those branches).

### Files added (all in `99_SYSTEM/`)

```
census/inventory_partial.json              # full machine-readable inventory
census/safe_delete_manifest.json           # 31 candidates with full evidence
census/superseded_keep_evidence_manifest.json  # 10 already-merged worktrees
census/F2_CENSUS_PHASE_B.md                # formal F2 closeout
census/README.md                           # human summary
housekeeper/housekeeper.py                 # the tool
housekeeper/README.md
housekeeper/tests/test_housekeeper.py      # 7 tests
```

### Suggested next decision (your call)

Three options, none of them auto-run:

1. **Open the PR** (`feat/housekeeper-baseline-guard-v1` → `main`) and trigger independent review (JEV).
2. **Stop here** — keep the census as evidence, defer the housekeeper PR until we have reviewed the 31 candidates manually.
3. **Extend the census** with Docker volume mount mapping, per-worktree remote-merge check beyond IA-VISION, and a real handle.exe-based live-path scan.

I will continue autonomously toward option (1) unless you say otherwise.
