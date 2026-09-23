# Skill Fabric — Intake Policy (V1)

This is the canonical, fail-closed intake policy for any external skill registered with the TraficLab Factory's Skill Fabric. It is the body of evidence used by `agent_body/skill_registry.py::validate_entry()` and asserted by `agent_body/tests/test_skill_fabric_v1.py::test_intake_policy_*`.

## 1. License gate (see also `policies/license-gate.md`)

Before any mode higher than `CATALOG`:

- Upstream must declare an OSI-approved or source-available license at HEAD.
- Dual-licenses: stricter license binds; directory scope is recorded.
- `NOASSERTION`, `NONE`, `UNLICENSED`: FAIL until upstream relicenses.

## 2. Pin exactly

For `SHADOW` and `ACTIVE`:

- `upstream_commit` MUST be a 40-character hex string (or the canonical GitHub short SHA expanded to 40).
- No `main`, `master`, `latest`, `head`, floating refs.
- The verifier (`validate_entry`) compares the SHA against live `gh api repos/<owner>/<repo>/branches/<default_branch>` and refuses to advance mode if HEAD has moved.

## 3. Inspect, do not execute

Before `SHADOW`:

- Read `README.md`, `install.sh`, `install.ps1`, `setup.py`, `package.json` (and equivalents).
- Flag any of: post-install hooks that shell out, network listeners, public binds, scheduled daemons, auto-update checks.
- A skill that requires those surfaces is downgraded to `BLOCKED` until the surface is removed upstream or a sandbox shim is documented.

## 4. No secrets

- Secrets / API keys MUST NEVER be copied into the factory repo.
- The registry entry records required `runtime_env` keys; presence of a key in the repo (`.env`, `secrets.yaml`, etc.) is automatic `LICENSE_GATE_FAIL` and downgrades to `BLOCKED`.
- Config / secrets / gateway mutation: any skill that demands these is `BLOCKED` outright (see `policies/no-go-boundaries.md`).

## 5. Network and side effects, declared

For `SHADOW` and `ACTIVE`, `network_access`, `filesystem_write`, `shell_exec`, `subagent_spawn` and `dependency_install` must be declared in the registry, not implied.

- `network_access: read-only` is the default for `SHADOW`.
- `network_access: write` is permitted only with `allowed_projects` set, and only via the agent body's checkpoint.
- A skill whose declared side effects disagree with observed runtime is downgraded to `BLOCKED`.

## 6. Authority and conflict guard

- Skills MUST NOT redefine system instructions, override decision authority, claim merge/release authority, or mutate the host repo authority hierarchy.
- See `agent_body/skill_registry.py::detect_authority_conflicts()`.
- Conflict pairs (e.g. Superpowers vs Factory protocol, Ponytail vs Caveman in the same skill set) cannot both run unless explicitly compatible.

## 7. Provenance for every imported file

For anything moved out of CATALOG:

- Record `upstream_repo`, `upstream_commit`, the file path within upstream, the local mirror path inside the host repo, and the SHA of the imported bytes (`imported_sha256`).
- A diff-vs-source check is a deterministic test (`test_imported_files_match_upstream`).

## 8. Fail-closed

Any uncertainty defaults to:

| Uncertainty | Default mode |
|---|---|
| License unknown | `BLOCKED` |
| SHA unknown | `CATALOG` |
| Side-effect declaration missing | `CANDIDATE` (only `READ_ONLY` operations allowed) |
| Authority conflict detected | `BLOCKED` |
| Drift between audited SHA and live `default_branch` HEAD | `CANDIDATE` until re-audited |

## 9. Catalog mode (see also macrogoal section F)

A skill whose role is discovery (e.g. `agentic-awesome-skills`) is registered as `CATALOG`. It does not auto-install or auto-enable. It may only suggest candidates that then run through this same intake gate.

## 10. Rollback

Every registry entry records `rollback`:

- The vendor directory (if any) under `.hermes/skills/<id>/`
- The vendored SHA
- The import marker (e.g., comment in `internal-consult` referencing the external skills)
- The command to drop it (e.g., `rm -rf .hermes/skills/<id>`)

Rollback is **deterministic and reversible**. The Skill Fabric never relies on upstream `uninstall` scripts — those are not in scope.

## 11. Live shadow canaries

`SHADOW` mode runs in real Hermes sessions. `ACTIVE` mode requires live shadow canary evidence (`live_canary.json`):

- `tasks_observed: <int>`
- `errors_with_skill: <int>`
- `errors_without_skill: <int>`
- `tokens_with_skill: <int>`
- `tokens_without_skill: <int>`
- `subjective_clarity_delta: <-1..+1>`
- `wall_clock_with_skill: <seconds>`
- `wall_clock_without_skill: <seconds>`

The shadow canary is held by the orchestrator; it does NOT auto-promote to `ACTIVE`.

## Cross-references

- `policies/no-go-boundaries.md` — the 14 hard no-go constants.
- `policies/license-gate.md` — the SPDX gate.
- `agent_body/skill_registry.py` — registry + validator.
- `agent_body/skill_router.py` — task-scoped router.
- `agent_body/tests/test_skill_fabric_v1.py` — deterministic tests.
