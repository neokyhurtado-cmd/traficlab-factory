"""Adversarial tests for HUMAN_GO_GATE_V2 — P1 v3 (N1..N5 gaps closed).

This test suite is split into:
- Original 35 tests (updated for new API)
- N1..N5 specific adversarial tests
- N5 fake executor integration test

Run with: python tests/test_human_go_gate_v2.py
"""
import sys
import os
import subprocess
import json
import tempfile
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from human_go_gate_v2 import (
    HUMAN_GO_GATE_V2, ProvenanceRegistry, ReplayStore, FakeMergeExecutor
)


def _registry_with_event(event_id="evt_test", action="merge", repo="neokyhurtado-cmd/traficlab-factory",
                         pr_number=15, expected_head=None):
    """Build a registry with a single pre-verified event."""
    if expected_head is None:
        expected_head = "a" * 40
    reg = ProvenanceRegistry(secret_key="default")
    reg.add_event({
        "event_id": event_id,
        "owner_principal": "david@example.com",
        "action": action,
        "repo": repo,
        "pr_number": pr_number,
        "expected_head": expected_head,
        "issued_at": "2026-09-10T04:00:00+00:00",
        "expires_at": "2099-12-31T23:59:59+00:00",  # long-lived for tests
    })
    return reg


def _gate_with_store(event_id="evt_test", expected_head=None, pr_number=15, action="merge",
                      repo="neokyhurtado-cmd/traficlab-factory"):
    """Build a gate with registry + replay store."""
    if expected_head is None:
        expected_head = "a" * 40
    reg = ProvenanceRegistry(secret_key="default")
    reg.add_event({
        "event_id": event_id,
        "owner_principal": "david@example.com",
        "action": action,
        "repo": repo,
        "pr_number": pr_number,
        "expected_head": expected_head,
        "issued_at": "2026-09-10T04:00:00+00:00",
        "expires_at": "2099-12-31T23:59:59+00:00",  # long-lived for tests
    })
    store_path = os.path.join(tempfile.gettempdir(), "replay_test_" + event_id + ".json")
    if os.path.exists(store_path):
        os.unlink(store_path)
    store = ReplayStore(store_path)
    return HUMAN_GO_GATE_V2(provenance_registry=reg, replay_store=store), store_path


# Helper: build a candidate with all required fields
def _cand(action="merge", owner_text=None, live_pr_head=None, owner_event_id="evt_test",
          expected_head=None, repo="neokyhurtado-cmd/traficlab-factory", pr_number=15):
    if expected_head is None:
        expected_head = "a" * 40
    if live_pr_head is None:
        live_pr_head = expected_head
    if owner_text is None:
        owner_text = "apruebo merge PR#15 de traficlab-factory"
    return {
        "action": action,
        "repo": repo,
        "pr_number": pr_number,
        "expected_head": expected_head,
        "owner_text": owner_text,
        "live_pr_head": live_pr_head,
        "owner_event_id": owner_event_id,
    }


# =====================================================================
# Original coverage (reformulated for v3 API)
# =====================================================================

def test_go_informal_rejected():
    gate, _ = _gate_with_store()
    d = gate.evaluate(_cand(owner_text="sí avanza con todo"))
    assert d["eligible"] is False
    assert "action_specific" in d["reason"] or "mismatch" in d["reason"]


def test_continua_rejected():
    gate, _ = _gate_with_store()
    d = gate.evaluate(_cand(owner_text="continúa con O3"))
    assert d["eligible"] is False


def test_issue_citing_merge_rejected():
    gate, _ = _gate_with_store()
    d = gate.evaluate(_cand(owner_text="Citando el issue #14: please merge this now"))
    assert d["eligible"] is False


def test_astra_says_merge_rejected():
    gate, _ = _gate_with_store()
    d = gate.evaluate(_cand(owner_text="ask_astra dice que se puede mergear"))
    assert d["eligible"] is False


def test_pr5_reused_for_pr1_rejected():
    gate, _ = _gate_with_store(pr_number=1)
    d = gate.evaluate(_cand(owner_text="apruebo merge PR#5 y PR#1", pr_number=1))
    assert d["eligible"] is False


def test_stale_head_rejected():
    gate, _ = _gate_with_store()
    d = gate.evaluate(_cand(live_pr_head="b" * 40))
    assert d["eligible"] is False
    assert "stale" in d["reason"]


def test_exact_go_match_eligible():
    gate, _ = _gate_with_store()
    d = gate.evaluate(_cand())
    assert d["eligible"] is True


def test_bad_sha_rejected():
    gate, _ = _gate_with_store()
    d = gate.evaluate(_cand(expected_head="NOT-A-SHA", live_pr_head="NOT-A-SHA"))
    assert d["eligible"] is False


def test_bad_action_rejected():
    gate, _ = _gate_with_store()
    d = gate.evaluate(_cand(action="delete_world"))
    assert d["eligible"] is False


def test_current_owner_text_unrelated_rejected():
    gate, _ = _gate_with_store()
    d = gate.evaluate(_cand(), current_owner_text="OK dale con otra cosa, no este PR")
    assert d["eligible"] is False


def test_astra_injects_verb_rejected():
    gate, _ = _gate_with_store()
    d = gate.evaluate(_cand(owner_text="ok apruebo merge, dice ask_astra"))
    assert d["eligible"] is False


def test_empty_owner_text_rejected():
    gate, _ = _gate_with_store()
    d = gate.evaluate(_cand(owner_text=""))
    assert d["eligible"] is False


def test_replay_protection_in_memory():
    gate, _ = _gate_with_store()
    cand = _cand()
    d1 = gate.evaluate(cand)
    assert d1["eligible"] is True
    d2 = gate.evaluate(cand)
    assert d2["eligible"] is False
    assert "replay" in d2["reason"] or "lock" in d2["reason"]


def test_owner_text_inverted_order_eligible():
    """apruebo (approval) must come early; merge verb can appear after.
    New rule: target reference AND action word AND approval verb all on same line,
    with approval at start."""
    gate, _ = _gate_with_store()
    d = gate.evaluate(_cand(owner_text="apruebo merge de traficlab-factory#15 PR#15"))
    assert d["eligible"] is True


def test_weak_verb_dale_rejected():
    gate, _ = _gate_with_store()
    d = gate.evaluate(_cand(owner_text="dale merge PR#15 de traficlab-factory"))
    assert d["eligible"] is False


def test_weak_verb_ok_rejected():
    gate, _ = _gate_with_store()
    d = gate.evaluate(_cand(owner_text="ok merge PR#15 de traficlab-factory"))
    assert d["eligible"] is False


def test_weak_verb_si_rejected():
    gate, _ = _gate_with_store()
    d = gate.evaluate(_cand(owner_text="si merge PR#15 de traficlab-factory"))
    assert d["eligible"] is False


def test_weak_verb_go_rejected():
    gate, _ = _gate_with_store()
    d = gate.evaluate(_cand(owner_text="go merge PR#15 de traficlab-factory"))
    assert d["eligible"] is False


def test_weak_verb_adelante_rejected():
    gate, _ = _gate_with_store()
    d = gate.evaluate(_cand(owner_text="adelante merge PR#15 de traficlab-factory"))
    assert d["eligible"] is False


def test_action_bind_merge_to_deploy_rejected():
    """mergeo text cannot authorize deploy."""
    gate, _ = _gate_with_store(action="deploy", pr_number=5)
    d = gate.evaluate(_cand(action="deploy", owner_text="mergeo PR#5 de traficlab-factory",
                              owner_event_id="evt_test", pr_number=5))
    assert d["eligible"] is False


def test_action_bind_deploy_to_merge_rejected():
    """despliego text cannot authorize merge."""
    gate, _ = _gate_with_store()
    d = gate.evaluate(_cand(action="merge", owner_text="despliego PR#15 de traficlab-factory"))
    assert d["eligible"] is False


def test_secret_write_requires_explicit():
    gate, _ = _gate_with_store(action="secret_write", pr_number=5)
    d = gate.evaluate(_cand(action="secret_write",
                             owner_text="apruebo secret_write PR#5 en traficlab-factory",
                             owner_event_id="evt_test", pr_number=5))
    assert d["eligible"] is True


def test_secret_write_without_explicit_rejected():
    gate, _ = _gate_with_store(action="secret_write", pr_number=5)
    d = gate.evaluate(_cand(action="secret_write",
                             owner_text="apruebo PR#5 secret en traficlab-factory",
                             owner_event_id="evt_test", pr_number=5))
    assert d["eligible"] is False


def test_missing_live_pr_head_rejected():
    gate, _ = _gate_with_store()
    cand = _cand()
    del cand["live_pr_head"]
    d = gate.evaluate(cand)
    assert d["eligible"] is False
    assert d["reason"] == "live_pr_head_required"


def test_repo_suffix_collision_rejected():
    gate, _ = _gate_with_store()
    d = gate.evaluate(_cand(owner_text="apruebo merge PR#15 de old-traficlab-factory-backup"))
    assert d["eligible"] is False
    assert d["reason"] == "repo_collision_in_owner_text"


def test_repo_prefix_collision_rejected():
    gate, _ = _gate_with_store()
    d = gate.evaluate(_cand(owner_text="apruebo merge PR#15 de my-traficlab-factory"))
    assert d["eligible"] is False
    assert d["reason"] == "repo_collision_in_owner_text"


def test_repo_exact_match_eligible():
    gate, _ = _gate_with_store()
    d = gate.evaluate(_cand())
    assert d["eligible"] is True


def test_result_does_not_echo_owner_text():
    gate, _ = _gate_with_store()
    sensitive = "apruebo merge PR#15 de traficlab-factory. SECRET=hunter2 PWD=x"
    d = gate.evaluate(_cand(owner_text=sensitive))
    serialized = json.dumps(d)
    assert "SECRET" not in serialized
    assert "hunter2" not in serialized
    assert sensitive not in serialized


def test_happy_path_explicit_go_match_eligible():
    gate, _ = _gate_with_store()
    d = gate.evaluate(_cand())
    assert d["eligible"] is True
    assert d["reason"] == "all_gates_passed"


# =====================================================================
# N1: provenance falsificable — now requires owner_event_id + registry
# =====================================================================

def test_n1_no_owner_event_id_rejected():
    """Caller cannot forge provenance without owner_event_id."""
    reg = ProvenanceRegistry(secret_key="default")
    store = ReplayStore(os.path.join(tempfile.gettempdir(), "n1_test.json"))
    gate = HUMAN_GO_GATE_V2(provenance_registry=reg, replay_store=store)
    cand = _cand()
    del cand["owner_event_id"]
    d = gate.evaluate(cand)
    assert d["eligible"] is False
    assert d["reason"] == "owner_event_id_missing"


def test_n1_unknown_event_id_rejected():
    """Caller cannot guess a valid event_id."""
    gate, _ = _gate_with_store()
    cand = _cand(owner_event_id="evt_fabricated_by_caller")
    d = gate.evaluate(cand)
    assert d["eligible"] is False
    assert d["reason"] == "owner_event_id_unknown"


def test_n1_event_for_different_action_rejected():
    """Event authorizes merge; candidate requests deploy."""
    reg = _registry_with_event(action="merge", pr_number=15)
    store = ReplayStore(os.path.join(tempfile.gettempdir(), "n1b_test.json"))
    gate = HUMAN_GO_GATE_V2(provenance_registry=reg, replay_store=store)
    cand = _cand(action="deploy",
                 owner_text="apruebo deploy PR#15 de traficlab-factory",
                 owner_event_id="evt_test")
    d = gate.evaluate(cand)
    assert d["eligible"] is False
    assert d["reason"] == "owner_event_action_mismatch"


def test_n1_event_for_different_pr_rejected():
    """Event for PR#5; candidate requests PR#15."""
    reg = _registry_with_event(pr_number=5)
    store = ReplayStore(os.path.join(tempfile.gettempdir(), "n1c_test.json"))
    gate = HUMAN_GO_GATE_V2(provenance_registry=reg, replay_store=store)
    cand = _cand(pr_number=15, owner_text="apruebo merge PR#15 de traficlab-factory",
                 owner_event_id="evt_test")
    d = gate.evaluate(cand)
    assert d["eligible"] is False
    assert d["reason"] == "owner_event_pr_mismatch"


def test_n1_expired_event_rejected():
    """Expired event cannot authorize."""
    reg = ProvenanceRegistry(secret_key="default")
    reg.add_event({
        "event_id": "evt_expired",
        "owner_principal": "david@example.com",
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 15,
        "expected_head": "a" * 40,
        "issued_at": "2020-01-01T00:00:00+00:00",
        "expires_at": "2020-01-02T00:00:00+00:00",  # expired
    })
    store = ReplayStore(os.path.join(tempfile.gettempdir(), "n1d_test.json"))
    gate = HUMAN_GO_GATE_V2(provenance_registry=reg, replay_store=store)
    cand = _cand(owner_event_id="evt_expired")
    d = gate.evaluate(cand)
    assert d["eligible"] is False
    assert d["reason"] == "owner_event_expired"


def test_n1_valid_event_for_exact_target_eligible():
    persist = os.path.join(tempfile.gettempdir(), "n1e_test_unique.json")
    try:
        os.unlink(persist)
    except OSError:
        pass
    reg = ProvenanceRegistry(secret_key="default")
    reg.add_event({
        "event_id": "evt_unique_1",
        "owner_principal": "david",
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 15,
        "expected_head": "a" * 40,
        "issued_at": "2026-09-10T04:00:00+00:00",
        "expires_at": "2099-12-31T23:59:59+00:00",
    })
    gate = HUMAN_GO_GATE_V2(provenance_registry=reg, replay_store=ReplayStore(persist))
    cand = {
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 15,
        "expected_head": "a" * 40,
        "owner_text": "apruebo merge PR#15 de traficlab-factory",
        "live_pr_head": "a" * 40,
        "owner_event_id": "evt_unique_1",
    }
    d = gate.evaluate(cand)
    assert d["eligible"] is True
    try:
        os.unlink(persist)
    except OSError:
        pass


# =====================================================================
# N2: generic 'apruebo' without action word cannot authorize
# =====================================================================

def test_n2_generic_apruebo_no_action_rejected_for_merge():
    """Generic 'apruebo PR#15...' without 'merge' word cannot authorize merge."""
    gate, _ = _gate_with_store()
    d = gate.evaluate(_cand(owner_text="apruebo PR#15 de traficlab-factory"))
    assert d["eligible"] is False
    assert d["reason"] == "owner_text_not_action_specific"


def test_n2_apruebo_merge_eligible():
    """Explicit 'apruebo merge PR#15' works for merge."""
    gate, _ = _gate_with_store()
    d = gate.evaluate(_cand(owner_text="apruebo merge PR#15 de traficlab-factory"))
    assert d["eligible"] is True


def test_n2_apruebo_deploy_does_not_authorize_merge():
    """apruebo deploy does not authorize merge."""
    gate, _ = _gate_with_store()
    d = gate.evaluate(_cand(action="merge", owner_text="apruebo deploy PR#15 de traficlab-factory"))
    assert d["eligible"] is False


def test_n2_apruebo_release_does_not_authorize_merge():
    gate, _ = _gate_with_store()
    d = gate.evaluate(_cand(action="merge", owner_text="apruebo release PR#15 de traficlab-factory"))
    assert d["eligible"] is False


def test_n2_apruebo_merge_does_not_authorize_deploy():
    """apruebo merge does not authorize deploy even though 'apruebo' is generic."""
    gate, _ = _gate_with_store(action="deploy", pr_number=15)
    cand = _cand(action="deploy",
                 owner_text="apruebo merge PR#15 de traficlab-factory",
                 owner_event_id="evt_test", pr_number=15)
    d = gate.evaluate(cand)
    assert d["eligible"] is False


# =====================================================================
# N3: current_owner_text must authorize same action+repo+PR
# =====================================================================

def test_n3_cot_authorizes_different_action_rejected():
    """Latest message authorizes deploy; candidate is merge."""
    gate, _ = _gate_with_store()
    d = gate.evaluate(
        _cand(action="merge"),
        current_owner_text="apruebo deploy PR#15 de traficlab-factory",
    )
    assert d["eligible"] is False
    assert "current_owner_text_action_mismatch" in d["reason"]


def test_n3_cot_authorizes_same_action_eligible():
    gate, _ = _gate_with_store()
    d = gate.evaluate(
        _cand(action="merge"),
        current_owner_text="apruebo merge PR#15 de traficlab-factory",
    )
    assert d["eligible"] is True


def test_n3_cot_unrelated_rejected():
    gate, _ = _gate_with_store()
    d = gate.evaluate(
        _cand(),
        current_owner_text="ok dale con otra cosa",
    )
    assert d["eligible"] is False


# =====================================================================
# N4: replay persistence mandatory + atomic
# =====================================================================

def test_n4_no_replay_store_fails_closed():
    """Without replay_store, the gate must reject (fail-closed)."""
    reg = _registry_with_event()
    gate = HUMAN_GO_GATE_V2(provenance_registry=reg, replay_store=None)
    d = gate.evaluate(_cand())
    assert d["eligible"] is False
    assert d["reason"] == "replay_store_not_configured"


def test_n4_concurrent_subprocess_only_one_eligible():
    """Two concurrent subprocesses sharing a replay store: only one can be ELIGIBLE."""
    TMP = tempfile.gettempdir()
    persist = os.path.join(TMP, "n4_concurrent_test.json")
    if os.path.exists(persist):
        os.unlink(persist)

    # Set up registry file
    events_file = os.path.join(TMP, "n4_concurrent_events.json")
    with open(events_file, "w") as f:
        json.dump([{
            "event_id": "evt_test",
            "owner_principal": "david",
            "action": "merge",
            "repo": "neokyhurtado-cmd/traficlab-factory",
            "pr_number": 15,
            "expected_head": "a" * 40,
            "issued_at": "2026-09-10T04:00:00+00:00",
            "expires_at": "2099-12-31T23:59:59+00:00",
        }], f)

    cand_path = os.path.join(TMP, "n4_concurrent_cand.json")
    with open(cand_path, "w") as f:
        json.dump({
            "action": "merge",
            "repo": "neokyhurtado-cmd/traficlab-factory",
            "pr_number": 15,
            "expected_head": "a" * 40,
            "owner_text": "apruebo merge PR#15 de traficlab-factory",
            "live_pr_head": "a" * 40,
            "owner_event_id": "evt_test",
        }, f)

    src_path = os.path.join(os.path.dirname(__file__), "..", "src", "human_go_gate_v2.py")

    def run():
        r = subprocess.run(
            ["python", src_path, cand_path, "--events", events_file, "--replay-store", persist],
            capture_output=True, text=True, timeout=30,
        )
        return r.returncode, r.stdout

    threads = [threading.Thread(target=lambda r=[]: r.append(run())) for _ in range(2)]
    results = [[] for _ in range(2)]
    for i, t in enumerate(threads):
        t._args = (results[i],)
        t.start()
    for t in threads:
        t.join()

    eligibles = []
    for r in results:
        if r:
            rc, stdout = r[0]
            try:
                d = json.loads(stdout)
                eligibles.append(d.get("eligible"))
            except:
                eligibles.append(None)

    # Exactly ONE should be eligible, the other should be replay/lock failure
    n_eligible = sum(1 for e in eligibles if e is True)
    print(f"  eligibles: {eligibles}")
    assert n_eligible == 1, f"expected 1 eligible, got {n_eligible}: {eligibles}"

    for f in [persist, events_file, cand_path]:
        if os.path.exists(f):
            os.unlink(f)


def test_n4_sequential_replay_protection():
    """Sequential: first eligible, second rejected."""
    persist = os.path.join(tempfile.gettempdir(), "n4_sequential_test.json")
    if os.path.exists(persist):
        os.unlink(persist)
    reg = _registry_with_event()
    gate = HUMAN_GO_GATE_V2(provenance_registry=reg, replay_store=ReplayStore(persist))
    cand = _cand()
    d1 = gate.evaluate(cand)
    d2 = gate.evaluate(cand)
    assert d1["eligible"] is True
    assert d2["eligible"] is False
    assert "replay" in d2["reason"]
    os.unlink(persist)


# =====================================================================
# N5: enforcement integration with FakeMergeExecutor
# =====================================================================

def test_n5_fake_executor_blocks_merge_without_gate():
    """The fake executor refuses to merge anything that isn't gate-eligible."""
    reg = _registry_with_event()
    persist = os.path.join(tempfile.gettempdir(), "n5_test.json")
    if os.path.exists(persist):
        os.unlink(persist)
    gate = HUMAN_GO_GATE_V2(provenance_registry=reg, replay_store=ReplayStore(persist))
    executor = FakeMergeExecutor(gate)

    # Attempt 1: ineligible candidate (no action word in owner_text)
    bad = _cand(owner_text="ok dale merge PR#15 de traficlab-factory")
    result = executor.merge(bad)
    assert result["merged"] is False
    assert result["reason"] in ("no_action_specific_authorization_verb",
                                "owner_text_not_action_specific")

    # Attempt 2: eligible candidate (explicit action word)
    good = _cand(owner_text="apruebo merge PR#15 de traficlab-factory")
    result = executor.merge(good)
    assert result["merged"] is True
    assert result["fingerprint"] is not None
    assert len(executor.completed_merges) == 1

    # Attempt 3: replay of attempt 2 — should be blocked by replay protection
    result = executor.merge(good)
    assert result["merged"] is False
    assert "replay" in result["reason"] or "lock" in result["reason"]
    assert len(executor.completed_merges) == 1  # No additional merge

    os.unlink(persist)


def test_n5_fake_executor_blocks_forged_provenance():
    reg = _registry_with_event()
    persist = os.path.join(tempfile.gettempdir(), "n5b_test.json")
    try:
        os.unlink(persist)
    except OSError:
        pass
    gate = HUMAN_GO_GATE_V2(provenance_registry=reg, replay_store=ReplayStore(persist))
    executor = FakeMergeExecutor(gate)
    forged = _cand(owner_event_id="evt_caller_forged")
    result = executor.merge(forged)
    assert result["merged"] is False
    assert "unknown" in result["reason"] or "event_id" in result["reason"]
    assert len(executor.completed_merges) == 0
    try:
        os.unlink(persist)
    except OSError:
        pass


def test_n5_fake_executor_blocks_action_swap():
    """Caller sets candidate action=deploy but event was for merge."""
    reg = _registry_with_event(action="merge", pr_number=15)
    persist = os.path.join(tempfile.gettempdir(), "n5c_test.json")
    try:
        os.unlink(persist)
    except OSError:
        pass
    gate = HUMAN_GO_GATE_V2(provenance_registry=reg, replay_store=ReplayStore(persist))
    executor = FakeMergeExecutor(gate)
    cand = _cand(action="deploy",
                 owner_text="apruebo deploy PR#15 de traficlab-factory",
                 owner_event_id="evt_test")
    result = executor.merge(cand)
    assert result["merged"] is False
    assert "event" in result["reason"]
    assert len(executor.completed_merges) == 0
    try:
        os.unlink(persist)
    except OSError:
        pass


# =====================================================================
# Driver
# =====================================================================

if __name__ == "__main__":
    tests = [(name, fn) for name, fn in globals().items()
             if name.startswith("test_") and callable(fn)]
    failures = []
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception as e:
            print(f"  FAIL  {name}: {type(e).__name__}: {e}")
            failures.append((name, e))
    print()
    print(f"{len(tests) - len(failures)}/{len(tests)} tests pass")
    if failures:
        sys.exit(1)
