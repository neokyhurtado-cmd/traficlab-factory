# HERMES-2.0 GitHub Directive Watcher — implementation notes

> Discovery log for the watcher implemented in `directive_watcher/`.
> This is the durable record of decisions and gotchas for the next
> session. The actual contract lives in `directive_watcher/README.md`
> and the originating WO is `traficlab-factory#18`.

## What this module is

A separate, versioned, testable outbound polling watcher that consumes
`[ASTRA_DIRECTIVE:v1]` blocks in GitHub comments and orchestrates the
Director dispatch + ACK/RESULT protocol. Phase 2 wires it into the
existing `orchestrator/scripts/github_poller.py` path so we keep ONE
orchestrator truth (no second hidden cron island).

## Why this design (post Astra re-audit)

- **Fail-closed everywhere.** Parser raises on malformed envelopes;
  allowlist denies by default; protected-boundary gate never auto-executes;
  body edits after ACK are detected and rejected.
- **Real dispatch, not theatre.** Per Fix #1, `default_execution` now
  wires through `OrchestratorDispatcher` (see
  `directive_watcher/orch_dispatch.py`). READY_FOR_ASTRA_REAUDIT is
  reserved for the future case where delegated work is DONE; today's
  default emits DISPATCHED (session bound) or BLOCKED_EXTERNAL_REAL
  (dispatch failed) — never a lie.
- **Per-repo cursors (Fix #2).** The global `MAX(comment_id)` cursor
  silently skipped directives when the cursor had advanced past them
  on a poll of a different repo. We persist a `repo_cursor` table.
- **Edit window (Fix #3).** Re-fetching only `id > since_id` permanently
  skips edited comments. The watcher now re-scans the last N comments
  per tick and compares body_sha to detect edits. The Phase 1 test that
  cheated by rewinding the cursor was rewritten to use this honest path.
- **Durable publication (Fix #4).** ACK and RESULT post are now separate
  from "business outcome". `ack_posted=0` and `result_posted=0` mean the
  message still owes a GitHub publication; the next tick republishes.
- **gh error classification (Fix #5).** Retry policy now classifies
  `GHCLIError` by HTTP status: 5xx + 429 → retry, 4xx → no retry, with
  a default-retry fallback for unclassified non-zero exits.
- **Real pytest discovery (Fix #6).** `pyproject.toml` no longer narrows
  `testpaths` to a single directory. The full repo regression now
  enumerates `directive_watcher/tests/`, `orchestrator/scripts/`, and
  the standalone `control/tests/test_adversarial.py`.

## Gotchas (worth remembering)

1. **`__pycache__` can mask real bugs.** During development, a stale
   `.pyc` from a previous module shape caused `record_result`'s
   `if cur.rowcount == 0: raise` to be silently bypassed. Always
   `rm -rf */__pycache__` between sabotage runs.
2. **`[ASTRA_DIRECTIVE:v1]` parser must tolerate leading blank lines**
   after the marker. The first iteration broke here because
   `str.splitlines()` after the marker starts with an empty string.
3. **Jitter in `BackoffPolicy` must be clamped to `max_seconds`.**
   A naïve `capped + uniform(-spread, spread)` can exceed the cap by
   `jitter_ratio`. The fix is `min(jittered, self.max_seconds)`.
4. **`pytest_plugins = []` MUST live at the repo root.** Setting it
   inside a per-package `conftest.py` triggers pytest 8's
   "Defining 'pytest_plugins' in a non-top-level conftest is no
   longer supported" collection error. The repo-root `conftest.py`
   is the canonical home for this declaration.
5. **`control/tests/test_adversarial.py` is NOT a pytest module.**
   It is a standalone runner (calls `sys.exit(0)` at module scope).
   Pytest discovery chokes on the `sys.exit`. We added
   `control/tests/conftest.py` with `collect_ignore = ["test_adversarial.py"]`
   so the runner still passes under its own invocation
   (`python control/tests/test_adversarial.py`) but doesn't crash
   pytest's collection.
6. **FakeGitHubClient cursor semantics.** `list_comments_since(repo, since_id)`
   returns only comments with `id > since_id`. To test the body-edit
   detection path, the watcher's `list_recent_comments(repo, limit=N)`
   window catches the edited comment without any cursor hack — that's
   the whole point of Fix #3.
7. **evidence.py path convention.** `prepare_execution_dir(base, ...)` writes
   to `<base>/evidence/visual/<execution_id>/`. Passing an already-suffixed
   base (e.g. `tmp/evidence`) double-stamps the path; the watcher passes
   the bare base and `evidence_visual_root()` does the prefixing.
8. **`OrchestratorDispatcher` reuses `routing_resolver.resolve_route`**
   rather than reading `routing.yaml` directly. Per
   `orchestrator/scripts/routing_resolver.py`, that resolver is the
   single read-path and respects HERMES_ROUTING_PATH > HERMES_HOME >
   fallback. We MUST NOT re-parse the routing table ourselves.
9. **`GHCLIError.is_retryable` looks at stderr, not just exit code.**
   gh surfaces HTTP 4xx/5xx in stderr (not exit code), so the
   classifier greps for the status token. If you change gh's error
   format, update `is_retryable` accordingly.
10. **No CI workflow on this repo before Phase 2.** Phase 1 had no
    `.github/workflows/`. Phase 2 adds `directive-watcher-ci.yml` with
    a full repo regression (no `testpaths` narrowing) and a standalone
    adversarial run. Activation still requires David GO.
11. **Session Registry persistence is JSONL, not SQLite.** Phase 2
    uses `directive_watcher/sessions.jsonl` because the registry is
    bounded (one record per dispatched directive) and human-inspectable.
    A SQLite table is a documented follow-up for >10k records.

## What was NOT changed (and why)

- **`control/bff/main.py` and `control/tests/test_adversarial.py`**
  have pre-existing modifications (Tailscale FQDN allowlist; new
  hostname test cases). The Astra re-audit and the original WO both
  said "don't touch these". We honoured that — documented here so
  the next operator understands why the diff excludes them.
- **No cron / activation wiring.** Phase 2 keeps the watcher as a
  library. The orchestrator cron continues to drive
  `orchestrator/scripts/github_poller.py`; the watcher's dispatch
  path REUSES that routing table via `routing_resolver`. Activation
  remains a separate David GO.

## Open questions for Astra re-audit

- **Phase 3 webhook signature verification.** The WO defers this; when
  implemented, the same `DirectiveContract v1` parser applies, only the
  ingestion transport changes.
- **Crash-recovery semantics for the `ExecutionFn`.** Phase 2 records
  the default outcome; if a custom `ExecutionFn` crashes between claim
  and `record_result`, the directive stays `result_status=NULL` forever.
  A future cron-based recovery observer should surface those — but the
  watcher itself must NOT auto-resolve them (HUMAN_GO_REAL boundary).
- **Session Registry UI.** The contract is in place
  (`directive_watcher/orch_dispatch.py::SessionRecord`); the War Room
  panel itself is a separate ticket and out of scope here.
- **First real directive.** The activation plan says "Astra posts with
  `AUTO_NEXT_SAFE_GATE = NO`". Confirm whether the orchestrator
  scheduler's `auto` mode should be disabled for the very first run.

---

# Phase 3 — single primitive + fail-honest status + CI portability

> Follows Phase 2's dispatch rewire. Phase 3 closes the "ONE primitive,
> MANY adaptors" architecture that David froze in comment 5629246987 and
> re-stated in comment 5629293070. No merge, no activation, no micro-GO.

## Phase 3 fixes (commits land on top of `d730a0b`)

### 1. Single kanban primitive — Objective 3

Phase 2 shipped **two** parallel `subprocess.run(['hermes', 'kanban',
'create', ...])` pipelines:

  - `directive_watcher/orch_dispatch.py::OrchestratorDispatcher._invoke_kanban`
  - `orchestrator/scripts/github_poller.py::create_kanban_task`

Both are kept as **adaptors** (the steer in comment 5629293070 explicitly
allowed multiple adaptors). What changed is the **single primitive**:

  - `directive_watcher/kanban_primitive.py::dispatch_to_kanban(
        payload, idempotency_key)`
  - The ONLY module in the repo that calls `hermes kanban create`.
  - Both adaptors build their payload (Directive → payload for the
    directive path; Work Order → payload for the github_poller path)
    and delegate to the primitive.

Idempotency-key convention is preserved:
  - WO path:        `github:<repo>#<issue>`
  - directive path: `directive:<DIRECTIVE_ID>`

**Bite test (proves the invariant):** `directive_watcher/tests/test_kanban_primitive.py`
has a static source guard that scans the two adapter files and FAILS
with a clear `SINGLE_PRIMITIVE VIOLATION` message if anyone re-introduces
a parallel subprocess pipeline. Sabotage-confirmed: re-adding a
`subprocess.run(['hermes', 'kanban', 'create', ...])` to either adapter
makes the test fail with the line number + offending argv.

### 2. `build_status` is fail-honest — Objective 5

Phase 2's `build_status()` hardcoded `watcher_status="healthy"`. That
made the War Room panel show green even when the last run ended in
error — a quiet lie. Phase 3 derives the status from the last run:

  - `last_run_status == "ok"`   → `"healthy"`
  - `last_run_status == "error"`→ `"degraded"`
  - `last_run_status is None`   → `"unknown"`

`watcher_status.json` consumers can now trust the field. Sabotage-confirmed:
re-hardcoding `"healthy"` in the error branch makes
`test_build_status_reflects_degraded_when_last_run_errored` fail with
the exact message.

### 3. `--once` writes `watcher_status.json` — Objective 1

Phase 2's `--once` only printed the tick summary to stdout. The
documented cron path (`hermes cron create --no-agent
directive_watcher.cli -- --once`) silently bypassed the status file
the scheduler loop writes. Phase 3 makes `--once` use the same
`build_status` + `write_status` path. The War Room panel now sees a
fresh snapshot after every cron tick.

### 4. `cli.main()` wires the real dispatch seam — Objective 1 (cont.)

Phase 2's CLI constructed `WatcherHandler` without `dispatcher=`.
The production path therefore fell through to `BLOCKED_EXTERNAL_REAL`
with no session bind — the "doorbell but no one opens" failure. Phase
3's CLI:

  - Resolves the orchestrator routing table
    (`HERMES_ROUTING_PATH` > `HERMES_HOME/config` > repo-local fallback).
  - Builds `OrchestratorDispatcher` with that table + a session-log path.
  - Passes `dispatcher=` to `WatcherHandler`.

Bite test: `test_cli_once_wires_dispatcher_to_handler` captures the
handler kwargs and FAILS if `dispatcher` is missing or `None`.
Sabotage-confirmed.

### 5. CI covers both `hermes_cli` paths — Objective 4 (steered rephrase)

Phase 2's workflow ran on a clean machine without `hermes_cli`. The
directive said "force the fallback"; the steer in comment 5629293070
corrected that to "test that BOTH paths work". Phase 3:

  - Adds a `matrix.hermes_cli: [installed, absent]` strategy to the
    workflow — the suite runs in both arms.
  - Removes the `pip install -r requirements.txt || true` that
    silently hid the missing `requirements.txt`. The repo is stdlib +
    PyYAML only; the step is documented inline.
  - Adds `orchestrator/scripts/test_hermes_cli_portability.py` with
    five tests that hide `hermes_cli` via import mocking and verify
    `eligibility_hook`, `recovery_observer`, and `github_poller`
    still import + function via the fallback paths.

### Architecture map (Phase 3 frozen state)

```
              ORCH TICK (existing cron, no new island)
                 │
       ┌─────────┴─────────┐
       ↓                   ↓
   Work Orders         Directives
       │                   │
       │              WatcherHandler (now wired with dispatcher=)
       │                   │
       │           OrchestratorDispatcher
       │            (adaptor — resolves assignee,
       │             persists SessionRecord,
       │             returns DispatchResult)
       │                   │
       └──────────┬────────┘
                  ↓
        dispatch_to_kanban()
        (directive_watcher/kanban_primitive.py)
        UNIQUE IMPLEMENTATION
                  ↓
               Kanban
                  ↓
           Session Registry
       (directive_watcher/sessions.jsonl)
```

## Gotchas added in Phase 3

12. **`import subprocess` is forbidden in adapter modules.** Only the
    primitive is allowed to spawn `hermes kanban create`. The static
    guard in `test_kanban_primitive.py` enforces this by scanning for
    the literal argv `["hermes", "kanban", "create", ...]` and the
    `import subprocess` statement. If you add a new adaptor, route it
    through `directive_watcher.kanban_primitive.dispatch_to_kanban`.
13. **`build_status` defaults to `"unknown"`, not `"healthy"`.** A
    fresh install with no recorded run shows `"unknown"` so the War
    Room panel doesn't lie about a green system that's never ticked.
14. **`cli.main()` requires both `--config` and an allowlist with at
    least one repo.** Failing the second condition returns exit code 2
    with a clear stderr message — this is the fail-closed contract
    from Phase 1 that we keep.
15. **The matrix CI arm `hermes_cli: absent` is the closer.** If the
    installed arm passes and the absent arm fails, the code has a hard
    dependency on `hermes_cli` that needs to be removed.

## Phase 3 metrics (current HEAD)

- Pytest regression: **231 PASS** (139 in `directive_watcher/tests/`,
  92 in `orchestrator/scripts/`).
- Standalone adversarial: **97 pass, 0 fail**
  (`control/tests/test_adversarial.py`).
- Total: **328 regressions executed**, 0 fail.
- Pre-existing dirty files (NOT touched, per directive):
  `control/bff/main.py`, `control/tests/test_adversarial.py`.

## What did NOT change in Phase 3

- `OrchestratorDispatcher` survived (adaptor, per the steer).
- `SessionRecord` shape is unchanged.
- `OrchestratorDispatcher._invoke_kanban` is now a thin wrapper that
  builds the payload and delegates. Its signature, idempotency
  semantics, and DispatchError contract are preserved.
- The watcher remains a library. No cron wiring, no activation, no
  merge, no micro-GO.


---

# Phase 3 closeout pass — Astra re-audit (PR #19 comment 5629796729)

> Frozen contract closeout on top of `f326ecf`. NO merge, NO activation,
> NO micro-GO. Five P0 contracts closed with TDD strict, sabotage
> runs that bite, and a separate adversarial CI workflow. No new
> architecture, no new product features.

## The five closed P0 contracts

| # | Contract | Where | Bite test |
|---|----------|-------|-----------|
| 1 | `github_poller` runs through a gh wrapper | `gh_wrapper.py` (new) + `orchestrator/scripts/github_poller.py` rewrite of `gh_list_work_orders` | `test_github_poller_runtime.py::test_github_poller_does_not_call_subprocess_run_directly` + `test_github_poller_main_path_runs_without_nameerror` |
| 2 | One ORCH tick walks WO + Directive ingestion; cli has no production loop | `github_poller.main()` + `run_directive_tick()`; `cli.py` requires `--once` | `test_single_tick.py::test_orch_tick_invokes_both_wo_and_directive_ingestion` + `test_cli_rejects_running_without_once_flag` |
| 3 | `--once` produces exactly one `watcher_run` row | `handler.tick(run_id=...)` + `cli.main()` passes `run_id` | `test_one_tick_one_run.py::test_cli_once_records_exactly_one_run` |
| 4 | hermes_cli detection via `importlib.util.find_spec` (no shadow) | `conftest.py` gate | `test_hermes_cli_detection.py::test_detection_uses_find_spec_not_sys_modules` + `test_when_hermes_cli_is_importable_conftest_does_not_stub` + `test_when_hermes_cli_is_missing_conftest_does_stub` |
| 5 | Full repo regression CI without silent SKIPs | `.github/workflows/directive-watcher-adversarial.yml` (new) + `directive-watcher-ci.yml` honest enumeration | the dedicated adversarial workflow reports its own status; CI never carries a silent SKIP for fastapi deps |

## Gotchas added in the closeout pass

16. **`subprocess.run` is forbidden in `github_poller.py`.** The gh
    transport lives in `orchestrator/scripts/gh_wrapper.py` —
    `GithubClient.list_issues_with_label`. The static guard in
    `test_github_poller_runtime.py` is the bite: a stray
    `subprocess.run` reintroduced into the poller fails the guard
    with a clear "Route every subprocess invocation through a
    dedicated gh wrapper" message. The Phase 3 single-primitive
    `test_kanban_primitive.py` guard stays — the kanban primitive
    is the only home of `hermes kanban create`; the gh wrapper is
    the only home of `gh issue list`. Two wrappers, two domains.
17. **`handler.tick(repos, *, run_id=...)` is the single-owner seam
    for `watcher_run` rows.** When `run_id` is supplied, the handler
    treats the row as already-opened and only calls
    `record_run_finish(run_id, ...)`. When `run_id` is None the
    handler mints its own row (legacy Scheduler-only diagnostic
    path). The CLI always supplies `run_id` so one logical tick
    produces one `watcher_run` row. See
    `directive_watcher/tests/test_one_tick_one_run.py`.
18. **`github_poller.main()` is the one tick authority.** It walks
    WO ingestion (existing pipeline) AND directive ingestion (new
    `run_directive_tick()`) under one Python invocation. The cli's
    `Scheduler.run_forever()` was removed as a production-reachable
    scheduling authority. The Scheduler class itself survives for
    diagnostic use (operator runs it inline on a workstation;
    tests construct it directly). See
    `orchestrator/scripts/test_single_tick.py`.
19. **`conftest.py` uses `importlib.util.find_spec("hermes_cli")`
    (NOT `"hermes_cli" not in sys.modules`).** The old gate asked
    the import history and shadowed a real install that pytest had
    not yet imported. The new gate asks the import system whether
    the package exists on disk. Behaviour: a real install never
    gets a stub. A missing install still gets the stub so the
    pre-existing `fixture_profiles` keeps working. See
    `orchestrator/scripts/test_hermes_cli_detection.py`.
20. **Two GitHub workflows, each owning its own dependency set.**
    `directive-watcher-ci.yml` runs pytest discovery over the whole
    repo (stdlib + PyYAML only). `directive-watcher-adversarial.yml`
    installs fastapi + uvicorn in its own job and runs the
    standalone adversarial runner; it does not couple the watcher
    runtime tree to the BFF runtime tree. Each workflow reports
    its own status. The classic "GREEN CI ≠ FULL_REGRESSION_CI"
    failure mode (Astra re-audit) is closed.
21. **Two gh wrappers, same binary, two domains.** The directive
    watcher's `directive_watcher/gh_client.py::GHCLIClient` (comment
    listing for ACK/RESULT publication) and the orchestrator's
    `orchestrator/scripts/gh_wrapper.py::GithubClient` (issue
    listing for WO ingestion) are distinct modules by design — they
    serve different observable surfaces. Multiple thin wrappers are
    permitted as long as each one owns its own subprocess plumbing;
    a second wrapper that pretends to be the primitive is not.

## Sabotage runs (proof the tests bite)

For each P0 contract, the closing pass reverts the production fix
and confirms the test fails with a clear, on-topic message. The
full enumeration:

- P0 #1: revert `gh_list_work_orders` to `subprocess.run(...)` →
  `test_github_poller_does_not_call_subprocess_run_directly` fails
  with "Phase 3 re-audit NameError bug ... route every subprocess
  invocation through a dedicated gh wrapper" and
  `test_github_poller_main_path_runs_without_nameerror` surfaces
  the literal `NameError: name 'subprocess' is not defined` (the
  exact bug Phase 3 missed).
- P0 #2: drop the `run_directive_tick` call from `main()` →
  `test_orch_tick_invokes_both_wo_and_directive_ingestion` fails
  with "P0 #2 / SINGLE_POLLING_TRUTH ... orch tick must invoke
  WatcherHandler.tick() exactly once; got 0".
- P0 #3: drop `run_id=` from `handler.tick(repos, ...)` →
  `test_cli_once_records_exactly_one_run` fails with
  "P0 #3 violation: --once must produce EXACTLY ONE watcher_run
  row, got 2" — explicitly naming the duplicate-row contract.
- P0 #4: revert the gate to `"hermes_cli" not in sys.modules` →
  `test_detection_uses_find_spec_not_sys_modules` fails with
  "conftest.py still USES the broken ... gate in executable code".
- P0 #5: a workflow that re-installs the silent-SKIP branch would
  be reverted by the workflow's own grep at the end
  (`grep -q "=== RESULT: .* pass, 0 fail ===$" /tmp/adversarial.log`).
  The dedicated workflow can be made to fail loudly by editing
  `control/tests/test_adversarial.py` to add a deliberate fail;
  that file is intentionally untouched here, so the sabotage would
  be exercised in a future operator pass (documented in this
  IMPLEMENTATION_NOTES as the bound for the contract).

## Suite enumeration — closeout baseline

```
directive_watcher/tests/                          140 PASS
  ├─ Phase 1 + Phase 2 + Phase 3 pre-existing     137 (unchanged)
  ├─ test_one_tick_one_run.py (P0 #3)               1 (new)
  └─ 2 tests renamed/updated for the closeout       2
orchestrator/scripts/                            100 PASS
  ├─ Pre-existing routing/poller/eligibility/...  87 (unchanged)
  ├─ test_hermes_cli_portability.py (Phase 3)       5 (unchanged)
  ├─ test_hermes_cli_detection.py (P0 #4)           3 (new)
  ├─ test_github_poller_runtime.py (P0 #1)         2 (new)
  └─ test_single_tick.py (P0 #2)                    3 (new)
control/tests/test_adversarial.py (standalone)   REPORTED SEPARATELY
                                                by directive-watcher-adversarial.yml
TOTAL (pytest):                                  240 PASS, 0 fail
Adversarial (separate CI job):                   depends on operator's fastapi install
                                                — workflow enforces the contract via grep
```

## What did NOT change in the closeout pass

- `OrchestratorDispatcher` survives as a domain adaptor (per the
  original steer, comment 5629293070).
- `SessionRecord` shape unchanged from Phase 2.
- `control/bff/main.py` and `control/tests/test_adversarial.py`
  left dirty (pre-existing, NOT part of this PR).
- Incident provenance preserved: `b5bbcc1` (`noop`) and `b2cbbb6`
  (chore: remove accidental noop file) stay on the branch.
- No merge, no activation, no micro-GO, no HUMAN_GO_REAL.
- The new commit is the single closeout pass on the frozen
  contracts. No new architecture, no new product features.


---

# Phase 4 closeout — CONTEXT_BINDING_FAIL_CLOSED (PR #19 comment 5629796729)

> Frozen contract closeout on top of `07d44c33` (the Phase 3 closeout
> pass). NO merge, NO activation, NO micro-GO. Five binding contracts
> closed with TDD strict, sabotage runs that bite, and explicit
> PROD/TEST env separation.

## The five closed CONTEXT_BINDING_FAIL_CLOSED contracts

| # | Contract | Where | Bite test |
|---|----------|-------|-----------|
| 1 | REPO_BINDING: `directive.repository == actual_repo` | `handler._process_comment` (envelope-vs-actual-context check before allowlist) | `test_context_binding.py::test_repo_binding_blocks_directive_whose_repo_differs` |
| 2 | ISSUE_BINDING: `directive.issue == comment.issue_number` | `handler._process_comment` (same seam as #1) | `test_context_binding.py::test_issue_binding_blocks_directive_whose_issue_differs` |
| 3 | HEAD_BINDING: `directive.expected_head == gh.get_branch_head(repo, branch)` | `handler._process_comment` + `gh_client.GitHubClient.get_branch_head` (Protocol + Fake + Production) | `test_context_binding.py::test_head_binding_blocks_when_expected_head_is_stale` |
| 4 | AUTO_FROM_ISSUE_CONTEXT: YES → derive from context; YES + insufficient context → BLOCK | `directive_parser.Directive.auto_from_issue_context` + `handler._process_comment` | `test_context_binding.py::test_auto_from_ctx_yes_without_issue_number_blocks_fail_closed` |
| 5 | FRESH_START_NO_HISTORY_REPLAY: empty sidecar + historical comment with stale HEAD → BLOCKED | `handler._process_comment` HEAD_BINDING + per-repo cursor advance | `test_context_binding.py::test_fresh_start_does_not_claim_historical_directive_with_stale_head` |

## The closed PROD/TEST ENV SEPARATION contract

| # | Contract | Where | Bite test |
|---|----------|-------|-----------|
| 6 | PROD author allowlist is read from an explicit `--author-allowlist` path; missing file → fail-closed (rc != 0) + clear stderr message; default = `--env=prod`; only `neokyhurtado-cmd` ships in the template | `cli.py` argparse + `cli.main()` branch + `directive_watcher/allowlists/authors.prod.yaml.example` | `test_cli_env_separation.py::test_prod_env_missing_author_file_is_fail_closed` |

## The closed documentation contract

| # | Contract | Where | Bite test |
|---|----------|-------|-----------|
| 7 | README says ONE CRON, ONE TICK — `orchestrator/scripts/github_poller.py::main()` is the only scheduling authority; `--once` is diagnostic only; `Scheduler` survives for diagnostic use but is NOT wired to the CLI | `directive_watcher/README.md` (full rewrite) | (doc-only; bite confirmed by inspection of the diff) |

## Gotcha #22

22. **The CONTEXT_BINDING_FAIL_CLOSED pattern is "validate envelope
    against actual context BEFORE the allowlist".** A hostile or stale
    directive is rejected on the binding contract (which is the cheap
    check), not on the allowlist (which is the broader check). Putting
    the binding checks first is the fail-closed shape: a misspelled
    repo in the envelope can never reach the allowlist, can never
    reach the dispatcher, can never produce a session bind. The
    `notes.append(...)` line is the durable audit trail — every
    BLOCKED directive leaves a specific, parseable message that names
    the offending field, the actual value, and the expected value.
    The test for each contract reads `summary.notes` to confirm the
    specific message landed; that is how the sabotage run bites.
    `AUTO_FROM_ISSUE_CONTEXT=YES` is the escape hatch for legitimate
    directives that don't want to spell out the binding fields
    explicitly — the handler resolves them from the actual context
    and the binding check still runs (with the resolved values).
    Insufficient context (e.g. PR review comment with `issue_number=0`)
    is BLOCKED fail-closed because there is no honest default to fall
    back to.

23. **The PROD/TEST env separation is a CLI-shape contract, not a
    runtime toggle.** `--env=prod` is the default; production
    deployments MUST NOT need to remember to set a flag. The shape:
    `--env=prod` requires `--author-allowlist <` (separate from
    `--config`); `--env=test` uses `--config` as the combined
    fixture. The fail-closed behaviour for missing `--author-allowlist`
    is at the CLI gate (exit code 3 + stderr), not deep in the
    handler. The shipped template `authors.prod.yaml.example` contains
    ONLY `neokyhurtado-cmd` so a copy-pasted enable cannot silently
    grant production access to `astra` (who authors re-audits but
    does not author execution-bound directives).

24. **The Phase 1 sentinels `EXPECTED_HEAD = NONE` and
    `TARGET_BRANCH = AUTO_FROM_ISSUE_CONTEXT` are not removed by the
    CONTEXT_BINDING_FAIL_CLOSED contracts.** They are still valid
    envelope values, resolved to the live branch HEAD by
    `directive_watcher/sentinels.py::resolve_expected_head` /
    `resolve_branch_name`. A literal sha is compared verbatim. The
    sentinel-vs-empty distinction matters: empty `EXPECTED_HEAD` is a
    fail-closed BLOCK ("EXPECTED_HEAD missing"); a sentinel is a
    pass-through to the resolved HEAD. Tests for legacy
    `EXPECTED_HEAD = NONE` envelopes must seed `(repo, "main")` in
    `FakeGitHubClient.set_branch_head()` so the resolution returns a
    real sha.
