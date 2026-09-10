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


def test_utf8_owner_text_eligible():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "a" * 40,
        "owner_text": "apruebo merge de traficlab-factory#5 🚀",
    })
    assert d["eligible"] is True


def test_double_space_in_owner_text_eligible():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "b" * 40,
        "owner_text": "apruebo PR  #5  merge de traficlab-factory",
    })
    assert d["eligible"] is True


def test_tab_in_owner_text_eligible():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "c" * 40,
        "owner_text": "apruebo PR\t#5 merge de traficlab-factory",
    })
    assert d["eligible"] is True


def test_case_insensitive_repo_name_eligible():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "d" * 40,
        "owner_text": "apruebo PR#5 merge de TRAFICLAB-FACTORY",
    })
    assert d["eligible"] is True


def test_multiple_PRs_no_target_pr_rejected():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "e" * 40,
        "owner_text": "apruebo PR#1 y PR#2 también",
    })
    assert d["eligible"] is False
    assert "mismatch" in d["reason"]


def test_pr_substring_attack_rejected():
    """PR number 99 must not match within PR#1999 or PR#990."""
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 99,
        "expected_head": "f" * 40,
        "owner_text": "apruebo PR#1999 merge de traficlab-factory",
    })
    assert d["eligible"] is False
    assert "mismatch" in d["reason"]


def test_pr_substring_safe_eligible():
    """PR number 99 must match in PR#99 but NOT PR#990."""
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 99,
        "expected_head": "01" * 20,
        "owner_text": "apruebo PR#99 merge de traficlab-factory",
    })
    assert d["eligible"] is True


def test_repo_substring_partial_match_documented():
    """Edge case: 'traficlab-factory' matches within 'old-traficlab-factory-backup'.

    This is by design — the gate accepts any text that mentions the target
    repo name as a substring. The caller MUST verify against GitHub that the
    PR exists in the EXACT target repo before merging. The gate is one
    layer of defense, not the only one.
    """
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "10" * 20,
        "owner_text": "apruebo PR#5 merge de old-traficlab-factory-backup",
    })
    # Documented behavior: substring match is accepted
    assert d["eligible"] is True
    assert d["reason"] == "all_gates_passed"


def test_blank_lines_between_relevant_lines_eligible():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "11" * 20,
        "owner_text": "consideraciones varias\n\n\napruebo PR#5 merge de traficlab-factory\n\nmás texto",
    })
    assert d["eligible"] is True


def test_markdown_format_in_owner_text_eligible():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "12" * 20,
        "owner_text": "**apruebo** `PR#5` merge de **traficlab-factory**",
    })
    assert d["eligible"] is True


def test_punctuation_around_target_eligible():
    g = _fresh_gate()
    d = g.evaluate({
        "action": "merge",
        "repo": "neokyhurtado-cmd/traficlab-factory",
        "pr_number": 5,
        "expected_head": "13" * 20,
        "owner_text": "Ok, apruebo merge de traficlab-factory#5. Listo.",
    })
    assert d["eligible"] is True



if __name__ == "__main__":
    # Original 14 tests
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
    # 11 additional adversarial tests
    test_utf8_owner_text_eligible()
    test_double_space_in_owner_text_eligible()
    test_tab_in_owner_text_eligible()
    test_case_insensitive_repo_name_eligible()
    test_multiple_PRs_no_target_pr_rejected()
    test_pr_substring_attack_rejected()
    test_pr_substring_safe_eligible()
    test_repo_substring_partial_match_documented()
    test_blank_lines_between_relevant_lines_eligible()
    test_markdown_format_in_owner_text_eligible()
    test_punctuation_around_target_eligible()
    print("ALL 25 TESTS PASS")
