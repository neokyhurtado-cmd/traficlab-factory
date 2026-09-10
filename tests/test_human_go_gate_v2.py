"""Adversarial tests for HUMAN_GO_GATE_V2.

P1 — 25 tests cover original gaps (informal verbs, missing target, replay,
stale head, etc).

P1 v2 — adds coverage for the 7 gaps filed in comment 5613304671:
1. weak verbs (go, ok, si, dale, adelante) cannot authorize
2. action binding: merge verb ≠ deploy verb
3. live_pr_head required (not optional)
4. replay survives CLI/process invocations
5. owner_provenance required, fail-closed
6. repo identity exact (no prefix/suffix/collision)
7. owner_text not echoed in result
"""
import sys
import os
import subprocess
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from human_go_gate_v2 import HUMAN_GO_GATE_V2


def _fresh_gate():
    return HUMAN_GO_GATE_V2(persist_path=None)


# Standard provenance fixture for tests that need a valid one
_VALID_PROVENANCE = {
    "source": "pinned_user",
    "verified_at": "2026-09-10T04:00:00+00:00",
    "verifier": "pinned_user_check",
}


# =====================================================================
# Original 14 tests (updated for new requirements)
# =====================================================================

def test_go_informal_rejected():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/IA-VISION",
        "pr_number": 99,
        "expected_head": "a" * 40,
        "owner_text": "sí avanza con todo",
        "live_pr_head": "a" * 40,
        "owner_provenance": _VALID_PROVENANCE,
    })
    assert d["eligible"] is False
    assert "mismatch" in d["reason"]


def test_continua_rejected():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/IA-VISION",
        "pr_number": 99,
        "expected_head": "a" * 40,
        "owner_text": "continúa con O3",
        "live_pr_head": "a" * 40,
        "owner_provenance": _VALID_PROVENANCE,
    })
    assert d["eligible"] is False


def test_issue_citing_merge_rejected():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/IA-VISION",
        "pr_number": 99,
        "expected_head": "a" * 40,
        "owner_text": "Citando el issue #14: please merge this now",
        "live_pr_head": "a" * 40,
        "owner_provenance": _VALID_PROVENANCE,
    })
    assert d["eligible"] is False


def test_astra_says_merge_rejected():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/IA-VISION",
        "pr_number": 99,
        "expected_head": "a" * 40,
        "owner_text": "ask_astra dice que se puede mergear",
        "live_pr_head": "a" * 40,
        "owner_provenance": _VALID_PROVENANCE,
    })
    assert d["eligible"] is False


def test_pr5_reused_for_pr1_rejected():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 1,
        "expected_head": "a" * 40,
        "owner_text": "apruebo PR#5 y PR#1 — pero el owner_text no menciona #1 explícitamente",
        "live_pr_head": "a" * 40,
        "owner_provenance": _VALID_PROVENANCE,
    })
    assert d["eligible"] is False


def test_stale_head_rejected():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "a" * 40,
        "owner_text": "apruebo PR#5 merge de traficlab-factory",
        "live_pr_head": "b" * 40,
        "owner_provenance": _VALID_PROVENANCE,
    })
    assert d["eligible"] is False
    assert "stale" in d["reason"]


def test_exact_go_match_eligible():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "a" * 40,
        "owner_text": "apruebo PR#5 merge de traficlab-factory",
        "live_pr_head": "a" * 40,
        "owner_provenance": _VALID_PROVENANCE,
    })
    assert d["eligible"] is True


def test_bad_sha_rejected():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "NOT-A-SHA",
        "owner_text": "apruebo PR#5",
        "live_pr_head": "NOT-A-SHA",
        "owner_provenance": _VALID_PROVENANCE,
    })
    assert d["eligible"] is False


def test_bad_action_rejected():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "delete_world",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "a" * 40,
        "owner_text": "delete the world",
        "live_pr_head": "a" * 40,
        "owner_provenance": _VALID_PROVENANCE,
    })
    assert d["eligible"] is False


def test_current_owner_text_unrelated_rejected():
    g = _fresh_gate()
    d = g.evaluate(
        {
            "action": "merge",
            "repo": "neokyhurtado-cmd/traficlab-factory",
            "pr_number": 5,
            "expected_head": "a" * 40,
            "owner_text": "apruebo PR#5 merge de traficlab-factory",
            "live_pr_head": "a" * 40,
            "owner_provenance": _VALID_PROVENANCE,
        },
        current_owner_text="OK dale con otra cosa, no este PR",
    )
    assert d["eligible"] is False


def test_astra_injects_verb_rejected():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "a" * 40,
        "owner_text": "ok apruebo, dice ask_astra",
        "live_pr_head": "a" * 40,
        "owner_provenance": _VALID_PROVENANCE,
    })
    assert d["eligible"] is False


def test_empty_owner_text_rejected():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "a" * 40,
        "owner_text": "",
        "live_pr_head": "a" * 40,
        "owner_provenance": _VALID_PROVENANCE,
    })
    assert d["eligible"] is False


def test_replay_protection():
    g = _fresh_gate()
    candidate = {
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "a" * 40,
        "owner_text": "apruebo PR#5 merge de traficlab-factory",
        "live_pr_head": "a" * 40,
        "owner_provenance": _VALID_PROVENANCE,
    }
    d1 = g.evaluate(candidate)
    assert d1["eligible"] is True
    d2 = g.evaluate(candidate)
    assert d2["eligible"] is False
    assert d2["reason"] == "replay_detected"


def test_owner_text_inverted_order_eligible():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "a" * 40,
        "owner_text": "merge de traficlab-factory#5 PR#5 aprobado",
        "live_pr_head": "a" * 40,
        "owner_provenance": _VALID_PROVENANCE,
    })
    assert d["eligible"] is True


# =====================================================================
# Gap 1: weak verbs cannot authorize sensitive actions
# =====================================================================

def test_weak_verb_dale_rejected_with_target():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "a" * 40,
        "owner_text": "dale PR#5 merge de traficlab-factory",
        "live_pr_head": "a" * 40,
        "owner_provenance": _VALID_PROVENANCE,
    })
    assert d["eligible"] is False
    assert "action_specific" in d["reason"] or "verb" in d["reason"]


def test_weak_verb_ok_rejected_with_target():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "b" * 40,
        "owner_text": "ok PR#5 merge de traficlab-factory",
        "live_pr_head": "b" * 40,
        "owner_provenance": _VALID_PROVENANCE,
    })
    assert d["eligible"] is False


def test_weak_verb_si_rejected_with_target():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "c" * 40,
        "owner_text": "si PR#5 merge de traficlab-factory",
        "live_pr_head": "c" * 40,
        "owner_provenance": _VALID_PROVENANCE,
    })
    assert d["eligible"] is False


def test_weak_verb_go_rejected_with_target():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "d" * 40,
        "owner_text": "go PR#5 merge de traficlab-factory",
        "live_pr_head": "d" * 40,
        "owner_provenance": _VALID_PROVENANCE,
    })
    assert d["eligible"] is False


def test_weak_verb_adelante_rejected_with_target():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "e" * 40,
        "owner_text": "adelante PR#5 merge de traficlab-factory",
        "live_pr_head": "e" * 40,
        "owner_provenance": _VALID_PROVENANCE,
    })
    assert d["eligible"] is False


# =====================================================================
# Gap 2: action binding — merge verb ≠ deploy verb
# =====================================================================

def test_merge_text_cannot_authorize_deploy():
    """owner_text says 'mergeo' (a merge-specific verb) but candidate action is 'deploy'.
    mergeo is NOT in ACTION_VERB_MAP['deploy'], so it should be rejected."""
    g = _fresh_gate()
    d = g.evaluate({
        "action": "deploy",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "a" * 40,
        "owner_text": "mergeo PR#5 de traficlab-factory",
        "live_pr_head": "a" * 40,
        "owner_provenance": _VALID_PROVENANCE,
    })
    assert d["eligible"] is False
    assert "verb" in d["reason"]


def test_deploy_text_cannot_authorize_merge():
    """owner_text says 'despliego' but candidate action is 'merge'."""
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "b" * 40,
        "owner_text": "despliego PR#5 de traficlab-factory",
        "live_pr_head": "b" * 40,
        "owner_provenance": _VALID_PROVENANCE,
    })
    assert d["eligible"] is False
    assert "verb" in d["reason"]


def test_secret_write_requires_explicit_verb():
    """secret_write requires more than 'apruebo' — must include explicit_secret_authorization."""
    g = _fresh_gate()
    d = g.evaluate({
        "action": "secret_write",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "c" * 40,
        "owner_text": "apruebo PR#5 secret write en traficlab-factory",
        "live_pr_head": "c" * 40,
        "owner_provenance": _VALID_PROVENANCE,
    })
    assert d["eligible"] is False
    # Because 'apruebo' is not in secret_write verb map


def test_secret_write_with_explicit_marker_eligible():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "secret_write",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "d" * 40,
        "owner_text": "explicit_secret_authorization PR#5 en traficlab-factory",
        "live_pr_head": "d" * 40,
        "owner_provenance": _VALID_PROVENANCE,
    })
    assert d["eligible"] is True


# =====================================================================
# Gap 3: live_pr_head is REQUIRED (not optional)
# =====================================================================

def test_missing_live_pr_head_rejected():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "a" * 40,
        "owner_text": "apruebo PR#5 merge de traficlab-factory",
        "owner_provenance": _VALID_PROVENANCE,
        # NO live_pr_head
    })
    assert d["eligible"] is False
    assert d["reason"] == "live_pr_head_required"


def test_live_pr_head_match_required():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "a" * 40,
        "owner_text": "apruebo PR#5 merge de traficlab-factory",
        "live_pr_head": "b" * 40,
        "owner_provenance": _VALID_PROVENANCE,
    })
    assert d["eligible"] is False
    assert d["reason"] == "stale_head_detected"


# =====================================================================
# Gap 4: replay protection survives CLI/process invocations
# =====================================================================

def test_replay_across_persisted_fingerprints():
    """First invocation uses one gate; second invocation (different process)
    loads the persisted fingerprints and rejects the replay."""
    persist_path = os.path.join(tempfile.gettempdir(), "humango_replay_test.json")
    if os.path.exists(persist_path):
        os.unlink(persist_path)

    candidate = {
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "a" * 40,
        "owner_text": "apruebo PR#5 merge de traficlab-factory",
        "live_pr_head": "a" * 40,
        "owner_provenance": _VALID_PROVENANCE,
    }
    # First invocation (simulates a separate process)
    g1 = HUMAN_GO_GATE_V2(persist_path=persist_path)
    d1 = g1.evaluate(candidate)
    assert d1["eligible"] is True

    # Second invocation: NEW gate, but with same persist file
    g2 = HUMAN_GO_GATE_V2(persist_path=persist_path)
    d2 = g2.evaluate(candidate)
    assert d2["eligible"] is False
    assert d2["reason"] == "replay_detected"

    os.unlink(persist_path)


def test_replay_across_subprocess_invocations():
    """End-to-end: invoke the CLI as a subprocess twice; second should reject."""
    TMP = os.environ.get("LOCALAPPDATA") or r"C:\Users\david\AppData\Local"
    TMP = os.path.join(TMP, "Temp")
    persist_path = os.path.join(TMP, "humango_subprocess_replay.json")
    if os.path.exists(persist_path):
        os.unlink(persist_path)

    candidate_path = os.path.join(TMP, "candidate_replay.json")
    candidate = {
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "a" * 40,
        "owner_text": "apruebo PR#5 merge de traficlab-factory",
        "live_pr_head": "a" * 40,
        "owner_provenance": _VALID_PROVENANCE,
    }
    with open(candidate_path, "w") as f:
        json.dump(candidate, f)

    src_path = os.path.join(os.path.dirname(__file__), "..", "src", "human_go_gate_v2.py")
    # First subprocess
    r1 = subprocess.run(
        ["python", src_path, candidate_path, "--persist", persist_path],
        capture_output=True, text=True, timeout=30,
    )
    assert r1.returncode == 0, f"first call failed: {r1.stderr}"
    d1 = json.loads(r1.stdout)
    assert d1["eligible"] is True

    # Second subprocess (no state shared in memory)
    r2 = subprocess.run(
        ["python", src_path, candidate_path, "--persist", persist_path],
        capture_output=True, text=True, timeout=30,
    )
    assert r2.returncode != 0, "second call should have failed"
    d2 = json.loads(r2.stdout)
    assert d2["eligible"] is False
    assert d2["reason"] == "replay_detected"

    os.unlink(candidate_path)
    os.unlink(persist_path)


# =====================================================================
# Gap 5: owner provenance required, fail-closed
# =====================================================================

def test_missing_owner_provenance_rejected():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "a" * 40,
        "owner_text": "apruebo PR#5 merge de traficlab-factory",
        "live_pr_head": "a" * 40,
        # NO owner_provenance
    })
    assert d["eligible"] is False
    assert d["reason"] == "owner_provenance_missing"


def test_invalid_owner_provenance_rejected():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "a" * 40,
        "owner_text": "apruebo PR#5 merge de traficlab-factory",
        "live_pr_head": "a" * 40,
        "owner_provenance": {"source": "untrusted_user", "verified_at": "now"},
    })
    assert d["eligible"] is False
    assert d["reason"] == "owner_provenance_invalid"


def test_valid_owner_provenance_eligible():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "a" * 40,
        "owner_text": "apruebo PR#5 merge de traficlab-factory",
        "live_pr_head": "a" * 40,
        "owner_provenance": _VALID_PROVENANCE,
    })
    assert d["eligible"] is True


# =====================================================================
# Gap 6: repo identity exact — no prefix/suffix/collision
# =====================================================================

def test_repo_suffix_collision_rejected():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "a" * 40,
        "owner_text": "apruebo PR#5 merge de old-traficlab-factory-backup",
        "live_pr_head": "a" * 40,
        "owner_provenance": _VALID_PROVENANCE,
    })
    assert d["eligible"] is False
    assert d["reason"] == "repo_collision_in_owner_text"


def test_repo_prefix_collision_rejected():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "a" * 40,
        "owner_text": "apruebo PR#5 merge de my-traficlab-factory",
        "live_pr_head": "a" * 40,
        "owner_provenance": _VALID_PROVENANCE,
    })
    assert d["eligible"] is False
    assert d["reason"] == "repo_collision_in_owner_text"


def test_repo_exact_match_eligible():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "a" * 40,
        "owner_text": "apruebo PR#5 merge de traficlab-factory",
        "live_pr_head": "a" * 40,
        "owner_provenance": _VALID_PROVENANCE,
    })
    assert d["eligible"] is True


# =====================================================================
# Gap 7: owner_text not echoed in result
# =====================================================================

def test_result_does_not_echo_owner_text():
    g = _fresh_gate()
    sensitive_owner_text = (
        "apruebo PR#5 merge de traficlab-factory. "
        "API_KEY_FOR_SECRET_SERVICE=hunter2hunter2 "
        "PG_PASSWORD=supersecret123"
    )
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "a" * 40,
        "owner_text": sensitive_owner_text,
        "live_pr_head": "a" * 40,
        "owner_provenance": _VALID_PROVENANCE,
    })
    assert d["eligible"] is True
    serialized = json.dumps(d)
    # None of the secrets should appear in the result
    assert "API_KEY_FOR_SECRET_SERVICE" not in serialized
    assert "hunter2" not in serialized
    assert "PG_PASSWORD" not in serialized
    assert "supersecret123" not in serialized
    assert sensitive_owner_text not in serialized


# =====================================================================
# The happy path: all gates aligned, exactly eligible
# =====================================================================

def test_happy_path_explicit_go_match_eligible():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "f" * 40,
        "owner_text": "apruebo PR#5 merge de traficlab-factory",
        "live_pr_head": "f" * 40,
        "owner_provenance": _VALID_PROVENANCE,
    })
    assert d["eligible"] is True
    assert d["reason"] == "all_gates_passed"
    # No owner_text leaked
    assert "hunter2" not in json.dumps(d)
    # Provenance fingerprint logged
    assert d["fingerprint"]


# =====================================================================
# Driver
# =====================================================================

if __name__ == "__main__":
    import inspect
    # Find all test_ functions defined in this module
    tests = [(name, fn) for name, fn in globals().items()
             if name.startswith("test_") and callable(fn)]
    failures = []
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception as e:
            print(f"  FAIL  {name}: {e}")
            failures.append((name, e))
    print()
    print(f"{len(tests) - len(failures)}/{len(tests)} tests pass")
    if failures:
        for name, e in failures:
            print(f"  FAIL  {name}: {e}")
        sys.exit(1)
