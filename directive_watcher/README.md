# Directive Watcher — Phase 1 (HERMES-2.0)

> **Source of truth:** `traficlab-factory#18`
> **Work Order:** `HERMES-2.0-GITHUB-DIRECTIVE-WATCHER-01`
> **Mode:** `ISOLATED_IMPLEMENTATION`
> **Activation:** `NOT_DONE` — see [Activation](#activation-human_go_real_boundary) below.

This directory implements the Phase 1 GitHub Directive Watcher described in
`traficlab-factory#18`. It is **a consumer of the same orchestrator tick**
that already drives `orchestrator/scripts/github_poller.py` (which polls
labelled Work Orders and creates kanban tasks). The directive watcher
wakes the Director when Astra or David post a structured
`[ASTRA_DIRECTIVE:v1]` block in a comment.

## ⚠️ ONE CRON, ONE TICK — fail-closed contract

**The only production scheduling authority is
`orchestrator/scripts/github_poller.py::main()`.** It runs both the WO
   ingestion AND the directive ingestion under one Python invocation —
   no second cron island, no independent polling loop.

- **Do NOT add a separate cron entry** for the directive watcher. The
  Phase 3 / `P0 #2 / SINGLE_POLLING_TRUTH` contract (PR #19 comment
  5629796729) explicitly forbade "two independently runnable polling
  authorities". A copy-pasted cron pointing at `directive_watcher.cli`
  with a scheduler loop would silently start a second ticking
  authority and corrupt the durable state.
- **`--once` is a diagnostic tool**, not a production mode. It runs a
  single tick and exits. The orchestrator cron wraps
  `github_poller.main()` (which internally calls `run_directive_tick`)
  — that is the only cron entry this codebase owns.
- The `Scheduler` class itself survives in `directive_watcher.scheduler`
  for diagnostic use (an operator may run it inline on a workstation;
  tests construct it directly). The CLI no longer wires it as a
  production-reachable scheduling authority.

If a future operator wants to run the watcher in a local loop for
debugging, they construct `Scheduler` directly from Python. The CLI
deliberately refuses that path.

## Canonical flow

```text
Astra/David comment in GitHub
        ↓
[ASTRA_DIRECTIVE:v1]        ← fail-closed; anything else is information-only
        ↓
orchestrator/scripts/github_poller.py::main()   ← ONE TICK
        ↓ (fans out under one tick)
WatcherHandler.tick(repos, run_id=...)         ← single-owner seam
        ↓
validate repo + author + directive id
        ↓
CONTEXT_BINDING_FAIL_CLOSED (PR #19 closeout):
  - REPOSITORY == actual repo being polled
  - ISSUE      == comment.issue_number
  - EXPECTED_HEAD == gh.get_branch_head(repo, branch)
  - AUTO_FROM_ISSUE_CONTEXT resolved or fail-closed
        ↓
idempotency check           ← durable sidecar state (SQLite)
        ↓
exactly-once claim           ← BEGIN IMMEDIATE + UNIQUE(directive_id)
        ↓
Director ACK                 ← [HERMES_ACK:v1] posted on the same issue
        ↓
execution under governance   ← customisable ExecutionFn; default never
                                performs merge/release/deploy
        ↓
Director RESULT              ← [HERMES_RESULT:v1] linking source comment,
                                directive id, execution id
        ↓
READY_FOR_ASTRA_REAUDIT  (or BLOCKED_EXTERNAL_REAL / HUMAN_GO_REAL_REQUIRED)
```

## Layout

```
directive_watcher/
├── __init__.py
├── conftest.py                 # sys.path shim for the test runner
├── directive_parser.py         # [ASTRA_DIRECTIVE:v1] parser (frozen record)
├── sentinels.py                # AUTO_FROM_ISSUE_CONTEXT / NONE sentinels (legacy compat)
├── allowlist.py                # repo + author allowlists + protected gate
├── sidecar_store.py            # durable SQLite state (claim, result, edits)
├── gh_client.py                # gh CLI wrapper + FakeGitHubClient for tests
│                               # + get_branch_head() for HEAD_BINDING contract
├── retry.py                    # exponential backoff with jitter
├── evidence.py                 # evidence/visual/<execution_id>/ skeleton
├── status.py                   # watcher_status.json snapshot for War Room
├── ack_result.py               # [HERMES_ACK:v1] / [HERMES_RESULT:v1] composers
├── handler.py                  # tick() — CONTEXT_BINDING_FAIL_CLOSED contracts
├── scheduler.py                # 5-min loop (DIAGNOSTIC ONLY — see top of file)
├── cli.py                      # `python -m directive_watcher.cli --once`
├── config.example.yaml         # YAML allowlist template (test/dev)
├── allowlists/
│   └── authors.prod.yaml.example   # PRODUCTION author allowlist template
│                                   # (fail-closed-by-default: neokyhurtado-cmd only)
└── tests/                      # behavioural tests
```

## Tests

```bash
cd traficlab-factory
python -m pytest directive_watcher/tests/ -v
```

The suite covers the CONTEXT_BINDING_FAIL_CLOSED contracts plus the
Phase 3 P0 contracts. Each contract has a sabotage run that bites
(see `IMPLEMENTATION_NOTES.md`).

## Configuration

The watcher has TWO environment-specific config paths. They are
intentionally separated so the production allowlist cannot be silently
shadowed by a test fixture.

### Production (`--env=prod`, the default)

```bash
python -m directive_watcher.cli \
    --config <repos-only.yaml> \
    --author-allowlist <authors.prod.yaml> \
    --once
```

- `--env=prod` (default) reads the **author allowlist** from
  `--author-allowlist` (e.g. `directive_watcher/allowlists/authors.prod.yaml`).
- `--config` carries **only the repo list** in production.
- If `--author-allowlist` is missing → fail-closed, exit code 3,
  stderr message `"author allowlist file missing — fail-closed"`.
- The shipped template (`authors.prod.yaml.example`) contains ONLY
  `neokyhurtado-cmd` (David). `astra` is intentionally NOT in the
  default production allowlist — the production watcher must only
  accept directives from David. Astra's re-audits come through David
  in the governance process.

### Test/dev (`--env=test`)

```bash
python -m directive_watcher.cli \
    --config <test-fixture.yaml> \
    --env test \
    --once
```

- `--env=test` uses `--config` as a combined fixture (repos + authors).
- This is the path the test suite uses; it is NOT a production entry.

## Running

The CLI has **no production-loop mode**. The `--once` flag is required
and the CLI exits after a single tick:

```bash
python -m directive_watcher.cli \
    --config directive_watcher.yaml \
    --author-allowlist directive_watcher/allowlists/authors.prod.yaml \
    --once
```

For a workstation diagnostic loop, construct `Scheduler` directly from
Python (see `directive_watcher/tests/test_scheduler_cli.py` for usage
patterns). Do NOT add the CLI to any cron.

## Activation (HUMAN_GO_REAL boundary)

Per the WO, **runtime activation is NOT included in this ticket.** The
watcher software is ready; turning it on requires:

1. **Single cron verification.** Confirm that
   `orchestrator/scripts/github_poller.py::main()` is the only cron
   entry driving both WO + directive ingestion. The Phase 3 P0 #2
   `SINGLE_POLLING_TRUTH` contract forbids a separate cron for the
   directive watcher.
2. **Allowlist curation.** The default config allowlists
   `neokyhurtado-cmd/traficlab-factory` and `neokyhurtado-cmd`. The
   prod author allowlist ships with ONLY `neokyhurtado-cmd`. Confirm
   with Astra before enabling.
3. **First real directive.** Astra posts `[ASTRA_DIRECTIVE:v1]` with
   `AUTO_NEXT_SAFE_GATE = NO` so the first run is observable but not
   silently chained.

These three steps are **deliberately deferred to David GO** because they
cross the runtime/config/service boundary that the WO protects.

## Phase 2 (design only, not implemented)

Phase 2 (per the WO) will introduce a signed GitHub webhook as a faster
trigger while keeping polling as fallback. No code in this ticket starts
that work — it is documented in #18 only.

## CONTEXT_BINDING_FAIL_CLOSED contracts (PR #19 closeout)

The five binding contracts enforced in `handler._process_comment`:

1. **REPO_BINDING** — `directive.repository == actual_repo`. A directive
   pointing at a different repo is BLOCKED before the allowlist check.
2. **ISSUE_BINDING** — `directive.issue == comment.issue_number`. A
   directive pointing at a different issue is BLOCKED.
3. **HEAD_BINDING** — `directive.expected_head == gh.get_branch_head(repo, branch)`.
   Empty EXPECTED_HEAD or unresolvable branch HEAD → fail-closed BLOCK.
4. **AUTO_FROM_ISSUE_CONTEXT** — when YES, the handler resolves
   REPOSITORY / ISSUE / EXPECTED_HEAD from the actual context; insufficient
   context (e.g. comment has no issue_number) → fail-closed BLOCK.
5. **FRESH_START_NO_HISTORY_REPLAY** — empty sidecar + a comment with
   stale EXPECTED_HEAD → BLOCKED by HEAD_BINDING, no replay.

Each contract has a dedicated test in `test_context_binding.py` and a
sabotage run that bites (see `IMPLEMENTATION_NOTES.md`).

## Reuse note (audit)

The watcher **does not duplicate** the existing
`orchestrator/scripts/github_poller.py` or `recovery_observer.py`. Those
modules handle a different problem (labelled Work Orders → kanban tasks
at 60s cadence; recovery for stuck tasks at 5m). The directive watcher
is invoked from the same one tick (`github_poller.main()` → directive
ingestion) — same orchestrator cron, same durable state, same single
source of truth.