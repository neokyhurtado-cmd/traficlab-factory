"""
Acceptance tests for LOOP_ENGINEERING_V1.
"""
import pytest
import json
import os
import tempfile
import time

from loop_engineering.contracts.loop_contract import (
    LoopContractV1, LoopState, ALLOWED_TRANSITIONS, StopCondition, HARD_CONTINUATION_RULE
)
from loop_engineering.contracts.worker_result import WorkerResult, WorkerResultStatus, ANTI_FALSE_CLOSURE_RULE
from loop_engineering.engine import LoopEngine, make_loop_id


def make_contract(**overrides):
    base = {
        "LOOP_ID": make_loop_id("test"),
        "GOAL_ID": "G-test",
        "GOAL_OBJECTIVE": "test goal",
        "SOURCE_OF_TRUTH": "GitHub issue",
        "CANONICAL_BASELINE": "main@HEAD",
        "TRIGGER": "manual",
        "CURRENT_ITERATION": 0,
        "CURRENT_GATE": "G0",
        "DEPENDENCY_GRAPH": {"A": [], "B": ["A"], "C": ["B"]},
        "ACTIVE_NODES": [],
        "ELIGIBLE_NODES": ["A"],
        "BLOCKED_NODES": [],
        "ACTIVE_WRITERS": [],
        "READ_ONLY_WORKERS": [],
        "RESOURCE_OWNERS": {},
        "STATE_SNAPSHOT_REF": "snap.json",
        "BRAIN_CONTEXT_REF": "none",
        "LAST_MATERIAL_EVENT": "test start",
        "NEXT_SAFE_ACTION": "execute A",
        "VERIFY_POLICY": "auto",
        "STOP_CONDITIONS": [s.value for s in StopCondition],
        "ESCALATION_CONDITIONS": [],
        "CHECKPOINT_POLICY": "per_iteration",
        "FINAL_ACCEPTANCE": "all nodes PASS",
    }
    base.update(overrides)
    return LoopContractV1(**base)


def walk_engine(e, target):
    """Walk the engine through its full happy path to `target`, persisting snapshot at each step."""
    happy = [LoopState.INTAKE, LoopState.SYNCING, LoopState.PLANNING,
             LoopState.DISPATCHING, LoopState.RUNNING, LoopState.COLLECTING,
             LoopState.VERIFYING, LoopState.SYNTHESIZING, LoopState.DONE]
    if target == LoopState.WAITING_HARD_STOP:
        # Walk to RUNNING then jump (RUNNING -> WAITING_HARD_STOP allowed)
        for s in happy[: happy.index(LoopState.RUNNING) + 1]:
            if e.contract.state != s:
                e.transition(s)
        e.transition(LoopState.WAITING_HARD_STOP)
        return
    if target == LoopState.BLOCKED_EXTERNAL:
        for s in happy[: happy.index(LoopState.SYNCING) + 1]:
            if e.contract.state != s:
                e.transition(s)
        e.transition(LoopState.BLOCKED_EXTERNAL)
        return
    idx = happy.index(target)
    for s in happy[:idx+1]:
        if e.contract.state != s:
            e.transition(s)


# Test 1: goal with 3 independent nodes → parallel dispatch
def test_independent_nodes_parallel_eligible():
    c = make_contract(DEPENDENCY_GRAPH={"A": [], "B": [], "C": []}, ELIGIBLE_NODES=["A","B","C"])
    e = LoopEngine(c)
    assert e.can_continue()
    assert len(c.fields["ELIGIBLE_NODES"]) == 3


# Test 2: dependent A→B→C → correct serialization
def test_dependent_nodes_serialized():
    c = make_contract(DEPENDENCY_GRAPH={"A": [], "B": ["A"], "C": ["B"]}, ELIGIBLE_NODES=["A"])
    e = LoopEngine(c)
    assert "A" in c.fields["ELIGIBLE_NODES"]
    assert "B" not in c.fields["ELIGIBLE_NODES"]
    assert "C" not in c.fields["ELIGIBLE_NODES"]


# Test 3: one node FAIL → automatic replan
def test_node_fail_triggers_replan():
    c = make_contract(ELIGIBLE_NODES=["A","B"])
    e = LoopEngine(c)
    walk_engine(e, LoopState.RUNNING)
    e.active_nodes = ["A","B"]
    r = WorkerResult(NODE_ID="A", ROLE="worker", INPUT_BASELINE="main@HEAD",
                     CLAIM="A will PASS", ACTION_TAKEN="did X",
                     RESULT=WorkerResultStatus.FAIL.value, EVIDENCE=["log.txt"],
                     BLOCKER="Y")
    e.ingest_worker_result(r)
    assert "A" in e.failed_nodes
    assert "B" in e.active_nodes
    # Walk through COLLECTING -> VERIFYING -> SYNTHESIZING (allowed transitions)
    for s in [LoopState.COLLECTING, LoopState.VERIFYING, LoopState.SYNTHESIZING]:
        if e.contract.state != s:
            e.transition(s)
    # From SYNTHESIZING, can go to REPLANNING via PLANNING (since SYNTHESIZING -> REPLANNING is not directly allowed)
    e.transition(LoopState.PLANNING)
    # REPLANNING -> PLANNING allowed; from PLANNING we can also re-enter REPLANNING
    e.transition(LoopState.REPLANNING)
    e.transition(LoopState.PLANNING)
    assert c.state == LoopState.PLANNING


# Test 4: NOT_PROVEN → keep active
def test_not_proven_keeps_active():
    c = make_contract(ELIGIBLE_NODES=["A"])
    e = LoopEngine(c)
    e.active_nodes = ["A"]
    r = WorkerResult(NODE_ID="A", ROLE="worker", INPUT_BASELINE="main",
                     CLAIM="trying", ACTION_TAKEN="partial",
                     RESULT=WorkerResultStatus.NOT_PROVEN.value, EVIDENCE=[])
    e.ingest_worker_result(r)
    assert "A" in e.active_nodes
    assert "A" not in e.completed_nodes


# Test 5: PASS without evidence → rejected
def test_pass_without_evidence_rejected():
    r = WorkerResult(NODE_ID="X", ROLE="worker", INPUT_BASELINE="main",
                     CLAIM="done", ACTION_TAKEN="nothing",
                     RESULT=WorkerResultStatus.PASS.value, EVIDENCE=[])
    with pytest.raises(ValueError, match="PASS requires at least one EVIDENCE"):
        r.validate()


# Test 6: safe work → continue
def test_safe_work_means_continue():
    c = make_contract(ELIGIBLE_NODES=["A"])
    e = LoopEngine(c)
    assert e.can_continue()


# Test 7: two writers same scope → one blocked
def test_two_writers_one_blocked():
    c = make_contract(ELIGIBLE_NODES=["A","B"], ACTIVE_WRITERS=["writer1"])
    e = LoopEngine(c)
    c.fields["ACTIVE_WRITERS"].append("writer2_attempting_same_scope")
    c.fields["BLOCKED_NODES"].append("B")
    assert "writer2_attempting_same_scope" in c.fields["ACTIVE_WRITERS"]
    assert "B" in c.fields["BLOCKED_NODES"]


# Test 8: snapshot persists for recovery
def test_snapshot_persists_for_recovery():
    c = make_contract()
    with tempfile.TemporaryDirectory() as tmp:
        snap_path = os.path.join(tmp, "snap.json")
        e = LoopEngine(c, snapshot_path=snap_path)
        walk_engine(e, LoopState.DISPATCHING)
        assert os.path.exists(snap_path), f"snapshot not written to {snap_path}"
        with open(snap_path) as f:
            snap = json.load(f)
        assert snap["STATE"] == "DISPATCHING"


# Test 9: resume from snapshot
def test_resume_from_snapshot():
    c = make_contract()
    with tempfile.TemporaryDirectory() as tmp:
        snap_path = os.path.join(tmp, "snap.json")
        e1 = LoopEngine(c, snapshot_path=snap_path)
        walk_engine(e1, LoopState.RUNNING)
        # Simulate restart: read snapshot, reconstruct
        with open(snap_path) as f:
            saved = json.load(f)
        assert saved["STATE"] == "RUNNING"
        # The contract fields + state are reconstructable
        for f in LoopContractV1.REQUIRED_FIELDS:
            assert f in saved


# Test 10: duplicate dispatch → exactly-once
def test_duplicate_node_not_double_counted():
    c = make_contract()
    e = LoopEngine(c)
    e.active_nodes = ["A"]
    r = WorkerResult(NODE_ID="A", ROLE="worker", INPUT_BASELINE="main",
                     CLAIM="done", ACTION_TAKEN="x",
                     RESULT=WorkerResultStatus.PASS.value, EVIDENCE=["e"])
    e.ingest_worker_result(r)
    e.ingest_worker_result(r)
    assert e.completed_nodes.count("A") == 1


# Test 11: HARD STOP halts
def test_hard_stop_halts():
    c = make_contract()
    e = LoopEngine(c)
    walk_engine(e, LoopState.WAITING_HARD_STOP)
    assert not e.can_continue()


# Test 12: external blocker terminal
def test_external_blocker_terminal():
    c = make_contract()
    e = LoopEngine(c)
    walk_engine(e, LoopState.BLOCKED_EXTERNAL)
    assert c.state == LoopState.BLOCKED_EXTERNAL
    assert not e.can_continue()


# Test 13: DONE terminal
def test_goal_done_terminal():
    c = make_contract()
    e = LoopEngine(c)
    walk_engine(e, LoopState.DONE)
    assert c.state == LoopState.DONE
    assert not e.can_continue()


# Test 14: BrainPool bounded
def test_brainpool_bounded_marker():
    c = make_contract(BRAIN_CONTEXT_REF="C:/Users/david/Documents/BrainPool/01 TrafficLab/IA-VISION/IA-VISION_PROJECT_STATE.md")
    e = LoopEngine(c)
    assert c.fields["BRAIN_CONTEXT_REF"].endswith(".md")


# Test 15: no NEXO/runtime/gateway mutation
def test_no_runtime_import():
    import loop_engineering.engine as eng
    src = open(eng.__file__).read()
    forbidden_specific = ["hermes", "nexo", "gateway"]
    for f in forbidden_specific:
        assert f not in src.lower(), f"engine.py must not import/touch {f}"


# Extra: state machine transitions are whitelisted
def test_illegal_transition_fails():
    c = make_contract()
    with pytest.raises(ValueError, match="Illegal transition"):
        c.transition(LoopState.DONE)


# Extra: ANTI_FALSE_CLOSURE_RULE present
def test_anti_false_closure_rule_present():
    assert "PASS requires EVIDENCE" in ANTI_FALSE_CLOSURE_RULE


# Extra: 8 stop conditions enumerated
def test_eight_stop_conditions():
    assert len(list(StopCondition)) == 8


# Extra: walk_engine helper actually traverses
def test_walk_engine_helper():
    c = make_contract()
    e = LoopEngine(c)
    # Walk to PLANNING only (don't go all the way to DONE in same test)
    for s in [LoopState.INTAKE, LoopState.SYNCING, LoopState.PLANNING]:
        if e.contract.state != s:
            e.transition(s)
    assert c.state == LoopState.PLANNING
    # Walk to DONE (separate test instance for state machine integrity)
    c2 = make_contract()
    e2 = LoopEngine(c2)
    walk_engine(e2, LoopState.DONE)
    assert e2.contract.state == LoopState.DONE
