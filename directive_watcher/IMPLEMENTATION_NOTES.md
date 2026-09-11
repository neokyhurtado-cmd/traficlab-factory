# HERMES-2.0 GitHub Directive Watcher — implementation notes

> Discovery log for the Phase 1 watcher implemented in `directive_watcher/`.
> This is the durable record of decisions and gotchas for the next session
> (or for Astra re-audit). The actual contract lives in `directive_watcher/README.md`
> and the originating WO is `traficlab-factory#18`.

## What this module is

A separate, versioned, testable outbound polling watcher that consumes
`[ASTRA_DIRECTIVE:v1]` blocks in GitHub comments and orchestrates the
Director dispatch + ACK/RESULT protocol. It is NOT the same as
`orchestrator/scripts/github_poller.py` (which polls labelled Work
Orders and creates kanban tasks). The two can co-exist; this watcher
solves a higher-level orchestration problem.

## Why this design

- **Fail-closed everywhere.** Parser raises on malformed envelopes;
  allowlist denies by default; protected-boundary gate never auto-executes;
  body edits after ACK are detected and rejected.
- **SQLite as sidecar** (separate from any product canonical DB). Exactly-once
  claim via `BEGIN IMMEDIATE` + `UNIQUE(directive_id)`. WAL mode for
  concurrent-reader safety.
- **Thin gh client + FakeGitHubClient for tests.** Avoids the second token
  layer / second attack surface; tests are hermetic.
- **Default `ExecutionFn` records orchestrator-level outcomes only.** It
  never advances a branch or touches the canonical DB. Phase 1 is software
  + tests; activation is David GO.

## Gotchas (worth remembering)

1. **`__pycache__` can mask real bugs.** During development, a stale
   `.pyc` from a previous module shape caused `record_result`'s
   `if cur.rowcount == 0: raise` to be silently bypassed. Always
   `rm -rf */__pycache__` between sabotage runs. This is captured as a
   test (`test_record_result_twice_raises`) that fails loudly if the
   check is removed.
2. **`[ASTRA_DIRECTIVE:v1]` parser must tolerate leading blank lines**
   after the marker. The first iteration broke here because
   `str.splitlines()` after the marker starts with an empty string.
3. **Jitter in `BackoffPolicy` must be clamped to `max_seconds`.**
   A naïve `capped + uniform(-spread, spread)` can exceed the cap by
   `jitter_ratio`. The fix is `min(jittered, self.max_seconds)`. This
   is tested by `test_backoff_policy_caps_delay`.
4. **FakeGitHubClient cursor semantics.** `list_comments_since(repo, since_id)`
   returns only comments with `id > since_id`. To test the body-edit
   detection path, the test must force the watcher's cursor backwards
   (via direct SQL on `directive_seen`) so the logically-edited comment
   is observed again.
5. **evidence.py path convention.** `prepare_execution_dir(base, ...)` writes
   to `<base>/evidence/visual/<execution_id>/`. Passing an already-suffixed
   base (e.g. `tmp/evidence`) double-stamps the path; the watcher passes
   the bare base and `evidence_visual_root()` does the prefixing.
6. **`last_seen_comment_id()` filtering rules out edited comments.**
   When GitHub edits a comment, its id does not change. The watcher
   detects the edit by comparing `body_sha256` inside `directive_seen`
   against the current body — that's why `mark_seen` always upserts.
7. **No CI workflow on this repo.** Local pytest is the green signal.
   A follow-up ticket to add `.github/workflows/directive-watcher.yml`
   is appropriate if Astra wants gating.

## Open questions for Astra re-audit

- **Phase 2 webhook signature verification.** The WO defers this; when
  implemented, the same `DirectiveContract v1` parser applies, only the
  ingestion transport changes.
- **Crash-recovery semantics for the `ExecutionFn`.** Phase 1 records the
  default outcome; if a custom `ExecutionFn` crashes between claim and
  `record_result`, the directive stays in `claim_pending()` forever.
  A future cron-based recovery observer should surface those — but the
  watcher itself should NOT auto-resolve them (HUMAN_GO_REAL boundary).
- **Multi-repo concurrency.** Phase 1 supports one `ExecutionFn`
  globally. If different repos need different execution strategies, the
  Director should pick the strategy at dispatch time and pass it as a
  parameter to `WatcherHandler` — no change required in the watcher
  itself.
- **First real directive.** The activation plan says "Astra posts with
  `AUTO_NEXT_SAFE_GATE = NO`". Confirm whether the orchestrator
  scheduler's `auto` mode should be disabled for the very first run.
