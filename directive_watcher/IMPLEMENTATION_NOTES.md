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
