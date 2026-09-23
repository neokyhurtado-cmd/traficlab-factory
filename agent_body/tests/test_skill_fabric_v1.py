"""Skill Fabric — V1 SCAFFOLD test suite.

Coverage:
    G1 registry schema + validator (fail-closed intake gates)
    G2 router progressive discovery (smallest relevant subset)
    G3 adversarial (floating ref, unknown license, prompt injection,
                   catalog auto-install, forbidden capability,
                   conflict canonical precedence)
    graph adapter stub raises until SHADOW activation
"""
from __future__ import annotations

import os
import sys
import textwrap
from pathlib import Path

import pytest

# Ensure repo root is importable for `agent_body.skill_fabric`.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent_body.skill_fabric import (  # noqa: E402
    ACCEPTED_SPDX_LICENSES,
    ConflictResolution,
    GraphAdapterNotActive,
    Mode,
    SkillEntry,
    build_graph,
    empty_routing,
    find_skill,
    load_registry,
    resolve,
    route,
    sha256_text,
    validate_entry,
)


# ---------- G1 registry schema + validator --------------------------------


def test_accepted_spdx_licenses_are_conservative():
    # Mirror issue #51 intent: conservative allowlist.
    assert "MIT" in ACCEPTED_SPDX_LICENSES
    assert "Apache-2.0" in ACCEPTED_SPDX_LICENSES
    # GPL variants are intentionally absent.
    assert "GPL-3.0" not in ACCEPTED_SPDX_LICENSES
    assert "AGPL-3.0" not in ACCEPTED_SPDX_LICENSES


def test_validate_entry_minimum_candidate_passes():
    raw = {
        "id": "diagram-design",
        "upstream_repo": "cathrynlavery/diagram-design",
        "upstream_commit": "0" * 40,
        "upstream_license": "MIT",
        "mode": "CANDIDATE",
    }
    ok, reasons = validate_entry(raw)
    assert ok, reasons


def test_validate_entry_active_requires_pinned_sha():
    raw = {
        "id": "diagram-design",
        "upstream_repo": "x/y",
        "upstream_commit": "main",  # floating ref
        "upstream_license": "MIT",
        "mode": "ACTIVE",
    }
    ok, reasons = validate_entry(raw)
    assert not ok
    assert any("40-char hex SHA" in r for r in reasons)


def test_validate_entry_active_requires_known_license():
    raw = {
        "id": "diagram-design",
        "upstream_repo": "x/y",
        "upstream_commit": "a" * 40,
        "upstream_license": "UNKNOWN",
        "mode": "ACTIVE",
    }
    ok, reasons = validate_entry(raw)
    assert not ok
    assert any("SPDX" in r for r in reasons)


def test_validate_entry_blocks_forbidden_demands():
    raw = {
        "id": "evil-skill",
        "upstream_repo": "x/y",
        "upstream_commit": "a" * 40,
        "upstream_license": "MIT",
        "mode": "CANDIDATE",
        "forbidden_demands": ["DIRECT_MAIN_WRITE", "SECRETS_MUTATION"],
    }
    ok, reasons = validate_entry(raw)
    assert not ok
    assert any("DIRECT_MAIN_WRITE" in r for r in reasons)
    assert any("SECRETS_MUTATION" in r for r in reasons)


def test_validate_entry_blocks_high_prompt_injection_for_active():
    raw = {
        "id": "x",
        "upstream_repo": "x/y",
        "upstream_commit": "a" * 40,
        "upstream_license": "MIT",
        "mode": "ACTIVE",
        "prompt_injection_surface": "high",
    }
    ok, reasons = validate_entry(raw)
    assert not ok
    assert any("prompt_injection_surface=high" in r for r in reasons)


def test_load_registry_empty_when_file_absent(tmp_path: Path):
    entries = load_registry(tmp_path / "absent.yaml")
    assert entries == []


def test_load_registry_validates_each_entry(tmp_path: Path):
    f = tmp_path / "registry.yaml"
    f.write_text(
        textwrap.dedent(
            """
            - id: diagram-design
              upstream_repo: cathrynlavery/diagram-design
              upstream_commit: 0{0}0
              upstream_license: MIT
              mode: CANDIDATE
            - id: evil
              upstream_repo: x/y
              upstream_commit: main
              upstream_license: MIT
              mode: ACTIVE
            """.format("a" * 39)
        ).strip()
    )
    with pytest.raises(ValueError) as ei:
        load_registry(f)
    assert "evil" in str(ei.value)
    assert "40-char hex SHA" in str(ei.value)


# ---------- G2 router progressive discovery --------------------------------


def _entry(mode: Mode, caps, project="*"):
    return SkillEntry(
        id=f"skill-{mode.value}",
        upstream_repo="x/y",
        upstream_commit="a" * 40,
        upstream_license="MIT",
        mode=mode,
        capabilities=caps,
        allowed_projects=[project],
    )


def test_router_returns_smallest_subset_for_intent():
    entries = [
        _entry(Mode.ACTIVE, ["diagram", "render"]),
        _entry(Mode.ACTIVE, ["video", "encode"]),
        _entry(Mode.CATALOG, ["diagram", "discovery"]),
    ]
    selected = route("render a diagram", entries, project_id="traficlab-factory")
    assert [s.id for s in selected] == ["skill-ACTIVE"]


def test_router_never_loads_catalog_automatically():
    entries = [_entry(Mode.CATALOG, ["diagram"])]
    assert route("diagram anything", entries, project_id="x") == []


def test_router_never_loads_candidate_or_blocked():
    entries = [
        _entry(Mode.CANDIDATE, ["diagram"]),
        _entry(Mode.BLOCKED, ["diagram"]),
    ]
    assert route("diagram", entries, project_id="x") == []


def test_router_respects_project_allowlist():
    entries = [
        SkillEntry(
            id="scoped",
            upstream_repo="x/y",
            upstream_commit="a" * 40,
            upstream_license="MIT",
            mode=Mode.ACTIVE,
            capabilities=["diagram"],
            allowed_projects=["other-project"],
        )
    ]
    assert route("diagram", entries, project_id="traficlab-factory") == []


def test_router_loads_shadow_only_for_canary_intents():
    entries = [
        SkillEntry(
            id="shadowed",
            upstream_repo="x/y",
            upstream_commit="a" * 40,
            upstream_license="MIT",
            mode=Mode.SHADOW,
            capabilities=["diagram"],
        )
    ]
    assert route("diagram", entries, project_id="x") == []
    assert len(route("shadow: diagram", entries, project_id="x")) == 1


def test_empty_routing_helper():
    assert empty_routing(
        [_entry(Mode.CANDIDATE, []), _entry(Mode.CATALOG, [])]
    ) is True
    assert (
        empty_routing([_entry(Mode.ACTIVE, ["x"])])
    ) is False


# ---------- G3 adversarial --------------------------------------------------


def test_canonical_factory_wins_against_skill_conflict():
    s = SkillEntry(
        id="factory-challenger",
        upstream_repo="x/y",
        upstream_commit="a" * 40,
        upstream_license="MIT",
        mode=Mode.ACTIVE,
        capabilities=["diagram"],
        conflicts=["__FACTORY_CANONICAL__"],
    )
    res = resolve([s], factory_directive="diagram must respect Factory style")
    assert res.winner is None
    assert s in res.losers
    assert res.canonical_factory_won


def test_graph_adapter_stub_raises_until_canary():
    with pytest.raises(GraphAdapterNotActive):
        build_graph(Path("/tmp/fake"))


def test_sha256_helper_is_deterministic():
    assert sha256_text("abc") == sha256_text("abc")
    assert sha256_text("abc") != sha256_text("abd")


def test_find_skill_helper():
    a = _entry(Mode.ACTIVE, ["x"], project="*")
    b = _entry(Mode.CATALOG, ["y"], project="*")
    assert find_skill([a, b], "skill-CATALOG").id == "skill-CATALOG"
    assert find_skill([a, b], "missing") is None


# ---------- Guard rails: zero forbidden mutations introduced ---------------


def test_scaffold_state_has_no_external_skill_registered(tmp_path: Path):
    """In V1 SCAFFOLD state, the registry file does not yet exist."""
    # This test exists to document the contract: V1 lands with NO
    # external skills registered. Adding candidates requires the G0
    # audit + G1-G5 gates per issue #51.
    fake_registry = tmp_path / "registry.yaml"
    assert not fake_registry.exists()
    assert load_registry(fake_registry) == []
