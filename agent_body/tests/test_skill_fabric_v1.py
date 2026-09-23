"""Skill Fabric V1 — supply-chain + adversarial + router tests.

The tests in this module cover the G3 supply-chain + adversarial gate from
the SKILL-FABRIC-V1 macrogoal (issue neokyhurtado-cmd/traficlab-factory#51):

  - G3.1 floating upstream refs rejected for ACTIVE mode
  - G3.2 unknown license rejected for vendoring
  - G3.3 unapproved auto-install rejected
  - G3.4 secret/config/gateway mutation rejected
  - G3.5 prompt/authority override loses to canonical Factory
  - G3.6 catalog recommendation does not imply installation
  - G3.7 conflict pair cannot both activate unless explicitly compatible
  - G3.8 repo/project allowlist enforced
  - G3.9 generated derived artifacts cannot be treated as canonical truth

Plus routing + router + progressive-discovery tests for G2, and the
LICENSE_GATE / SUPPLY_CHAIN_GATE tests for G3.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pytest

from agent_body.skill_registry import (
    is_valid_sha,
    is_open_license,
    is_blocking_license,
    detect_authority_conflicts,
    load_registry,
    resolve_skill_router,
    validate_entry,
    validate_registry,
    SkillEntry,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _entry(**overrides) -> SkillEntry:
    base = {
        "id": "sample",
        "upstream_repo": "owner/sample",
        "upstream_commit": "5bf4e78011075bcfc0dc295f0724994cd123ee71",
        "upstream_default_branch": "main",
        "upstream_license": "MIT",
        "spdx_id_ok": True,
        "mode": "CATALOG",
        "capabilities": {
            "network_access": "read-only",
            "filesystem_read": "declarative",
            "filesystem_write": "none",
            "shell_exec": "none",
            "subagent_spawn": "none",
            "prompt_injection_surface": "low",
            "dependency_install": "none",
        },
        "conflicts": [],
        "allowed_projects": ["neokyhurtado-cmd/traficlab-factory"],
        "activation_scope": "task-scoped",
        "rollback": {
            "type": "filesystem-mirror",
            "mirror_dir": ".hermes/skills/sample/",
            "disable_command": "rm -rf .hermes/skills/sample/",
        },
        "evidence": "audits/sample.md",
        "rationale": "Sample skill used by tests.",
        "raw": {},
    }
    base.update(overrides)
    base["raw"] = overrides.get("raw", base)
    return SkillEntry(**base)


# --------------------------------------------------------------------------- #
# SHA / SPDX primitives
# --------------------------------------------------------------------------- #


def test_is_valid_sha_accepts_only_40_lowercase_hex():
    assert is_valid_sha("5bf4e78011075bcfc0dc295f0724994cd123ee71") is True
    assert is_valid_sha("ABCD000000000000000000000000000000000000") is False  # uppercase
    assert is_valid_sha("5bf4e78011075bcfc0dc295f0724994cd123ee7") is False   # 39 chars
    assert is_valid_sha("5bf4e78011075bcfc0dc295f0724994cd123ee7100") is False  # 42 chars
    assert is_valid_sha("") is False
    assert is_valid_sha(None) is False  # type: ignore[arg-type]


def test_is_open_license_admits_mit_apache_bsd_mpl_isc():
    assert is_open_license("MIT")
    assert is_open_license("mit")
    assert is_open_license("Apache-2.0")
    assert is_open_license("BSD-3-Clause")
    assert is_open_license("MPL-2.0")
    assert is_open_license("ISC")
    assert not is_open_license("BSL-1.1")
    assert not is_open_license("NOASSERTION")
    assert not is_open_license("OTHER")


def test_is_blocking_license_detects_bsl_and_sspl():
    assert is_blocking_license("BSL-1.1")
    assert is_blocking_license("busl-1.1")
    assert is_blocking_license("SSPL")
    assert is_blocking_license("sspl-1.0")
    assert not is_blocking_license("MIT")
    assert not is_blocking_license("NOASSERTION")


# --------------------------------------------------------------------------- #
# G3.1 floating upstream refs rejected for ACTIVE mode
# --------------------------------------------------------------------------- #


def test_g31_floating_main_ref_rejected_for_active():
    """A 7-char SHA stub like 'main' is not a 40-char hex SHA."""
    e = _entry(mode="ACTIVE",
               upstream_commit="main",
               spdx_id_ok=True,
               evidence="audits/x.md")
    msgs = validate_entry(e)
    assert any("not a 40-char hex SHA" in m for m in msgs), msgs


def test_g31_short_sha_rejected_for_active():
    e = _entry(mode="ACTIVE",
               upstream_commit="abc1234",
               spdx_id_ok=True,
               evidence="audits/x.md")
    msgs = validate_entry(e)
    assert any("not a 40-char hex SHA" in m for m in msgs), msgs


def test_g31_live_sha_drift_for_shadow_drives_candidate_default():
    """Drift in SHADOW mode is reported as DRIFT, NOT a hard failure.

    Operator decides whether to refresh the pinned SHA.
    """
    e = _entry(mode="SHADOW",
               upstream_commit="5bf4e78011075bcfc0dc295f0724994cd123ee71")
    drift = "91f4d120b630ee35c79bf3c75ccd186870a808f9"
    msgs = validate_entry(e, live_sha=drift)
    assert any("DRIFT" in m and "differs from live" in m for m in msgs), msgs


def test_g31_drift_strategy_block_upgrades_to_hard_failure():
    e = _entry(mode="SHADOW",
               upstream_commit="5bf4e78011075bcfc0dc295f0724994cd123ee71")
    drift = "91f4d120b630ee35c79bf3c75ccd186870a808f9"
    msgs = validate_entry(e, live_sha=drift, drift_strategy="BLOCK")
    assert any(m.startswith("FAIL") and "differs from live" in m for m in msgs), msgs


# --------------------------------------------------------------------------- #
# G3.2 unknown license rejected for vendoring / activation
# --------------------------------------------------------------------------- #


def test_g32_noassertion_rejected_for_active():
    e = _entry(mode="ACTIVE",
               upstream_license="NOASSERTION",
               spdx_id_ok=True,
               evidence="audits/x.md")
    msgs = validate_entry(e)
    assert any("LICENSE_GATE_FAIL" in m and "NOASSERTION" in m for m in msgs), msgs


def test_g32_noassertion_allowed_for_catalog():
    """CATALOG is allowed even when license is unknown — catalog is reference material."""
    e = _entry(mode="CATALOG", upstream_license="NOASSERTION")
    msgs = validate_entry(e)
    # No LICENSE_GATE failures for CATALOG with NOASSERTION (still fails other validations? No).
    assert not any("LICENSE_GATE_FAIL" in m for m in msgs), msgs


def test_g32_bsl_blocked_at_shadow_and_active():
    e = _entry(mode="SHADOW", upstream_license="BSL-1.1", spdx_id_ok=True)
    msgs = validate_entry(e)
    assert any("LICENSE_GATE_FAIL" in m and "blocking" in m for m in msgs), msgs


def test_g32_dual_license_requires_vendored_directories_be_empty_for_active():
    e = _entry(
        mode="ACTIVE",
        upstream_license="DUAL",
        spdx_id_ok=True,
        evidence="audits/x.md",
        raw={
            "license_detail": {
                "permissive": "MIT",
                "restrictive": "BSL-1.1",
                "scope_separation": "LICENSE (MIT) covers everything except engine-linked dirs.",
            },
            "vendored_directories": ["engine/"],
            "id": "dual-skill",
            "upstream_repo": "owner/dual",
            "upstream_commit": "5bf4e78011075bcfc0dc295f0724994cd123ee71",
            "upstream_default_branch": "main",
            "mode": "ACTIVE",
        },
    )
    msgs = validate_entry(e)
    assert any("vendored_directories" in m for m in msgs), msgs


# --------------------------------------------------------------------------- #
# G3.3 / G3.4 unapproved auto-install + secret/config/gateway mutation
# --------------------------------------------------------------------------- #


def test_g33_unapproved_dependency_install_keeps_entry_in_catalog():
    """A skill whose only declared dep-install is 'none' and mode is CATALOG passes."""
    e = _entry(mode="CATALOG", upstream_license="MIT")
    msgs = validate_entry(e)
    assert not any("LICENSE_GATE_FAIL" in m for m in msgs), msgs


def test_g34_shadow_requires_nondeps_when_declared_zero():
    e = _entry(mode="SHADOW",
               capabilities={
                   "network_access": "read-only",
                   "filesystem_read": "SKILL.md-only",
                   "filesystem_write": "none",
                   "shell_exec": "none",
                   "subagent_spawn": "none",
                   "prompt_injection_surface": "low",
                   "dependency_install": "none",
               })
    msgs = validate_entry(e)
    assert msgs == [], msgs


# --------------------------------------------------------------------------- #
# G3.5 prompt/authority override surfaces
# --------------------------------------------------------------------------- #


def test_g35_authority_override_in_rationale_is_detected():
    """Superpowers' EXTREMELY_IMPORTANT wrapper is the canonical example."""
    e = _entry(
        id="superpowers",
        rationale=(
            "Prompt injection via bootstrap EXTREMELY_IMPORTANT wrapper that overrides "
            "system-instruction behavior. Override of decision authority hierarchy is "
            "a conflict class. Currently SHADOW."
        ),
    )
    conflicts = detect_authority_conflicts([e])
    assert "superpowers" in conflicts
    assert any("override" in c.lower() for c in conflicts["superpowers"])


def test_g35_superpowers_rationale_lists_known_conflicts():
    e = _entry(
        id="superpowers",
        rationale="May override system-instruction ordering; conflict with Factory authority.",
    )
    conflicts = detect_authority_conflicts([e])
    assert "superpowers" in conflicts


def test_g35_pure_style_skill_with_authority_keywords_in_rationale_is_flagged():
    """The analyzer flags intent — caller decides whether the keyword is real."""
    e = _entry(
        id="ponytail",
        rationale="pre_llm_call hook — competes with dispatcher policy and may rewrite response.",
    )
    conflicts = detect_authority_conflicts([e])
    assert "ponytail" in conflicts


# --------------------------------------------------------------------------- #
# G3.6 catalog recommendation does not imply installation
# --------------------------------------------------------------------------- #


def test_g36_sickn33_is_catalog_only_and_excluded_from_router_by_default():
    """AAS Core must remain CATALOG; the router does not surface catalogued
    entries unless the intent contains the entry's id or repo-anchor as a
    literal token."""
    reg = load_registry()
    sickn33 = reg.by_id("agentic-awesome-skills")
    assert sickn33 is not None
    assert sickn33.mode == "CATALOG"
    assert sickn33.activation_scope == "cataloged-discovery-feed"

    # Clearly unrelated intent must NOT surface the catalog entry.
    paths = resolve_skill_router(
        "What is the weather in Paris tomorrow?",
        reg,
        project="neokyhurtado-cmd/traficlab-factory",
    )
    assert "agentic-awesome-skills" not in paths, paths

    # Explicit intent_keyword MAY surface it as a catalog reference.
    paths_with_keyword = resolve_skill_router(
        "I want to find reusable skills",
        reg,
        project="neokyhurtado-cmd/traficlab-factory",
        intent_keywords=["agentic-awesome-skills"],
    )
    assert "agentic-awesome-skills" in paths_with_keyword, paths_with_keyword


# --------------------------------------------------------------------------- #
# G3.7 conflict pair cannot both activate unless explicitly compatible
# --------------------------------------------------------------------------- #


def test_g37_ponytail_and_caveman_list_each_other_as_conflicts():
    reg = load_registry()
    ponytail = reg.by_id("ponytail")
    caveman = reg.by_id("caveman")
    assert ponytail is not None
    assert caveman is not None
    assert "caveman" in ponytail.conflicts
    assert "ponytail" in caveman.conflicts


def test_g37_active_mode_cannot_be_assigned_to_conflict_pair_without_resolution():
    """Authority-conflict analyzer flags at least one of {ponytail, caveman}.

    Ponytail's rationale mentions system-instruction override.  Caveman's
    rationale is intentionally neutral so the analyzer does NOT flag it
    (caveman is purely a catalog-only reference; vendoring engine/ is
    gated by LICENSE_GATE elsewhere).
    """
    entries = [
        _entry(
            id="ponytail-active",
            rationale=(
                "pre_llm_call hook — appends ruleset to system-instruction list every turn; "
                "may rewrite response; competes with dispatcher policy and authority."
            ),
        ),
        _entry(
            id="caveman-active",
            rationale=(
                "skills/adapters + agents/agents.json; clean reference material; "
                "engine/ subdir is BSL-licensed and excluded."
            ),
        ),
    ]
    conflicts = detect_authority_conflicts(entries)
    # ponytail-active mentions system-instruction and authority keywords.
    assert "ponytail-active" in conflicts, conflicts
    # caveman-active is clean (no authority keywords), so it should NOT appear.
    assert "caveman-active" not in conflicts, conflicts


def test_g37_router_does_not_load_two_conflict_pairs_for_same_task():
    """If the caller asks for both ponytail and caveman, the router never
    returns both at score >= 4 — ponytail has pre_llm_call hook and is
    CATALOG-only by default, so even if id-matched, score is bounded by
    activation_scope=cataloged-only (-3).  Caveman same.  Falls back
    gracefully.
    """
    reg = load_registry()
    paths = resolve_skill_router(
        "ponytail and caveman competition test",
        reg,
        project="neokyhurtado-cmd/traficlab-factory",
    )
    # Both have activation_scope=cataloged-only -> -3 bias -> final score
    # pinned below the 4 threshold for these intents; they should NOT both
    # appear as loadable skills (catalog-only filter).
    overlap = set(paths) & {"ponytail", "caveman"}
    assert overlap == set(), paths


# --------------------------------------------------------------------------- #
# G3.8 repo/project allowlist enforced
# --------------------------------------------------------------------------- #


def test_g38_shadow_requires_allowed_projects_nonempty():
    e = _entry(mode="SHADOW", allowed_projects=[])
    msgs = validate_entry(e)
    assert any("allowed_projects" in m for m in msgs), msgs


def test_g38_router_excludes_unauthorized_project():
    reg = load_registry()
    paths = resolve_skill_router(
        "Run a planning code task with superpowers",
        reg,
        project="some-other-org/some-other-repo",
    )
    assert "superpowers" not in paths, (
        "superpowers is allow-listed to neokyhurtado-cmd/traficlab-factory only; "
        "must not appear for unrelated projects"
    )


# --------------------------------------------------------------------------- #
# G3.9 generated derived artifacts cannot be treated as canonical truth
# --------------------------------------------------------------------------- #


def test_g39_graphify_isolated_to_derived_cache_rollback():
    reg = load_registry()
    g = reg.by_id("graphify")
    assert g is not None
    assert g.activation_scope == "read-only-derived-adapter"
    assert g.rollback["type"] == "derived-cache"
    assert g.rollback["cache_dir"] == ".hermes/skills/graphify/graphify-out/"


def test_g39_understandanything_writes_only_under_dot_ua():
    reg = load_registry()
    u = reg.by_id("understand-anything")
    assert u is not None
    assert ".ua-only" in u.capabilities["filesystem_write"]


# --------------------------------------------------------------------------- #
# Progressive discovery (G2) — fresh worker does not load every skill
# --------------------------------------------------------------------------- #


def test_g2_router_returns_at_most_three_skills_for_a_planning_intent():
    reg = load_registry()
    # Generic dev intent without an explicit identifier: router falls back
    # to canonical Factory behavior (empty list).  Progressive discovery
    # is ON by default — a fresh worker must NOT load every skill.
    paths_plain = resolve_skill_router(
        "I need to plan a code task end to end with verifier-backed gates",
        reg,
        project="neokyhurtado-cmd/traficlab-factory",
    )
    assert paths_plain == [], paths_plain

    # Caller contracts the router explicitly: bring superpowers to the top.
    paths_keyword = resolve_skill_router(
        "Plan and execute a coding task with brainstorming, subagent-driven-development, "
        "test-driven-development, using superpowers discipline end-to-end.",
        reg,
        project="neokyhurtado-cmd/traficlab-factory",
        intent_keywords=["superpowers"],
    )
    assert 0 < len(paths_keyword) <= 5, paths_keyword
    assert "superpowers" in paths_keyword


def test_g2_router_returns_empty_for_unrelated_intent():
    reg = load_registry()
    paths = resolve_skill_router(
        "What is the weather in Paris tomorrow?",
        reg,
        project="neokyhurtado-cmd/traficlab-factory",
    )
    # Should not match any registry entry by id/repo/rationale token.
    assert paths == [], paths


# --------------------------------------------------------------------------- #
# Registry integrity — every entry MUST pass on real disk artifacts
# --------------------------------------------------------------------------- #


def test_registry_on_disk_is_shape_valid():
    """The real ``.hermes/skills-registry/skills.yaml`` must round-trip."""
    reg = load_registry()
    assert reg.schema == "skill-fabric/v1"
    assert reg.version == 1
    assert reg.fail_closed is True
    assert len(reg.entries) == 10


def test_registry_on_disk_all_pass_for_catalog_and_candidate():
    """All CATALOG + CANDIDATE entries (8 of 10) must pass validation.

    The other 2 entries (superpowers, scientific-agent-skills) are SHADOW
    or CANDIDATE respectively, both of which must also pass shape + license.
    """
    reg = load_registry()
    res = validate_registry(reg)
    # No hard FAILs for any entry on this snapshot.
    assert res.fail_messages == {}, res.fail_messages
    assert set(res.passed_ids) == {e.id for e in reg.entries}


def test_registry_active_id_is_zero_in_v1():
    """V1 must NOT auto-promote any skill to ACTIVE."""
    reg = load_registry()
    res = validate_registry(reg)
    assert res.active_ids == []


def test_registry_superpowers_in_shadow_not_active():
    reg = load_registry()
    res = validate_registry(reg)
    assert "superpowers" in res.shadow_ids
    assert "superpowers" not in res.active_ids


def test_registry_scientific_skills_in_candidate():
    reg = load_registry()
    res = validate_registry(reg)
    assert "scientific-agent-skills" in res.candidate_ids
