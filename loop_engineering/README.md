# loop_engineering V1

Layered on top of `MACROTURN_CONTRACT_V1` (existing in `traficlab-factory`).
Implements the autonomous goal loop per directive `LOOP-ENGINEERING-V1-20260917-01`.

## Files

```
loop_engineering/
├── __init__.py
├── engine.py                     # LoopEngine driver + can_continue/persist/ingest
├── contracts/
│   ├── __init__.py
│   ├── loop_contract.py          # LoopContractV1 dataclass + LoopState enum
│   └── worker_result.py          # WorkerResult dataclass + ANTI_FALSE_CLOSURE rule
└── tests/
    ├── __init__.py
    └── test_loop_engineering.py  # 15+ acceptance tests
```

## State machine

`INTAKE → SYNCING → PLANNING → DISPATCHING → RUNNING → COLLECTING → VERIFYING → SYNTHESIZING → (PLANNING | DONE)`

Plus: `→ REPLANNING → PLANNING`, `→ WAITING_HARD_STOP → PLANNING | CANCELLED`, `→ BLOCKED_EXTERNAL` (terminal), `→ CANCELLED` (terminal), `→ DONE` (terminal).

## Acceptance tests

```
1. independent nodes parallel-eligible
2. dependent nodes serialized
3. node FAIL → replan
4. NOT_PROVEN → keep active
5. PASS without evidence → rejected (anti-false-closure)
6. safe work → continue (hard continuation rule)
7. two writers same scope → one blocked
8. snapshot persists for recovery
9. resume from snapshot
10. duplicate dispatch → exactly-once
11. HARD STOP halts
12. BLOCKED_EXTERNAL terminal
13. DONE terminal
14. BrainPool update bounded + sourced
15. no NEXO/runtime/gateway mutation
```

## Run

```bash
cd /c/Users/david/repos/traficlab-factory.worktrees/loop-engineering-v1
python -m pytest loop_engineering/tests/ -v
```

## What this is NOT

- Not a replacement for the existing orchestrator (`orchestrator/`, `directive_watcher/`)
- Not a new scheduler/daemon
- Not a runtime rewrite
- Not a NEXO/gateway modification
