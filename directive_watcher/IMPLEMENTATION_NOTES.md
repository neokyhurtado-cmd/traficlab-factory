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
