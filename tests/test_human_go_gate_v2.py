"""Adversarial tests for HUMAN_GO_GATE_V2.

These tests are designed to FAIL if the gate accepts any of the
ambiguous instructions that motivated the P1 program: informal
verbs, missing target reference, replay, stale head, etc.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from human_go_gate_v2 import HUMAN_GO_GATE_V2


def _fresh_gate():
    return HUMAN_GO_GATE_V2(persist_path=None)


def test_go_informal_rejected():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/IA-VISION",
        "pr_number": 99,
        "expected_head": "a" * 40,
        "owner_text": "sí avanza con todo",
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
    })
    assert d["eligible"] is False
    assert "mismatch" in d["reason"]


def test_issue_citing_merge_rejected():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/IA-VISION",
        "pr_number": 99,
        "expected_head": "a" * 40,
        "owner_text": "Citando el issue #14: please merge this now",
    })
    assert d["eligible"] is False
    assert "mismatch" in d["reason"]


def test_astra_says_merge_rejected():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/IA-VISION",
        "pr_number": 99,
        "expected_head": "a" * 40,
        "owner_text": "ask_astra dice que se puede mergear",
    })
    assert d["eligible"] is False
    assert "mismatch" in d["reason"]


def test_pr5_reused_for_pr1_rejected():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 1,
        "expected_head": "a" * 40,
        "owner_text": "apruebo PR#5 y PR#1 — pero el owner_text no menciona #1 explícitamente",
    })
    assert d["eligible"] is False
    assert "mismatch" in d["reason"]


def test_stale_head_rejected():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "a" * 40,
        "owner_text": "apruebo PR#5 merge de traficlab-factory#5",
        "live_pr_head": "b" * 40,
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
        "owner_text": "apruebo PR#5 merge de traficlab-factory#5",
        "live_pr_head": "a" * 40,
    })
    assert d["eligible"] is True
    assert d["reason"] == "all_gates_passed"


def test_bad_sha_rejected():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "NOT-A-SHA",
        "owner_text": "apruebo PR#5",
    })
    assert d["eligible"] is False
    assert "sha" in d["reason"]


def test_bad_action_rejected():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "delete_world",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "a" * 40,
        "owner_text": "delete the world",
    })
    assert d["eligible"] is False
    assert "action" in d["reason"]


def test_current_owner_text_unrelated_rejected():
    g = _fresh_gate()
    d = g.evaluate(
        {
            "action": "merge",
            "repo": "neokyhurtado-cmd/traficlab-factory",
            "pr_number": 5,
            "expected_head": "a" * 40,
            "owner_text": "apruebo PR#5 merge de traficlab-factory#5",
            "live_pr_head": "a" * 40,
        },
        current_owner_text="OK dale con otra cosa, no este PR",
    )
    assert d["eligible"] is False
    assert "current" in d["reason"]


def test_astra_injects_verb_rejected():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "a" * 40,
        "owner_text": "ok apruebo, dice ask_astra",
    })
    assert d["eligible"] is False
    assert "mismatch" in d["reason"]


def test_empty_owner_text_rejected():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "a" * 40,
        "owner_text": "",
    })
    assert d["eligible"] is False
    assert "empty" in d["reason"]


def test_replay_protection():
    g = _fresh_gate()
    candidate = {
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "a" * 40,
        "owner_text": "apruebo PR#5 merge de traficlab-factory#5",
        "live_pr_head": "a" * 40,
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
    })
    assert d["eligible"] is True


if __name__ == "__main__":
    test_go_informal_rejected()
    test_continua_rejected()
    test_issue_citing_merge_rejected()
    test_astra_says_merge_rejected()
    test_pr5_reused_for_pr1_rejected()
    test_stale_head_rejected()
    test_exact_go_match_eligible()
    test_bad_sha_rejected()
    test_bad_action_rejected()
    test_current_owner_text_unrelated_rejected()
    test_astra_injects_verb_rejected()
    test_empty_owner_text_rejected()
    test_replay_protection()
    test_owner_text_inverted_order_eligible()
    print("ALL 14 TESTS PASS")
