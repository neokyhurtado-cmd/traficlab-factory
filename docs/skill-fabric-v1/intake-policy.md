# Skill Fabric V1 — Intake Policy

Fail-closed. A candidate skill MUST satisfy every gate to enter the
registry. Missing evidence is treated as failure.

## G1 — Registry schema and validator

Implemented in `agent_body/skill_fabric/registry.py::validate_entry`.

| Gate | Rule | Failure outcome |
|------|------|-----------------|
| Required fields | `id`, `upstream_repo`, `upstream_commit`, `mode` present | REJECT |
| Pinned SHA | ACTIVE / SHADOW requires exact 40-char hex | REJECT |
| License SPDX-known | ACTIVE / SHADOW requires SPDX id in `ACCEPTED_SPDX_LICENSES` | REJECT |
| No forbidden demands | Any of the 16 no-go items present in `forbidden_demands` | REJECT |
| Prompt-injection surface | `high` or `critical` incompatible with ACTIVE / SHADOW | REJECT |
| Dependency install | Must be `none` or `isolated_test_only` | REJECT |

## G3 — Supply-chain + adversarial

Tested in `agent_body/tests/test_skill_fabric_v1.py`.

- Floating upstream refs rejected for ACTIVE mode.
- Unknown license rejected for ACTIVE / SHADOW mode.
- Unapproved auto-install rejected (forbidden_demands gate).
- Secret / config / gateway mutation rejected (forbidden_demands gate).
- Prompt / authority override loses to canonical Factory (conflict resolver rule 1).
- Catalog recommendation does not imply installation (router rule: CATALOG never loaded).
- Conflict pair cannot both activate unless explicitly compatible (Rule 2/3 stub; will land with G3 expansion).
- Repo / project allowlist enforced (router).
- Generated derived artifacts cannot be treated as canonical truth (graph adapter raises until SHADOW).

## What is NOT covered in V1 SCAFFOLD

- Live network egress probes against candidate repos (manual review required).
- Live shell sandbox isolation tests.
- Live SHADOW canary against an actual upstream.
- Full Factory regression (`pytest agent_body/`).

Each of those lands in the appropriate G-stage. V1 SCAFFOLD establishes
the validator surface and the test harness; the G-stage gates populate
the evidence chain.
