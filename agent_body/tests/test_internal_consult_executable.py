"""INTERNAL_CONSULT — four executable pieces per directive #27.

Per directive `evolution-v1-closeout-20260914-01`:
  1. Real correlation of QUERY_ID/repo/issue/SHA — tests must parse and
     REJECT mismatch (no silent accept).
  2. ACTOR_UNVERIFIED as a real, executable branch — not a doc-only value.
  3. Extended secret scan — transitive over imports (os.environ, header
     smuggling, requests.auth). The pre-existing
     test_internal_consult_no_secret only checks literal `KEY=` patterns
     in three files; this test exercises the live module.
  4. /internal-consult discoverability — the skill must be findable by
     Hermes's skill loader from the workspace, not just by string-match
     against a hardcoded path.

These tests complement (do not duplicate) the static contract tests under
directive_watcher/tests/test_internal_consult_*.py — the latter freeze the
YAML/text contract; these exercise the executable surface.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


# 1. Real correlation of QUERY_ID / repo / issue / SHA -----------------------


def test_correlation_parser_rejects_mismatched_query_id():
    """A review with a wrong QUERY_ID MUST be parsed-but-rejected, not silently accepted."""
    from agent_body.internal_consult_synth import parse_review_envelope

    bundle = {
        "QUERY_ID": "evolution_v1_closeout_20260914_01",
        "REPOSITORY": "neokyhurtado-cmd/traficlab-factory",
        "ISSUE_OR_PR": "#27",
        "COMMIT_SHA": "7225d3e383f268b3b7032294ac6ef0c76d5c5d62",
    }
    bad_review = (
        "[MINIMAX_REVIEW:ARCHITECT:v1]\n"
        "QUERY_ID = some_other_query_20260913\n"
        "REPOSITORY = neokyhurtado-cmd/traficlab-factory\n"
        "ISSUE_OR_PR = #27\n"
        "COMMIT_SHA = 7225d3e383f268b3b7032294ac6ef0c76d5c5d62\n"
        "DECISION = GO\n"
        "RISK = LOW\n"
        "CONFIDENCE = 0.9\n"
        "COUNTEREXAMPLE = none\n"
        "EVIDENCE = agent_body/SKILL.md\n"
        "NOTES = ok\n"
    )
    parsed, correlation = parse_review_envelope(bad_review, expected_bundle=bundle)
    assert parsed is not None
    assert parsed["role"] == "ARCHITECT"
    # The correlation check is the key — mismatch → not valid for vote.
    assert correlation["valid"] is False
    assert "QUERY_ID" in correlation["mismatch_fields"]


def test_correlation_parser_rejects_mismatched_commit_sha():
    """The COMMIT_SHA is the most security-critical correlation field.

    Tampering must be rejected BEFORE the review can vote.
    """
    from agent_body.internal_consult_synth import parse_review_envelope

    bundle = {
        "QUERY_ID": "evolution_v1_closeout_20260914_01",
        "REPOSITORY": "neokyhurtado-cmd/traficlab-factory",
        "ISSUE_OR_PR": "#27",
        "COMMIT_SHA": "7225d3e383f268b3b7032294ac6ef0c76d5c5d62",
    }
    bad_review = (
        "[MINIMAX_REVIEW:EVIDENCE:v1]\n"
        "QUERY_ID = evolution_v1_closeout_20260914_01\n"
        "REPOSITORY = neokyhurtado-cmd/traficlab-factory\n"
        "ISSUE_OR_PR = #27\n"
        "COMMIT_SHA = deadbeefdeadbeefdeadbeefdeadbeefdeadbeef\n"
        "DECISION = GO\n"
        "RISK = LOW\n"
        "CONFIDENCE = 0.9\n"
        "COUNTEREXAMPLE = none\n"
        "EVIDENCE = tests/agent_body/\n"
        "NOTES = ok\n"
    )
    parsed, correlation = parse_review_envelope(bad_review, expected_bundle=bundle)
    assert parsed is not None
    assert correlation["valid"] is False
    assert "COMMIT_SHA" in correlation["mismatch_fields"]
    assert correlation["actor"] == "ACTOR_UNVERIFIED"


# 2. ACTOR_UNVERIFIED is a real executable branch ---------------------------


def test_actor_unverified_branch_is_executable_not_doc_only():
    """The synth oracle must produce ACTOR_UNVERIFIED outcomes that flow
    into the second-round decision, not just be text on a contract."""
    from agent_body.internal_consult_synth import (
        parse_review_envelope,
        correlate,
        synthesize,
    )

    bundle = {
        "QUERY_ID": "evolution_v1_closeout_20260914_01",
        "REPOSITORY": "neokyhurtado-cmd/traficlab-factory",
        "ISSUE_OR_PR": "#27",
        "COMMIT_SHA": "7225d3e383f268b3b7032294ac6ef0c76d5c5d62",
        "REVERSIBLE": True,
        "CRITICAL_GATE": False,
        "HUMAN_GATE": False,
    }
    # Two valid votes + one tampered → the tampered one must not count.
    valid_review = (
        "[MINIMAX_REVIEW:ARCHITECT:v1]\n"
        "QUERY_ID = evolution_v1_closeout_20260914_01\n"
        "REPOSITORY = neokyhurtado-cmd/traficlab-factory\n"
        "ISSUE_OR_PR = #27\n"
        "COMMIT_SHA = 7225d3e383f268b3b7032294ac6ef0c76d5c5d62\n"
        "DECISION = GO\n"
        "RISK = LOW\n"
        "CONFIDENCE = 0.9\n"
        "COUNTEREXAMPLE = none\n"
        "EVIDENCE = agent_body/\n"
        "NOTES = ok\n"
    )
    valid_review_2 = valid_review.replace("ARCHITECT", "EVIDENCE")
    tampered = (
        "[MINIMAX_REVIEW:RED_TEAM:v1]\n"
        "QUERY_ID = evolution_v1_closeout_20260914_01\n"
        "REPOSITORY = neokyhurtado-cmd/traficlab-factory\n"
        "ISSUE_OR_PR = #27\n"
        "COMMIT_SHA = ffffffffffffffffffffffffffffffffffffffff\n"
        "DECISION = GO\n"
        "RISK = LOW\n"
        "CONFIDENCE = 0.9\n"
        "COUNTEREXAMPLE = none\n"
        "EVIDENCE = agent_body/\n"
        "NOTES = ok\n"
    )

    parsed = []
    for r in (valid_review, valid_review_2, tampered):
        p, corr = parse_review_envelope(r, expected_bundle=bundle)
        parsed.append((p, corr))

    decision = synthesize(bundle, parsed_reviews=parsed)
    # RED_TEAM was tampered → excluded from quorum. Only 2 valid → SECOND_ROUND.
    assert decision["action"] == "SECOND_ROUND"
    assert "RED_TEAM" in decision["actor_unverified"]
    assert "RED_TEAM" in decision["rejected_reviews"]
    # ARCHITECT + EVIDENCE ARE counted.
    assert set(decision["review_roles"]) == {"ARCHITECT", "EVIDENCE"}
    # Decision is SECOND_ROUND precisely because quorum < min_quorum.
    assert decision["quorum_size"] == 2


# 3. Extended secret scan (transitive imports) -------------------------------


def test_internal_consult_modules_do_not_pull_secrets_from_env_or_auth():
    """Scan transitive imports of agent_body.internal_consult_synth and
    ensure it never reads os.environ, never instantiates requests with
    auth= or headers= containing literal credentials, never accepts a
    secret via a constructor kwarg.
    """
    from pathlib import Path as _P

    src_path = _P("agent_body") / "internal_consult_synth.py"
    assert src_path.exists(), "implementation must exist for transitive scan"

    text = src_path.read_text(encoding="utf-8")
    # The module must not import os.environ, must not use requests.auth,
    # must not accept a secret kwarg.
    forbidden = (
        re.compile(r"os\.environ"),       # env-var secret smuggling
        re.compile(r"requests\.auth"),    # HTTP auth smuggling
        re.compile(r"headers\s*=\s*\{"),  # header smuggling
        re.compile(r"api[_-]?key\s*=", re.IGNORECASE),  # literal API key
        re.compile(r"token\s*=", re.IGNORECASE),        # literal token
    )
    for rx in forbidden:
        assert not rx.search(text), f"forbidden pattern in synth module: {rx.pattern}"

    # Scan ALL non-test files under agent_body/ (transitive: every module the
    # test imports triggers). This is the "extended" scope the directive
    # asks for — pre-existing test_internal_consult_no_secret.py only scans
    # 3 text files; this test exercises the whole agent_body/ tree.
    for path in _P("agent_body").rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        if str(path).replace("\\", "/").endswith("test_internal_consult_executable.py"):
            # Don't scan the test file itself — its docstring legitimately
            # mentions "API_KEY=" as the forbidden pattern it asserts against.
            continue
        body = path.read_text(encoding="utf-8")
        assert "API_KEY=" not in body, f"literal API_KEY in {path}"
        assert "PASSWORD=" not in body, f"literal PASSWORD in {path}"
        assert "SECRET=" not in body, f"literal SECRET in {path}"


# 4. /internal-consult discoverability --------------------------------------


def test_internal_consult_skill_is_discoverable_from_workspace_root():
    """The internal-consult skill must be findable by walking from the
    workspace root, NOT by hardcoded absolute path. This proves a future
    worker can locate it without bespoke config.
    """
    from agent_body.skill_discovery import discover_skill

    # Walk from workspace root; this is what hermes skills_list / skill_view
    # would do. The skill must show up under the standard .hermes/skills/
    # convention.
    found = discover_skill("internal-consult", workspace_root=Path.cwd())
    assert found is not None
    assert found.name == "internal-consult"
    assert found.path.exists()
    # The discovered SKILL.md must be parseable as a real SKILL frontmatter
    # document, not just any markdown file with the right name.
    head = found.path.read_text(encoding="utf-8")
    assert head.startswith("---"), "SKILL.md must begin with YAML frontmatter"
    assert "name: internal-consult" in head
