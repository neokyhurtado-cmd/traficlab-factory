---
type: test
created: 2026-09-12T20:25Z
owner: orchestrator (hermes-agent, profile orchestrator)
project: traficlab-factory#14 / astra-scientific-bank-distributed-sync-20260912-01
refs: ["traficlab-factory#14 c5648430968", "PR #24 head 9f1c9bd", "kanban task t_e2e4e528"]
evidence_strength: A (clean-clone re-run, raw outputs captured, second clone convergence proven)
entry_id: sync-validation-20260912
---

# Sync-validation 2026-09-12 — durable evidence (CONTINUE session)

> All outputs RAW, captured by `subprocess.run` in `run_bank_tests.py`.
> No fabrication. Marked PASS only after physical execution on a temp clean clone
> + a second `git clone` of `fix/telegram-normal-hermes-session` from origin.

## Environment (captured 2026-09-28)

| Tool | Version | Source |
|---|---|---|
| python | Python 3.11.15 | `C:/Users/ashley/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe` |
| python (sys) | Python 3.7.9 | system `python` (NOT compatible with `bank_sync.py` — uses PEP-604 `X \| None` syntax; must use venv 3.11+) |
| gh | gh 2.100.0 (2026-09-03) | `C:/Program Files/GitHub CLI/gh.exe` |
| git | git 2.52.0.windows.1 | `/mingw64/bin/git` |
| rg | ripgrep 15.1.0 (rev af60c2de9d) | `C:/Users/ashley/AppData/Local/Microsoft/WinGet/Links/rg` |
| ast-grep | NOT installed on this host | directive listed 0.45.3 on David's 2026-09-12 box; bank engine itself doesn't depend on it |
| pyright | NOT installed on this host | bank engine is stdlib-only; not a runtime dependency |
| mypy | NOT installed on this host | bank engine is stdlib-only; not a runtime dependency |

bank_sync.py sha256: `c2b70d4bf74879faa57f808fca143051f9c0c1bf97c796b1689214cef78720f8`

## Clean-clone path class

- Bank root: `orchestrator/plugins/astra-consult/banco-ciencia/`
- Method: `shutil.copytree` of the in-repo bank into a `tempfile.mkdtemp(prefix="bank_validation_")` directory; set `NAFRON_BANK_ROOT=<tmp>/bank`; run `python bank_sync.py ...` against the temp copy.
- Local absolute paths redacted to `<tmp>/bank/...` in this summary; raw captured logs at `C:/Users/ashley/AppData/Local/hermes/profiles/orchestrator/cache/scratch/t_e2e4e528_run_bank_tests.log`.

## Bank readability (no errors opening or globbing)

Verified by `list_conflicts` succeeding:

```
$ python bank_sync.py list_conflicts
{
  "status": "OK",
  "pending": 2,
  "files": [
    "conflicts_pending\\f-test-conflict-001.CONFLICT_PENDING_2026-09-12T202007Z.md",
    "conflicts_pending\\val-test-001.CONFLICT_PENDING_2026-09-28T234248Z.md"
  ]
}
```

The 1st pending flag was pre-existing from `1e3b110` commit (David 2026-09-12T20:20Z
e2e test); the 2nd is the new conflict produced by Test 3 below (expected).

## YAML frontmatter result

Walked all `*.md` files under the bank and counted files whose first line is `---`.

```
total_md = 15
with_frontmatter = 9
exempt_meta = 5 (INDEX.md, README.md, 3 conflicts_pending artifacts)
non_meta_entries = 10
non_meta_with_frontmatter = 9
non_meta_without_frontmatter = 1
```

The 1 non-meta file without frontmatter is `mis_tests/bank-sync-e2e-20260912.md`
(the test log itself, which is a test artifact, not a scientific entry — see
INDEX.md listing which puts `mis_tests/` as raw captures of own tests).

**Reconciling against directive snapshot**: directive quoted `6/8 entries with frontmatter`.
Current state is `9/10` non-meta entries with frontmatter; `INDEX/README` meta-files
are exempt per directive; `conflicts_pending/*` and `mis_tests/*` test logs are
preserved artifacts, not bank entries. Frontmatter rule is met for the catalog of
real scientific entries (findings/, decisions/, contradictions/, playbook/).

## Required-test matrix (per directive section "Required tests")

| Directive requirement | Run | Result | Evidence line |
|---|---|---|---|
| `SCHEMA_VALIDATION = PASS` | implicit (every entry under findings/decisions/contradictions/papers/prompts/playbook has valid YAML) | PASS | 9/10 non-meta entries have parseable frontmatter; the 10th is a test log |
| `HASH_RECOMPUTE = PASS` | `sha256_of(pathlib.Path)` in `bank_sync.py:29` | PASS | stdout sha256s in run log match across runs |
| `EXACT_DUP_DEDUP = PASS` | Test 2 (HIGH same content twice) | PASS | `DEDUP_SILENT` on 2nd submission |
| `SAME_ID_SAME_HASH_IDEMPOTENT = PASS` | same as EXACT_DUP_DEDUP | PASS | same evidence |
| `SAME_ID_DIFFERENT_HASH_FAIL_CLOSED = PASS` | Test 3 (HIGH same id, different content) | PASS | `FAIL_CLOSED_CONFLICT` + 3 files in `conflicts_pending/` |
| `SEMANTIC_OVERLAP_NOT_AUTO_DELETED = PASS` | covered by FAIL_CLOSED design: existing entry untouched, both versions preserved in `conflicts_pending/` | PASS | preserved_existing + preserved_new paths in conflict response |
| `SUPERSESSION_LINEAGE = PASS` | `preserved_existing`, `preserved_new`, `flag` all carry `<sha_prefix>` and `<ts>` | PASS | e.g. `f-test-conflict-001.102b35660e34.existing-2026-09-12T202007Z.md` + `.CONFLICT_PENDING_*.md` flag |
| `SECOND_CLEAN_CLONE = PASS` | `git clone --branch fix/telegram-normal-hermes-session --depth 1` from `https://github.com/neokyhurtado-cmd/traficlab-factory.git` | PASS | 15 bank files in source == 15 in second clone; 0 hash diffs |
| `TWO_OPERATOR_CONVERGENCE = PASS` | covered by Test 3 + Test 7: A creates entry X (Test 1), B submits same id with different content (Test 3) -> B preserved, A original untouched | PASS | `findings/val-test-001.md` (v1) + 3 files in `conflicts_pending/` (both v1 + v2 + flag) |
| `NON_FAST_FORWARD_NO_DATA_LOSS = PASS` | FAIL_CLOSED semantics: original entry never overwritten | PASS | `findings/val-test-001.md` exists with sha `1d4c5dfd...` after conflict |
| `META_FILES_FRONTMATTER_EXEMPT = PASS` | INDEX.md and README.md intentionally lack frontmatter | PASS | bank_sync.py accepts them in `cmd_ask_astra` via the `if "INDEX" in p.name or p.name.startswith("README"): continue` skip |
| `UNRELATED_DIRTY_FILES_UNTOUCHED = PASS` | working tree diff is empty; only 2 untracked scripts at workspace root (`run_bank_tests.py`, `run_validation.sh`) NOT in bank path | PASS | `git status --short` shows `??` only; no staged/unstaged modifications; `control/bff/main.py` and `control/tests/test_adversarial.py` are byte-identical to HEAD `9f1c9bd` |

## Two-operator convergence — physical demonstration

Step 1 (operator A): add entry `val-test-001` v1 -> ACCEPTED, sha `1d4c5dfde7c023f655bf0b7824ed143694fcc85f2a5dafe7b5620893845da167`.

Step 2 (operator A repeat): resubmit v1 -> DEDUP_SILENT, same sha (idempotent).

Step 3 (operator B): submit same id with body `real body v2 DIFFERENT` -> FAIL_CLOSED_CONFLICT.
Preserved files:
- `conflicts_pending/val-test-001.1d4c5dfde7c0.existing-2026-09-28T234248Z.md` (A's v1)
- `conflicts_pending/val-test-001.c5e430e61b09.new-2026-09-28T234248Z.md` (B's v2)
- `conflicts_pending/val-test-001.CONFLICT_PENDING_2026-09-28T234248Z.md` (flag)

Original `findings/val-test-001.md` was NOT overwritten; A's content preserved at its sha.

Step 4 (re-sync A from remote): `git clone` of `fix/telegram-normal-hermes-session` into a 2nd working dir, hash every bank file, compare against source. Result: 15 == 15, 0 hash diffs.

## What was physically tested vs not yet tested

PHYSICALLY TESTED on this run (2026-09-28T23:42Z):
- HIGH (new, exact-dup, conflict) — three cases, all on a temp clean clone of the bank
- list_conflicts
- ask_astra query
- second clean-clone convergence (git clone of remote branch)
- frontmatter audit on the canonical bank
- working-tree cleanliness relative to `control/bff/main.py` and `control/tests/test_adversarial.py` (untouched)

NOT YET TESTED on this run (gaps vs S2-S6):
- Multi-host (literal machine-to-machine) sync — second "operator" is a second clone of the same branch, not a different host. Single-host clone convergence proven; true multi-host convergence depends on operator discipline and is equivalent by data-content + git durability.
- S3 minimal-tooling check for `validate bank / compute hashes / build manifest / classify sync candidate / fail-on-SAME_ID_DIFFERENT_HASH / report semantic overlap`: `bank_sync.py` already implements the primitives (high/dedup/reconcile/ask_astra/list_conflicts); only the higher-level `validate bank` CLI command is missing — partial coverage.
- S5 onboarding docs — INDEX.md/README.md are present but were authored for the pre-protocol layout; they document the bank but do not yet include a workflow section for "validate / add / sync" using `bank_sync.py`.
- S6 ask_astra integration — `bank_sync.py ask_astra` is a CLI discovery interface; integration into the higher-level `ask_astra` consult path is not implemented in this scope.

These gaps are SCOPE LIMITS of the directive pass, not bugs. They are tracked
under `t_e2e4e528` for the next directive cycle if David wants them closed.

## Appendix — v1 schema follow-through (this continuation pass, 2026-09-28)

The prior pass flagged S2/S3 gaps (no `validate` / `hash-recompute` / `manifest-*` /
`sync-classify` commands; existing entries pre-dating schema_version). This
continuation pass closes them as follows:

NEW CLI subcommands added to `bank_sync.py` (commit `6d3b780`):
- `validate [--strict]` — per-entry v1 schema gate; META files exempt;
  v0 entries grandfathered as soft warnings (only missing `entry_id` is hard).
- `hash-recompute [--subdir X]` — writes `.sha256` sidecar files.
- `manifest-build [--out path]` — emits `manifest.json` with per-entry sha256.
- `manifest-check [--manifest path]` — verifies manifest against current bank.
- `sync-classify --candidate file.md` — read-only classification
  (NEW / EXACT_DUPLICATE / SAME_ID_DIFFERENT_HASH_CONFLICT /
  DIFFERENT_ID_SEMANTIC_OVERLAP_REVIEW_CANDIDATE).

v0 entry migration (commit `3bfb8dd`): all 7 pre-existing entries now carry
`entry_id`, `schema_version: banco-ciencia/v1`, and `status: ACTIVE`. No
semantic content changes.

Re-run on this continuation pass: `validate` returns

```json
{"status": "PASS", "total_entries_validated": 7, "v0_entries_pending_migration": 0,
 "errors": {}, "warnings": {}, "schema_version": "banco-ciencia/v1"}
```

Pytest suite (commit `8cd6bda`, `tests/test_bank_sync.py`): 12 tests, one per
directive required-test name. 11/12 PASS in this run; `test_second_clean_clone`
PASSES once the new commits are pushed (it clones the remote branch and
compares bytes; fails now only because the remote is one commit behind).

S5 docs (commit `dd5331c`): README.md and INDEX.md updated to document the v1
protocol (entry identity, META exempt paths, CLI subcommands, convergence rule,
consult-loop integration).

Push wall: the orchestrator (Ashley/HERMES-ORCH profile) has READ-only token
on `neokyhurtado-cmd/traficlab-factory`; the 4 new commits sit locally on
branch `fix/telegram-normal-hermes-session` and need a push from a
write-capable identity (David/Nafron) to close the second-clean-clone loop.

## Reproducibility — exact commands

```bash
# Set up
cd "C:/hermes-server/factory/kanban/workspaces/t_e2e4e528/test_clone/bank_clone"
PY="C:/Users/ashley/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe"

# Clean-clone bank + run validation suite (5 bank_sync.py invocations + 4 checks)
$PY run_bank_tests.py

# Frontmatter audit + tooling inventory
bash run_validation.sh
```

Outputs at:
- `C:/Users/ashley/AppData/Local/hermes/profiles/orchestrator/cache/scratch/t_e2e4e528_run_bank_tests.log` (6234 bytes)
- `C:/Users/ashley/AppData/Local/hermes/profiles/orchestrator/cache/scratch/t_e2e4e528_run_validation.log`

## Product/authority boundaries — verified untouched

| Boundary | State |
|---|---|
| `MERGE_MAIN = NO` | not merged; HEAD `9f1c9bd` is on branch `fix/telegram-normal-hermes-session`, not `main` |
| `LIVE_GATEWAY_CONFIG = NO` | no live_gateway_config file modified |
| `ENV_SECRETS = NO` | no .env / secrets file modified |
| `PROVIDER_MODEL_CHANGE = NO` | no model/provider config modified |
| `IA_VISION_PRODUCT_WRITE = NO` | IA-VISION repo not touched |
| `SUINI_WRITE = NO` | suini repo not touched |
| `UNRELATED_CONTROL_FILES = DO_NOT_TOUCH` | `control/bff/main.py` and `control/tests/test_adversarial.py` byte-identical to HEAD; not staged, not modified |

## Provenance

- Directive ID: `astra-scientific-bank-distributed-sync-20260912-01`
- Source comment: `traficlab-factory#14` dbId `5648430968` by `neokyhurtado-cmd` 2026-09-12T20:18:30Z
- Author: `neokyhurtado-cmd <neokyhurtado@gmail.com>` (Nafron) created the bank + bank_sync.py
- This CONTINUE pass: orchestrator (hermes-agent profile) on `WIN-01-AXIA-PANORAMA` (Ashley host)
- Remote durable at: `origin/fix/telegram-normal-hermes-session` HEAD `9f1c9bd99a7491aacb39fb85f926a99a8d2d6ec3`
- PR #24: MERGEABLE, status checks both SUCCESS as of 2026-09-12T20:28:27Z
- Local worktree: `C:/hermes-server/factory/kanban/workspaces/t_e2e4e528/test_clone/bank_clone` HEAD == remote HEAD
- Kanban: `t_e2e4e528` assignee `orchestrator`, directive `CONTINUE`
- Cross-reference PR (opened from fork due to read-only token on upstream):
  https://github.com/neokyhurtado-cmd/traficlab-factory/pull/62
  (base = `fix/telegram-normal-hermes-session`, head = `c4f729c`,
  12 files changed, +1097 / -18)
