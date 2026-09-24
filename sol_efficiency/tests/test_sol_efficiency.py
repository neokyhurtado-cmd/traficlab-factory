import json
from pathlib import Path

import pytest

from sol_efficiency import (
    ActionFusion,
    ContextCompactor,
    EvidenceReducer,
    ObservationIntegrityError,
    ObservationPack,
    Verification,
)
from loop_engineering.contracts.loop_contract import LoopContractV1, StopCondition
from loop_engineering.contracts.worker_result import WorkerResult, WorkerResultStatus
from loop_engineering.engine import LoopEngine, make_loop_id


def make_contract():
    return LoopContractV1(**{
        "LOOP_ID": make_loop_id("sol"),
        "GOAL_ID": "G-sol",
        "GOAL_OBJECTIVE": "efficiency test",
        "SOURCE_OF_TRUTH": "test",
        "CANONICAL_BASELINE": "main@HEAD",
        "TRIGGER": "test",
        "CURRENT_ITERATION": 0,
        "CURRENT_GATE": "G0",
        "DEPENDENCY_GRAPH": {"A": []},
        "ACTIVE_NODES": [],
        "ELIGIBLE_NODES": ["A"],
        "BLOCKED_NODES": [],
        "ACTIVE_WRITERS": [],
        "READ_ONLY_WORKERS": [],
        "RESOURCE_OWNERS": {},
        "STATE_SNAPSHOT_REF": "snap.json",
        "BRAIN_CONTEXT_REF": "none",
        "LAST_MATERIAL_EVENT": "start",
        "NEXT_SAFE_ACTION": "run A",
        "VERIFY_POLICY": "auto",
        "STOP_CONDITIONS": [s.value for s in StopCondition],
        "ESCALATION_CONDITIONS": [],
        "CHECKPOINT_POLICY": "per_iteration",
        "FINAL_ACCEPTANCE": "A PASS",
    })


def test_observation_pack_exact_recall_and_dedup(tmp_path):
    pack = ObservationPack(tmp_path / "obs", threshold_bytes=10)
    text = "alpha\nbeta\ngamma\n"
    a = pack.archive(text, label="one")
    b = pack.archive(text, label="two")
    assert a.sha256 == b.sha256
    assert a.path == b.path
    assert pack.verify(a.handle)
    assert pack.recall(a.handle, start_line=2, end_line=3) == "beta\ngamma"


def test_observation_pack_tamper_fails_closed(tmp_path):
    pack = ObservationPack(tmp_path / "obs")
    ref = pack.archive("trusted\ntext")
    Path(ref.path).write_text("tampered", encoding="utf-8")
    with pytest.raises(ObservationIntegrityError):
        pack.recall(ref.handle)


def test_evidence_reducer_only_surfaces_verified_exact_lines(tmp_path):
    pack = ObservationPack(tmp_path / "obs")
    reducer = EvidenceReducer(pack)
    text = "setup\nWARNING cache cold\nmiddle\nAssertionError expected 2 got 3\nend"
    digest = reducer.reduce(text)
    assert digest.verified
    assert [f.line_no for f in digest.findings] == [2, 4]
    assert all(
        pack.recall(
            digest.observation.handle,
            start_line=f.line_no,
            end_line=f.line_no,
        ) == f.text
        for f in digest.findings
    )


def test_action_fusion_verifies_immediately():
    trace = []
    result = ActionFusion.run(
        "write+verify",
        lambda: trace.append("action") or 7,
        lambda value: trace.append("verify") or Verification(value == 7, "ok"),
    )
    assert trace == ["action", "verify"]
    assert result.status == "PASS"


def test_action_fusion_does_not_claim_pass_on_failed_verification():
    result = ActionFusion.run("x", lambda: 1, lambda _: False)
    assert result.status == "VERIFICATION_FAILED"


def test_context_compactor_keeps_only_live_resume_state(tmp_path):
    c = ContextCompactor(tmp_path / "ctx")
    cp = c.compact({
        "LOOP_ID": "L1",
        "GOAL_ID": "G1",
        "STATE": "RUNNING",
        "CURRENT_GATE": "G2",
        "CANONICAL_BASELINE": "abc",
        "COMPLETED_NODES": ["A"],
        "FAILED_NODES": [],
        "BLOCKED_NODES": [],
        "ACTIVE_NODES": ["B"],
        "LAST_MATERIAL_EVENT": "A passed",
        "NEXT_SAFE_ACTION": "run B",
        "SNAPSHOT_SHA": "deadbeef",
        "HUGE_TRANSCRIPT": "x" * 100000,
    }, evidence_handles=["obs://sha256/" + "a" * 64])
    raw = json.loads((tmp_path / "ctx" / "L1.json").read_text())
    assert raw["state"] == "RUNNING"
    assert "HUGE_TRANSCRIPT" not in raw
    assert cp.evidence_handles


def test_loop_enforce_replaces_only_large_evidence_and_recall_is_exact(tmp_path):
    evidence = "setup\n" + ("noise\n" * 200) + "ERROR exploded\n"
    snap = tmp_path / "snap.json"
    e = LoopEngine(
        make_contract(),
        snapshot_path=str(snap),
        sol_mode="enforce",
        sol_root=str(tmp_path / "sol"),
        sol_threshold_bytes=64,
    )
    r = WorkerResult(
        NODE_ID="A",
        ROLE="worker",
        INPUT_BASELINE="main",
        CLAIM="done",
        ACTION_TAKEN="tested",
        EVIDENCE=[evidence, "small.txt"],
        RESULT=WorkerResultStatus.PASS.value,
    )
    e.ingest_worker_result(r)
    assert r.EVIDENCE[0].startswith("obs://sha256/")
    assert r.EVIDENCE[1] == "small.txt"
    handle = r.EVIDENCE[0].split()[0]
    assert e.recall_evidence(handle) == evidence
    saved = json.loads(snap.read_text())
    assert saved["SOL_EFFICIENCY"]["observations_packed"] == 1
    assert saved["SOL_CONTEXT_CHECKPOINT"]["evidence_handles"] == [handle]


def test_loop_shadow_measures_without_mutating_worker_evidence(tmp_path):
    evidence = "WARNING x\n" + ("detail\n" * 100)
    e = LoopEngine(
        make_contract(),
        snapshot_path=str(tmp_path / "snap.json"),
        sol_mode="shadow",
        sol_root=str(tmp_path / "sol"),
        sol_threshold_bytes=32,
    )
    r = WorkerResult(
        NODE_ID="A",
        ROLE="worker",
        INPUT_BASELINE="main",
        CLAIM="done",
        ACTION_TAKEN="tested",
        EVIDENCE=[evidence],
        RESULT=WorkerResultStatus.PASS.value,
    )
    before = list(r.EVIDENCE)
    e.ingest_worker_result(r)
    assert r.EVIDENCE == before
    assert e._sol_metrics["observations_packed"] == 1


def test_pass_without_evidence_still_rejected_before_compaction(tmp_path):
    e = LoopEngine(
        make_contract(),
        snapshot_path=str(tmp_path / "snap.json"),
        sol_mode="enforce",
        sol_root=str(tmp_path / "sol"),
        sol_threshold_bytes=1,
    )
    r = WorkerResult(
        NODE_ID="A",
        ROLE="worker",
        INPUT_BASELINE="main",
        CLAIM="done",
        ACTION_TAKEN="nothing",
        EVIDENCE=[],
        RESULT=WorkerResultStatus.PASS.value,
    )
    with pytest.raises(ValueError, match="PASS requires at least one EVIDENCE"):
        e.ingest_worker_result(r)
