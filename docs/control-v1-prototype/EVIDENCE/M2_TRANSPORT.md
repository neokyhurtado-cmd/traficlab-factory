# M2 — Hermes-native transport composition

Decision based on evidence collected in M0. The M0 truth table established that
the live Hermes API server, web dashboard, webhooks, MCP servers, and peers
are all NOT currently enabled on this host. Enabling any of them is classified
by the WO as **HUMAN_GO_REAL** (config/secrets/daemon mutation).

Therefore M2 must choose **two parallel compositions**:
1. **Composition A** — what V0 will physically ship tonight, using only
   transport surfaces that are already available (public GitHub REST +
   Hermes CLI invocations from the same host that runs the Control BFF).
2. **Composition B** — the target composition once David authorizes the
   first privileged Hermes surface, defined in advance so the adapter code
   can drop in without redesign.

---

## M2 truth table

```text
CHAT_TRANSPORT          = (A) GitHub Issues + comments     (B) Hermes API /v1/chat/completions + /v1/responses
ASYNC_RUN_TRANSPORT     = (A) Kanban CLI dispatch          (B) Hermes /v1/runs + GET /v1/runs/{id}/events
EVENT_TRANSPORT         = (A) GitHub REST polling + kanban (B) Hermes lifecycle hooks + outbound signed hook
APPROVAL_TRANSPORT      = (A) Kanban transitions on HUMAN_GO comments (B) Hermes ACP approvals stream
SESSION_RESUME_STRATEGY = (A) Last-Event-ID / ETag polling on NextJS-like cache; (B) Hermes responses_id chains + bot-chat canonical
BROWSER_DIRECT_TO_HERMES = NO (in either composition; BFF pattern only)
HERMES_KEY_EXPOSED_TO_BROWSER = NO (in either composition; only short-lived BFF-scoped cookie)
CUSTOM_PROTOCOL_REQUIRED = NO (composition A); NO (composition B - uses official OpenAI-compatible or Hermes-native RPCs)
ADAPTER_REQUIRED         = YES (composition A: thin static BFF reading GitHub + calling hermes CLI on same host;
                                composition B: same BFF with the Hermes API client module added behind a feature flag)
```

## Why composition A ships V0 tonight

The WO's `AUTO-GO` set covers: read/audit/research, inspect installed Hermes
read-only, local POCs that do not require config/secrets/public exposure, UX/IA
work, isolated worktree code, commits/push to feature branch, PR creation if a
reviewable tranche exists, and reversible tests/docs.

Composition A meets the AUTO-GO criteria with no privileged surfaces touched:
- Public **GitHub REST** for issue/PR/commit/CI data — public, anonymous-callable,
  rate limits but no auth needed for the read-side corpus (private data is gated
  by David's session).
- **Kanban CLI** (`hermes kanban show`, `hermes kanban list`) — already authorized.
- **Hermes CLI** for `hermes gateway list`, `hermes profile list`, `hermes serve
  --status`, `hermes serve --status` — read-only and already gated by default
  profile access.

Composition A is acceptable as the V0 tranche; the BFF is even safer if the BFF
process runs on the same host as the Control UI and only talks to the
kanban DB + GitHub REST + Hermes CLI. It never needs an inbound port except the
static-served frontend.

## What composition B unlocks once authorized

The Hermes docs at `$LOCALAPPDATA/hermes/hermes-agent/website/docs/` show:

- `hermes serve` — port 9119 loopback JSON-RPC/WebSocket backend with:
  - `POST /v1/chat/completions` and `POST /v1/responses` (stateful via `previous_response_id` or `conversation`)
  - `POST /v1/runs` with `GET /v1/runs/{id}/events` SSE
  - `GET /v1/models`, `GET /v1/capabilities`
  - Per-request model/provider selection
  - Bearer auth (`API_SERVER_KEY`); loopback only by default
- `hermes dashboard` — port 9119 web dashboard loopback only
- `hermes mcp serve` — stdio MCP exposing Hermes conversation
- `hermes webhook` — port 8644 inbound webhook with HMAC secret
- Outbound hooks via `hooks.outbound:` config block, signed posts to a control webhook
- `hermes acp` — VS Code/Zed/JetBrains integration, includes approvals stream
- `hermes peer` — cross-machine via API server bearer key + Bot Chat canonical

Activation cost per surface (all are HUMAN_GO_REAL tonight):
1. `API_SERVER_ENABLED=true` + `API_SERVER_KEY=<random>` in `~/.hermes/.env`
2. `WEBHOOK_ENABLED=true` + `WEBHOOK_PORT=8644` + `WEBHOOK_SECRET=<random>` in `~/.hermes/.env`
3. `hooks.outbound:` block in `~/.hermes/config.yaml` listing the Control's
   inbound webhook URL + signing secret
4. `hermes mcp add filesystem <…>` or `hermes mcp install <catalog>`
5. `hermes peer add <name> --url <…> --key <…>` writing `API_SERVER_KEY` to `.env`
6. `hermes gateway install` + restart (already running via multiplexed PID 4892)

Once David approves ONE of those surfaces — most likely the API server + outbound
hooks for live event push — the BFF module that consumes it is already designed
in composition B and ready to flip on behind a feature flag.

## Why no custom protocol is needed

The WO explicitly forbids inventing a custom protocol if Hermes already exposes a
contract adequate for the use case. Every plane in composition B maps to an
existing Hermes plane:
- chat → OpenAI-compatible
- async runs → official `/v1/runs`
- events → outbound hooks + webhook receiver
- approvals → ACP (or comment-mediated HUMAN_GO in composition A)
- session resume → `responses_id` chains + Bot Chat canonical reference

Custom protocol cost avoided.

## Why the browser NEVER holds the Hermes key

The Control BFF runs on the loopback host (or on the same machine, in the case
of a deployment). It carries the `API_SERVER_KEY` only in the BFF process. The
browser carries a short-lived BFF session cookie bound to the user's local
authentication (loopback dev: any cookie-based session is fine; production:
tunnel + same-host bearer token exchange). Whatever the deployment shape, the
browser never sees the bearer. This satisfies the security minimum in M4.

## Adapter layer shape

The BFF exposes the same internal REST API regardless of whether composition A
or B is active. The internal API is the contract the frontend speaks. Each
backend adapter (GitHub / Kanban / Hermes-API / Hermes-Webhooks / Hermes-MCP)
is a separate module behind a single interface. Composition A ships with the
GitHub + Kanban adapters; composition B adds the Hermes adapters behind a
feature flag.

## Decision

- Composition A (live tonight, auto-eligible, read-only against GitHub + kanban
  + Hermes CLI) is the V0 transport.
- Composition B (authorized surface(s) only after David approves the exact
  config touches listed above) is the target.

The V0 prototype ships composition A. Composition B is documented, code is
written but disabled, and the exact minimal later action is recorded.
