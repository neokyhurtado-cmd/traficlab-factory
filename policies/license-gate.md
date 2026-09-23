# Skill Fabric — License Gate

External skills vendored, mirrored, or run under the TraficLab Factory's Skill Fabric MUST satisfy a license gate before any mode higher than `CATALOG` is granted.

## Rules

1. **Repo must declare an OSI-approved or source-available license at the upstream head.**
   - `MIT`, `BSD-2-Clause`, `BSD-3-Clause`, `Apache-2.0`, `MPL-2.0`, `ISC`: PASS
   - `LGPL-2.1-or-later`, `GPL-*`: PASS, but **branded as `GPL_FAMILY`** and subject to the copyleft-aware review (described below).
   - `BUSL-1.1`, `SSPL`, `BSL`: FAIL for vendoring and SHADOW/ACTIVE unless an explicit BSL allowance is documented and approved via `BLOCKED_MODE_OVERRIDE` ticket.
   - `NOASSERTION`, `NONE`, `OTHER`, `UNLICENSED`: FAIL until a license is added upstream AND a `LICENSE_GATE_REOPEN` rationale is filed.
   - **Dual-license** (multiple SPDX ids): the strictest applicable license binds. Document the exact directory scope in the registry entry.

2. **License scope must cover the vendored files.**
   - If only a subset of the upstream tree is permissive (e.g. caveman: `LICENSE` MIT covers skills/, `LICENSE.BSL` covers `engine/`), the registry entry MUST enumerate the vendored directories and confirm they all live under the permissive scope.
   - Vendoring BSL/SSPL-covered code blocks `LICENSE_GATE`. Reading it for inspiration does not.

3. **Author / owner provenance is recorded.**
   - The registry entry records upstream author / sponsoring org when present.

4. **No silent relicensing.** Adding a `LICENSE` file to the host Factory repo is a separate, careful patch — NOT bundled with the Skill Fabric intake.

## How the gate is tested

`agent_body.tests.test_skill_fabric_v1.test_license_gate_*` verifies:

- An entry with `upstream_license=MIT`, `Apache-2.0`, `BSD-3-Clause`, `MPL-2.0`, `ISC` passes for `SHADOW` and `ACTIVE`.
- An entry with `upstream_license=BSL-1.1` is blocked even if mode is `SHADOW`.
- An entry with `upstream_license=NOASSERTION` is blocked.
- A dual-license entry must list `engines:` directory scope; engines files cannot be vendored.

## When the gate blocks a desired skill

Do NOT silently downgrade the skill to `CATALOG`. Surface a `LICENSE_GATE_FAIL` comment on the relevant SKILL fabric ticket with:

- The license verdict.
- The exact reason (`upstream_license` value, directory scope conflict).
- The alternative (re-license request upstream, scoped take, or `CATALOG`-only registration).
