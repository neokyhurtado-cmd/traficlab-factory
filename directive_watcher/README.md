# Directive Watcher — Phase 1 (HERMES-2.0)

> **Source of truth:** `traficlab-factory#18`
> **Work Order:** `HERMES-2.0-GITHUB-DIRECTIVE-WATCHER-01`
> **Mode:** `ISOLATED_IMPLEMENTATION`
> **Activation:** `NOT_DONE` — see [Activation](#activation-human_go_real_boundary) below.

This directory implements the Phase 1 GitHub Directive Watcher described in
`traficlab-factory#18`. It is **separate from** the existing
`orchestrator/scripts/github_poller.py` (which polls labelled Work Orders
and creates kanban tasks). The directive watcher is a higher-level
orchestration component that wakes the Director when Astra or David
post a structured `[ASTRA_DIRECTIVE:v1]` block in a comment.

## Canonical flow

```text
Astra/David comment in GitHub
        ↓
[ASTRA_DIRECTIVE:v1]        ← fail-closed; anything else is information-only
        ↓
watcher polls every 5 min   ← outbound only; no inbound listener
        ↓
validate repo + author + marker + directive id
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
READY_FOR_ASTRA_REAUDIT
```

## Layout

```
directive_watcher/
├── __init__.py
├── conftest.py                 # sys.path shim for the test runner
├── directive_parser.py         # [ASTRA_DIRECTIVE:v1] parser (frozen record)
├── allowlist.py                # repo + author allowlists + protected gate
├── sidecar_store.py            # durable SQLite state (claim, result, edits)
├── gh_client.py                # gh CLI wrapper + FakeGitHubClient for tests
├── retry.py                    # exponential backoff with jitter
├── evidence.py                 # evidence/visual/<execution_id>/ skeleton
├── status.py                   # watcher_status.json snapshot for War Room
├── ack_result.py               # [HERMES_ACK:v1] / [HERMES_RESULT:v1] composers
├── handler.py                  # tick() — full pipeline orchestration
├── scheduler.py                # 5-min poll loop (cron-free)
├── cli.py                      # `python -m directive_watcher.cli` entry point
├── config.example.yaml         # YAML allowlist template
└── tests/                      # 83 behavioural tests
```

## Tests

```bash
cd traficlab-factory
python -m pytest directive_watcher/tests/ -v
```

The suite covers all 14 minimum-acceptance scenarios from #18 plus the
sabotage run (proven to fail without the implementation).

## Configuration

Copy `config.example.yaml` to `directive_watcher.yaml` and edit at the
host that will run the watcher. Both `allowlisted_repos` and
`allowlisted_authors` are **explicit lists** — wildcards are forbidden
(fail-closed per #18).

## Running

```bash
# One-shot tick (useful for cron-driven, no_agent jobs):
python -m directive_watcher.cli --config directive_watcher.yaml --once

# Continuous 5-minute loop (local development):
python -m directive_watcher.cli \
    --config directive_watcher.yaml \
    --interval-seconds 300 \
    --sidecar-db ./directive_watcher.sqlite \
    --evidence-root . \
    --status-path ./watcher_status.json
```

The CLI writes `watcher_status.json` after every tick (machine-readable
state for the future War Room panel).

## Activation (HUMAN_GO_REAL boundary)

Per the WO, **runtime activation is NOT included in this ticket.** The
watcher software is ready; turning it on requires:

1. **Cron wiring.** Add a `no_agent` cron entry under
   `~/.hermes/profiles/orchestrator/cron/jobs.json` (mirroring the
   existing `github-poller` job at 1m). Suggested:

   ```json
   {
     "id": "directive-watcher",
     "command": "python -m directive_watcher.cli --config /path/to/directive_watcher.yaml --once",
     "interval_seconds": 300
   }
   ```

2. **Allowlist curation.** The default config allowlists
   `neokyhurtado-cmd/traficlab-factory` and `neokyhurtado-cmd`. The real
   production host may need a different list — confirm with Astra before
   enabling.

3. **First real directive.** Astra posts `[ASTRA_DIRECTIVE:v1]` with
   `AUTO_NEXT_SAFE_GATE = NO` so the first run is observable but not
   silently chained.

These three steps are **deliberately deferred to David GO** because they
cross the runtime/config/service boundary that the WO protects.

## Phase 2 (design only, not implemented)

Phase 2 (per the WO) will introduce a signed GitHub webhook as a faster
trigger while keeping polling as fallback. No code in this ticket starts
that work — it is documented in #18 only.

## Reuse note (audit)

The watcher **does not duplicate** the existing
`orchestrator/scripts/github_poller.py` or `recovery_observer.py`. Those
modules handle a different problem (labelled Work Orders → kanban tasks
at 60s cadence; recovery for stuck tasks at 5m). The directive watcher
handles Astra/David directives → Director dispatch at 5m. They can
co-exist; this watcher is registered as a separate cron job when David
approves activation.
