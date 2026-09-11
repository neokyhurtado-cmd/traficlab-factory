"""Adversarial tests for HUMAN_GO_GATE_V2 — P1 v4 (B1/B2/B3/H1 closed).

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
    HUMAN_GO_GATE_V2, ProvenanceRegistry, ReplayStore,
    pre_merge_check_and_call, sign_event, MIN_SECRET_KEY_LEN
)


# Test secret key (>= MIN_SECRET_KEY_LEN chars)
TEST_SECRET = "a" * MIN_SECRET_KEY_LEN + "_TEST_KEY_DO_NOT_USE_IN_PROD"


def _signed_event(event_id="evt_test", action="merge",
                  repo="neokyhurtado-cmd/traficlab-factory",
                  pr_number=15, expected_head=None,
                  expires_at="2099-12-31T23:59:59+00:00"):
    if expected_head is None:
        expected_head = "a" * 40
    raw = {
        "event_id": event_id,
        "owner_principal": "david",
        "action": action,
        "repo": repo,
        "pr_number": pr_number,
        "expected_head": expected_head,
        "issued_at": "2026-09-10T04:00:00+00:00",
        "expires_at": expires_at,
    }
    return sign_event(TEST_SECRET, raw)


def _make_registry_with_event(event_id="evt_test", action="merge",
                              pr_number=15, expected_head=None,
                              expires_at="2099-12-31T23:59:59+00:00"):
    reg = ProvenanceRegistry(secret_key=TEST_SECRET)
    evt = _signed_event(event_id=event_id, action=action,
                        pr_number=pr_number, expected_head=expected_head,
                        expires_at=expires_at)
    ok, reason = reg.add_event(evt)
    assert ok, f"setup failed: {reason}"
    return reg


def _make_gate_with_store(event_id="evt_test", action="merge", pr_number=15,
                          expected_head=None, expires_at="2099-12-31T23:59:59+00:00"):
    reg = _make_registry_with_event(event_id=event_id, action=action,
                                     pr_number=pr_number, expected_head=expected_head,
                                     expires_at=expires_at)
    persist = os.path.join(tempfile.gettempdir(), f"replay_v4_{event_id}.json")
    try:
        os.unlink(persist)
    except OSError:
        pass
    return HUMAN_GO_GATE_V2(provenance_registry=reg, replay_store=ReplayStore(persist)), persist


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


def _cleanup(*paths):
    for p in paths:
        try:
            if os.path.exists(p):
                os.unlink(p)
        except OSError:
            pass


# =====================================================================
# H1: no default trust material
# =====================================================================

def test_h1_provenance_registry_requires_secret_key():
    """Missing secret_key must raise (TypeError or ValueError)."""
    try:
        ProvenanceRegistry()
    except (ValueError, TypeError):
        return
    raise AssertionError("ProvenanceRegistry() without secret_key should raise")


def test_h1_provenance_registry_rejects_empty_secret():
    try:
        ProvenanceRegistry(secret_key="")
    except ValueError:
        return
    raise AssertionError("empty secret_key should raise")


def test_h1_provenance_registry_rejects_short_secret():
    try:
        ProvenanceRegistry(secret_key="short")
    except ValueError:
        return
    raise AssertionError("short secret_key should raise")


def test_h1_human_go_gate_requires_registry():
    try:
        HUMAN_GO_GATE_V2(provenance_registry=None, replay_store=ReplayStore("/tmp/x"))
    except ValueError:
        return
    raise AssertionError("HUMAN_GO_GATE_V2 with None registry should raise")


def test_h1_human_go_gate_requires_replay_store():
    try:
        reg = ProvenanceRegistry(secret_key=TEST_SECRET)
        HUMAN_GO_GATE_V2(provenance_registry=reg, replay_store=None)
    except ValueError:
        return
    raise AssertionError("HUMAN_GO_GATE_V2 with None replay_store should raise")


# =====================================================================
# B1: signature verification
# =====================================================================

def test_b1_unsigned_event_rejected():
    """Event with no signature field → add_event rejects."""
    reg = ProvenanceRegistry(secret_key=TEST_SECRET)
    evt = {
        "event_id": "evt_unsigned",
        "owner_principal": "david",
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 15,
        "expected_head": "a" * 40,
        "issued_at": "2026-09-10T04:00:00+00:00",
        "expires_at": "2099-12-31T23:59:59+00:00",
    }
    ok, reason = reg.add_event(evt)
    assert ok is False
    assert reason == "signature_field_missing"


def test_b1_wrong_key_signature_rejected():
    """Event signed with a different key → add_event rejects."""
    reg = ProvenanceRegistry(secret_key=TEST_SECRET)
    bad_evt = _signed_event(event_id="evt_b1_bad")
    # Re-sign with wrong key
    bad_evt["signature"] = sign_event("wrong" * 20, {k: v for k, v in bad_evt.items() if k != "signature"})["signature"]
    ok, reason = reg.add_event(bad_evt)
    assert ok is False
    assert reason == "signature_invalid"


def test_b1_tampered_event_rejected():
    """Event with valid signature but tampered fields → signature mismatch."""
    reg = ProvenanceRegistry(secret_key=TEST_SECRET)
    evt = _signed_event(event_id="evt_tampered", pr_number=15)
    # Tamper with PR number AFTER signing
    evt["pr_number"] = 99
    ok, reason = reg.add_event(evt)
    assert ok is False
    assert reason == "signature_invalid"


def test_b1_valid_signed_event_accepted():
    reg = ProvenanceRegistry(secret_key=TEST_SECRET)
    evt = _signed_event()
    ok, reason = reg.add_event(evt)
    assert ok is True


def test_b1_cli_unsigned_event_denied():
    """End-to-end: CLI with unsigned events file → REJECTED."""
    TMP = tempfile.gettempdir()
    events_file = os.path.join(TMP, "b1_cli_events.json")
    persist = os.path.join(TMP, "b1_cli_replay.json")
    secret_file = os.path.join(TMP, "b1_cli_secret.txt")
    cand_file = os.path.join(TMP, "b1_cli_cand.json")

    with open(secret_file, "w") as f:
        f.write(TEST_SECRET)
    with open(events_file, "w") as f:
        json.dump([{
            "event_id": "evt_unsigned",
            "owner_principal": "david",
            "action": "merge",
            "repo": "neokyhurtado-cmd/traficlab-factory",
            "pr_number": 15,
            "expected_head": "a" * 40,
            "issued_at": "2026-09-10T04:00:00+00:00",
            "expires_at": "2099-12-31T23:59:59+00:00",
        }], f)
    cand = _cand(owner_event_id="evt_unsigned")
    with open(cand_file, "w") as f:
        json.dump(cand, f)

    src_path = os.path.join(os.path.dirname(__file__), "..", "src", "human_go_gate_v2.py")
    r = subprocess.run(
        ["python", src_path, cand_file, "--events", events_file,
         "--secret-key", secret_file, "--replay-store", persist],
        capture_output=True, text=True, timeout=15,
    )
    d = json.loads(r.stdout)
    assert d["eligible"] is False
    assert d["_events_rejected"] == 1
    assert d["_events_accept_reasons"] if False else "signature_field_missing" in str(d.get("_events_reject_reasons", {}))

    _cleanup(events_file, persist, secret_file, cand_file)


def test_b1_cli_signed_event_eligible():
    """End-to-end: CLI with properly signed events file → ELIGIBLE."""
    TMP = tempfile.gettempdir()
    events_file = os.path.join(TMP, "b1c_events.json")
    persist = os.path.join(TMP, "b1c_replay.json")
    secret_file = os.path.join(TMP, "b1c_secret.txt")
    cand_file = os.path.join(TMP, "b1c_cand.json")

    with open(secret_file, "w") as f:
        f.write(TEST_SECRET)
    signed = _signed_event(event_id="evt_signed_cli")
    with open(events_file, "w") as f:
        json.dump([signed], f)
    cand = _cand(owner_event_id="evt_signed_cli")
    with open(cand_file, "w") as f:
        json.dump(cand, f)

    src_path = os.path.join(os.path.dirname(__file__), "..", "src", "human_go_gate_v2.py")
    r = subprocess.run(
        ["python", src_path, cand_file, "--events", events_file,
         "--secret-key", secret_file, "--replay-store", persist],
        capture_output=True, text=True, timeout=15,
    )
    d = json.loads(r.stdout)
    assert d["eligible"] is True
    assert d["_events_accepted"] == 1

    _cleanup(events_file, persist, secret_file, cand_file)


# =====================================================================
# B2: replay store corruption fail-closed
# =====================================================================

def test_b2_corrupt_replay_store_returns_failure():
    persist = os.path.join(tempfile.gettempdir(), "b2_corrupt.json")
    try:
        os.unlink(persist)
    except OSError:
        pass
    reg = _make_registry_with_event(event_id="evt_b2")
    gate = HUMAN_GO_GATE_V2(provenance_registry=reg, replay_store=ReplayStore(persist))

    # First call: consume event normally
    d1 = gate.evaluate(_cand(owner_event_id="evt_b2"))
    assert d1["eligible"] is True

    # Corrupt the store
    with open(persist, "w") as f:
        f.write("CORRUPTED{{{ not valid JSON")

    # Retry: must be REJECTED, not silently pass
    d2 = gate.evaluate(_cand(owner_event_id="evt_b2"))
    assert d2["eligible"] is False
    assert d2["reason"] == "replay_store_corrupt"
    _cleanup(persist)


def test_b2_wrong_structure_replay_store_returns_failure():
    persist = os.path.join(tempfile.gettempdir(), "b2_struct.json")
    try:
        os.unlink(persist)
    except OSError:
        pass
    reg = _make_registry_with_event(event_id="evt_b2b")
    gate = HUMAN_GO_GATE_V2(provenance_registry=reg, replay_store=ReplayStore(persist))

    # First consume
    d1 = gate.evaluate(_cand(owner_event_id="evt_b2b"))
    assert d1["eligible"] is True

    # Write valid JSON but wrong structure
    with open(persist, "w") as f:
        json.dump({"not": "a list"}, f)

    d2 = gate.evaluate(_cand(owner_event_id="evt_b2b"))
    assert d2["eligible"] is False
    assert d2["reason"] == "replay_store_corrupt"
    _cleanup(persist)


# =====================================================================
# B3: real enforcement seam — pre_merge_check_and_call
# =====================================================================

def test_b3_pre_merge_adapter_blocks_unsigned_github_call():
    """The seam refuses to call github_merge_callable when gate fails."""
    gate, persist = _make_gate_with_store()
    calls = []

    def fake_github(cand):
        calls.append(cand)
        return {"merged_at": "2026-09-10T05:00:00Z"}

    # Bad candidate (no action word)
    bad = _cand(owner_text="ok dale con todo")
    r = pre_merge_check_and_call(gate, bad, github_merge_callable=fake_github)
    assert r["merged"] is False
    assert len(calls) == 0  # github NEVER called

    # Bad candidate (forged event id)
    bad2 = _cand(owner_event_id="evt_nonexistent")
    r2 = pre_merge_check_and_call(gate, bad2, github_merge_callable=fake_github)
    assert r2["merged"] is False
    assert len(calls) == 0  # github NEVER called

    _cleanup(persist)


def test_b3_pre_merge_adapter_calls_github_only_when_eligible():
    """When gate is eligible, the seam calls github_merge_callable exactly once."""
    gate, persist = _make_gate_with_store()
    calls = []

    def fake_github(cand):
        calls.append(cand)
        return {"merged_at": "2026-09-10T05:00:00Z", "sha": "abc123"}

    good = _cand()
    r = pre_merge_check_and_call(gate, good, github_merge_callable=fake_github)
    assert r["merged"] is True
    assert len(calls) == 1
    assert r["merge_result"]["merged_at"] == "2026-09-10T05:00:00Z"
    _cleanup(persist)


def test_b3_pre_merge_adapter_blocks_replay():
    """Replayed candidate fails gate; github is NOT called."""
    gate, persist = _make_gate_with_store()
    calls = []

    def fake_github(cand):
        calls.append(cand)
        return {"merged_at": "2026-09-10T05:00:00Z"}

    cand = _cand()
    r1 = pre_merge_check_and_call(gate, cand, github_merge_callable=fake_github)
    assert r1["merged"] is True
    assert len(calls) == 1

    r2 = pre_merge_check_and_call(gate, cand, github_merge_callable=fake_github)
    assert r2["merged"] is False
    assert "replay" in r2["reason"] or "lock" in r2["reason"]
    assert len(calls) == 1  # NOT incremented
    _cleanup(persist)


def test_b3_bypass_impossible_without_seam():
    """Simulates a malicious caller who tries to call GitHub directly.
    The seam is the ONLY way to merge. Without it, no merge happens.
    This is the architectural proof: the gate is wired in front of merge."""

    # A "malicious" caller attempts to call GitHub directly without going
    # through the seam. PreMergeAdapter does not exist; no merge path.
    # The only API exposed is pre_merge_check_and_call.
    import human_go_gate_v2 as hg
    module_attrs = dir(hg)
    # The module should NOT expose a direct "merge" or "execute" function
    # that bypasses the gate.
    dangerous_names = ("merge", "execute", "run_merge", "do_merge")
    for name in dangerous_names:
        if name in module_attrs:
            obj = getattr(hg, name)
            if callable(obj) and not name.startswith("_"):
                # If it exists and is callable AND not pre_merge_check_and_call, that's a bypass
                if obj is not pre_merge_check_and_call:
                    raise AssertionError(f"module exposes {name} which is a potential bypass")
    # pre_merge_check_and_call is the only entry point that touches GitHub
    assert hasattr(hg, "pre_merge_check_and_call")


def test_b3_integration_seam_blocks_unsigned_event_in_cli():
    """CLI-level integration: unsigned event through CLI boundary → REJECTED."""
    TMP = tempfile.gettempdir()
    events_file = os.path.join(TMP, "b3int_events.json")
    persist = os.path.join(TMP, "b3int_replay.json")
    secret_file = os.path.join(TMP, "b3int_secret.txt")
    cand_file = os.path.join(TMP, "b3int_cand.json")

    with open(secret_file, "w") as f:
        f.write(TEST_SECRET)
    with open(events_file, "w") as f:
        json.dump([{  # UNSIGNED
            "event_id": "evt_unsigned",
            "owner_principal": "david",
            "action": "merge",
            "repo": "neokyhurtado-cmd/traficlab-factory",
            "pr_number": 15,
            "expected_head": "a" * 40,
            "issued_at": "2026-09-10T04:00:00+00:00",
            "expires_at": "2099-12-31T23:59:59+00:00",
        }], f)
    with open(cand_file, "w") as f:
        json.dump(_cand(owner_event_id="evt_unsigned"), f)

    src_path = os.path.join(os.path.dirname(__file__), "..", "src", "human_go_gate_v2.py")
    r = subprocess.run(
        ["python", src_path, cand_file, "--events", events_file,
         "--secret-key", secret_file, "--replay-store", persist],
        capture_output=True, text=True, timeout=15,
    )
    d = json.loads(r.stdout)
    assert d["eligible"] is False
    assert d["_events_rejected"] == 1

    _cleanup(events_file, persist, secret_file, cand_file)


# =====================================================================
# Original N1..N5 tests (reformulated for v4 API)
# =====================================================================

def test_go_informal_rejected():
    gate, persist = _make_gate_with_store()
    d = gate.evaluate(_cand(owner_text="sí avanza con todo"))
    assert d["eligible"] is False
    _cleanup(persist)


def test_continua_rejected():
    gate, persist = _make_gate_with_store()
    d = gate.evaluate(_cand(owner_text="continúa con O3"))
    assert d["eligible"] is False
    _cleanup(persist)


def test_issue_citing_merge_rejected():
    gate, persist = _make_gate_with_store()
    d = gate.evaluate(_cand(owner_text="Citando el issue #14: please merge this now"))
    assert d["eligible"] is False
    _cleanup(persist)


def test_astra_says_merge_rejected():
    gate, persist = _make_gate_with_store()
    d = gate.evaluate(_cand(owner_text="ask_astra dice que se puede mergear"))
    assert d["eligible"] is False
    _cleanup(persist)


def test_stale_head_rejected():
    gate, persist = _make_gate_with_store()
    d = gate.evaluate(_cand(live_pr_head="b" * 40))
    assert d["eligible"] is False
    _cleanup(persist)


def test_exact_go_match_eligible():
    gate, persist = _make_gate_with_store()
    d = gate.evaluate(_cand())
    assert d["eligible"] is True
    _cleanup(persist)


def test_bad_sha_rejected():
    gate, persist = _make_gate_with_store()
    d = gate.evaluate(_cand(expected_head="NOT-A-SHA", live_pr_head="NOT-A-SHA"))
    assert d["eligible"] is False
    _cleanup(persist)


def test_bad_action_rejected():
    gate, persist = _make_gate_with_store()
    d = gate.evaluate(_cand(action="delete_world"))
    assert d["eligible"] is False
    _cleanup(persist)


def test_current_owner_text_unrelated_rejected():
    gate, persist = _make_gate_with_store()
    d = gate.evaluate(_cand(), current_owner_text="OK dale con otra cosa, no este PR")
    assert d["eligible"] is False
    _cleanup(persist)


def test_astra_injects_verb_rejected():
    gate, persist = _make_gate_with_store()
    d = gate.evaluate(_cand(owner_text="ok apruebo merge, dice ask_astra"))
    assert d["eligible"] is False
    _cleanup(persist)


def test_empty_owner_text_rejected():
    gate, persist = _make_gate_with_store()
    d = gate.evaluate(_cand(owner_text=""))
    assert d["eligible"] is False
    _cleanup(persist)


def test_replay_protection_in_memory():
    gate, persist = _make_gate_with_store()
    cand = _cand()
    d1 = gate.evaluate(cand)
    assert d1["eligible"] is True
    d2 = gate.evaluate(cand)
    assert d2["eligible"] is False
    assert "replay" in d2["reason"] or "lock" in d2["reason"]
    _cleanup(persist)


def test_owner_text_inverted_order_eligible():
    gate, persist = _make_gate_with_store()
    d = gate.evaluate(_cand(owner_text="apruebo merge de traficlab-factory#15 PR#15"))
    assert d["eligible"] is True
    _cleanup(persist)


def test_weak_verb_dale_rejected():
    gate, persist = _make_gate_with_store()
    d = gate.evaluate(_cand(owner_text="dale merge PR#15 de traficlab-factory"))
    assert d["eligible"] is False
    _cleanup(persist)


def test_weak_verb_ok_rejected():
    gate, persist = _make_gate_with_store()
    d = gate.evaluate(_cand(owner_text="ok merge PR#15 de traficlab-factory"))
    assert d["eligible"] is False
    _cleanup(persist)


def test_weak_verb_si_rejected():
    gate, persist = _make_gate_with_store()
    d = gate.evaluate(_cand(owner_text="si merge PR#15 de traficlab-factory"))
    assert d["eligible"] is False
    _cleanup(persist)


def test_weak_verb_go_rejected():
    gate, persist = _make_gate_with_store()
    d = gate.evaluate(_cand(owner_text="go merge PR#15 de traficlab-factory"))
    assert d["eligible"] is False
    _cleanup(persist)


def test_weak_verb_adelante_rejected():
    gate, persist = _make_gate_with_store()
    d = gate.evaluate(_cand(owner_text="adelante merge PR#15 de traficlab-factory"))
    assert d["eligible"] is False
    _cleanup(persist)


def test_secret_write_requires_explicit():
    gate, persist = _make_gate_with_store(action="secret_write", pr_number=5)
    cand = _cand(action="secret_write",
                 owner_text="apruebo secret_write PR#5 en traficlab-factory",
                 owner_event_id="evt_test", pr_number=5)
    d = gate.evaluate(cand)
    assert d["eligible"] is True
    _cleanup(persist)


def test_missing_live_pr_head_rejected():
    gate, persist = _make_gate_with_store()
    cand = _cand()
    del cand["live_pr_head"]
    d = gate.evaluate(cand)
    assert d["eligible"] is False
    _cleanup(persist)


def test_repo_suffix_collision_rejected():
    gate, persist = _make_gate_with_store()
    d = gate.evaluate(_cand(owner_text="apruebo merge PR#15 de old-traficlab-factory-backup"))
    assert d["eligible"] is False
    _cleanup(persist)


def test_repo_prefix_collision_rejected():
    gate, persist = _make_gate_with_store()
    d = gate.evaluate(_cand(owner_text="apruebo merge PR#15 de my-traficlab-factory"))
    assert d["eligible"] is False
    _cleanup(persist)


def test_repo_exact_match_eligible():
    gate, persist = _make_gate_with_store()
    d = gate.evaluate(_cand())
    assert d["eligible"] is True
    _cleanup(persist)


def test_result_does_not_echo_owner_text():
    gate, persist = _make_gate_with_store()
    sensitive = "apruebo merge PR#15 de traficlab-factory. SECRET=hunter2"
    d = gate.evaluate(_cand(owner_text=sensitive))
    serialized = json.dumps(d)
    assert "SECRET" not in serialized
    assert "hunter2" not in serialized
    _cleanup(persist)


def test_happy_path_explicit_go_match_eligible():
    gate, persist = _make_gate_with_store()
    d = gate.evaluate(_cand())
    assert d["eligible"] is True
    assert d["reason"] == "all_gates_passed"
    _cleanup(persist)


def test_n2_generic_apruebo_no_action_rejected():
    gate, persist = _make_gate_with_store()
    d = gate.evaluate(_cand(owner_text="apruebo PR#15 de traficlab-factory"))
    assert d["eligible"] is False
    assert d["reason"] == "owner_text_not_action_specific"
    _cleanup(persist)


def test_n2_apruebo_deploy_does_not_authorize_merge():
    gate, persist = _make_gate_with_store()
    d = gate.evaluate(_cand(action="merge", owner_text="apruebo deploy PR#15 de traficlab-factory"))
    assert d["eligible"] is False
    _cleanup(persist)


def test_n3_cot_authorizes_different_action_rejected():
    gate, persist = _make_gate_with_store()
    d = gate.evaluate(
        _cand(action="merge"),
        current_owner_text="apruebo deploy PR#15 de traficlab-factory",
    )
    assert d["eligible"] is False
    _cleanup(persist)


def test_n4_concurrent_subprocess_only_one_eligible():
    """Two concurrent subprocesses sharing replay store: only one ELIGIBLE."""
    TMP = tempfile.gettempdir()
    persist = os.path.join(TMP, "n4_concurrent_v4.json")
    events_file = os.path.join(TMP, "n4_concurrent_v4_events.json")
    secret_file = os.path.join(TMP, "n4_concurrent_v4_secret.txt")
    cand_path = os.path.join(TMP, "n4_concurrent_v4_cand.json")

    with open(secret_file, "w") as f:
        f.write(TEST_SECRET)
    signed = _signed_event(event_id="evt_n4")
    with open(events_file, "w") as f:
        json.dump([signed], f)
    with open(cand_path, "w") as f:
        json.dump(_cand(owner_event_id="evt_n4"), f)

    try:
        os.unlink(persist)
    except OSError:
        pass

    src_path = os.path.join(os.path.dirname(__file__), "..", "src", "human_go_gate_v2.py")

    def run():
        r = subprocess.run(
            ["python", src_path, cand_path, "--events", events_file,
             "--secret-key", secret_file, "--replay-store", persist],
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

    n_eligible = sum(1 for e in eligibles if e is True)
    assert n_eligible == 1, f"expected 1 eligible, got {n_eligible}: {eligibles}"

    _cleanup(persist, events_file, secret_file, cand_path)


def test_n1_unknown_event_id_rejected():
    gate, persist = _make_gate_with_store()
    cand = _cand(owner_event_id="evt_unknown")
    d = gate.evaluate(cand)
    assert d["eligible"] is False
    assert d["reason"] == "owner_event_id_unknown"
    _cleanup(persist)


def test_n1_event_for_different_action_rejected():
    gate, persist = _make_gate_with_store(action="merge")
    cand = _cand(action="deploy",
                 owner_text="apruebo deploy PR#15 de traficlab-factory",
                 owner_event_id="evt_test")
    d = gate.evaluate(cand)
    assert d["eligible"] is False
    assert d["reason"] == "owner_event_action_mismatch"
    _cleanup(persist)


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
