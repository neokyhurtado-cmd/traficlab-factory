# No-Go Boundaries — TRAFFICLAB Factory

This file codifies the **immutable no-go boundaries** for the TraficLab Factory and any product that builds on it. They are derived from issue `neokyhurtado-cmd/traficlab-factory#51` (MACROGOAL HERMES SKILL FABRIC V1) and are consistent with the existing frozen boundaries in `agent_body/manifest.py` (`FROZEN_BOUNDARY_DENIED_CAPABILITIES`).

A single positive authorization from the canonical decision authority (`policies/authority-hierarchy.md`, top of stack) MAY lift a boundary for a named ticket and a named SHA. The lift must be explicit, in writing, and durable (GitHub durable comment or PR review). Default is **deny**.

## Hard no-go list

| Boundary | Constant | Why |
|---|---|---|
| Direct write to `main` | `DIRECT_MAIN_WRITE = NO` | All product repo merges go through a PR. |
| Force push to any branch | `FORCE_PUSH = NO` | History integrity; pre-existing-rework rule still applies. |
| Auto-merge to `main` without review | `AUTO_MERGE_MAIN = NO` | Authority requires human (ASTRA/DAVID) gate for merge. |
| Mutate secrets / API keys | `SECRETS_MUTATION = NO` | No edits to `.env`, `secrets/`, keyring, or any auth handle. |
| Mutate `config.yaml` / `config.yml` | `CONFIG_YAML_MUTATION = NO` | Config mutation requires explicit owner GO. |
| Mutate runtime env vars | `ENV_MUTATION = NO` | No `os.environ` writes during task execution. |
| Mutate the Hermes gateway | `GATEWAY_MUTATION = NO` | Telegram/Discord/WhatsApp adapters and the multiplex owner are off-limits. |
| Mutate Telegram / Discord / WhatsApp integrations | `TELEGRAM_MUTATION = NO`, `DISCORD_MUTATION = NO`, `WHATSAPP_MUTATION = NO` | Channel surface is owned by the gateway. |
| Change model / provider | `MODEL_PROVIDER_CHANGE = NO` | Provider switching requires explicit owner GO. |
| Create a new orchestrator | `NEW_ORCHESTRATOR = NO` | One orchestrator exists (`./orchestrator/`); do not fork. |
| Create a new vector database | `NEW_VECTOR_DB = NO` | Out of scope; backed by `agent_body/README.md` table. |
| Create a new knowledge base | `NEW_KNOWLEDGE_BASE = NO` | Out of scope; backed by `agent_body/README.md` table. |
| Bind a public listener | `PUBLIC_LISTENER = NO` | No daemon that opens a public port. |
| Establish a second source of truth | `SECOND_SOURCE_OF_TRUTH = NO` | GitHub durable + Agent Body checkpoint + control plane state are canonical. |
| Mutate product repos during graph canary | `PRODUCT_REPO_MUTATION_DURING_GRAPH_CANARY = NO` | Graph / visualization adapters are read-only during canary. |

## Relationship to the Skill Fabric

An external skill (see `policies/skill-fabric-intake.md`) MAY extend capability, but it CANNOT widen these boundaries. If a third-party skill attempts to redefine authority, override merge policy, or claim `AUTO_GO` on these surfaces, the **Skill Fabric conflict resolver denies it** and the skill is dropped to `BLOCKED`.

## Lifting a boundary

If a ticket genuinely needs a boundary lifted (e.g. a merge is required by an ASTRA directive), the lift must be:

1. **Named** in the directive text (issue / PR comment) — not implied.
2. **Scoped** to a repo + branch + commit SHA.
3. **Time-bounded** — the lift expires when the named gate passes.
4. **Reversible** — the directive must say how to revert.
5. **Auditable** — durable in GitHub comments with a stable `<text id="...">` block.

No blanket "operate at max power" instruction can lift a boundary.
