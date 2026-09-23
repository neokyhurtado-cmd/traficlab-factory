# Skill Fabric V1 — Architecture

## Status

V1 SCAFFOLD — landed via `skill-fabric-v1-implant-20260922-01` (issue #51).

- Branch: `skill-fabric-v1-implant-20260922-01`
- Base main: `2cbc4b2243fbf886c2d18f74f169fd7f88b15f32`
- Zero external skills registered.
- Zero runtime / config / secrets / gateway mutations introduced.

## Components

```text
.hermes/skills/skill-fabric/SKILL.md
        Native Hermes-discoverable skill (matches the convention of
        .hermes/skills/internal-consult/). Loaded on demand by
        agent_body/skill_discovery.py.

agent_body/skill_fabric/registry.py
        Schema (SkillEntry dataclass), SPDX allowlist, fail-closed
        validator, YAML loader.

agent_body/skill_fabric/router.py
        Returns the SMALLEST relevant skill subset for a task intent.
        Progressive discovery; never injects every skill into bootstrap.

agent_body/skill_fabric/conflict.py
        Deterministic resolver. Rule 1 (canonical Factory wins) is
        implemented in V1 SCAFFOLD. Rules 2/3 land with G3 tests.

agent_body/skill_fabric/graph_adapter.py
        READ-ONLY derived graph adapter (STUB in SCAFFOLD). Raises
        GraphAdapterNotActive until SHADOW canary activates it.

agent_body/tests/test_skill_fabric_v1.py
        G1/G2/G3 adversarial coverage. Pure pytest, no network.

scripts/g0_audit.py
        READ-ONLY gh-api harness for the 10 candidate upstream repos.
        Emits G0 evidence to evidence/skill-fabric-v1/g0-audit/.
```

## Authority hierarchy (mirrors issue #51)

```text
GitHub durable truth
> TrafficLab Factory policies / authority
> Agent Body capability boundaries
> project contracts
> external skill instructions
```

An external skill can add capability. It can NEVER override authority,
merge policy, HUMAN_GO_REAL, source-of-truth rules, secrets rules,
one-writer rules, or product ownership.

## Intake gates (fail-closed)

See `agent_body/skill_fabric/registry.py::validate_entry`. Summary:

1. License must be SPDX-known AND in the conservative allowlist.
2. ACTIVE / SHADOW mode requires an exact 40-char upstream SHA.
3. Any `forbidden_demands` entry matching the no-go list -> REJECT.
4. Prompt injection surface `high` or `critical` is incompatible with ACTIVE/SHADOW.
5. Dependency install must be `none` or `isolated_test_only`.

## Next gates (not in V1 SCAFFOLD)

- G0 evidence ingestion: run `scripts/g0_audit.py` and write the output to
  `evidence/skill-fabric-v1/g0-audit/g0_initial.json`.
- G1 hand-authored registry entries per candidate with full provenance.
- G2 router integration with `agent_body/skill_discovery.py`.
- G3 expanded adversarial tests (catalog auto-install, repo/project
  allowlist, generated-derivatives-as-canonical).
- G4 live shadow canaries (Superpowers SHADOW vs Factory; diagram-design;
  last30days; graph adapter; deliberate conflict pair).
- G5 full regression on Factory test suite (`pytest agent_body/`).

## Rollback

Removing the `skill-fabric` skill folder and `agent_body/skill_fabric/`
package restores Factory to its prior state. No global config, runtime,
secrets, or channels were touched by the V1 SCAFFOLD landing.
