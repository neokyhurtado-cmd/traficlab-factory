# M0 — Reality sync across all three repos

Read-only evidence basis. Verified 2026-09-09 against the running Windows host.

## M0 truth table

```text
CONTROL_V1_M0_REALITY = PASS
CANONICAL_MACRO_GOAL = neokyhurtado-cmd/traficlab-factory#4 (TRAFFICLAB-CONTROL-V1)
EXECUTION_WO = neokyhurtado-cmd/suini#54
HERMES_INTERFACE_EVIDENCE_SOURCE = neokyhurtado-cmd/traficlab-factory#3

HERMES_INSTALLED_VERSION = Hermes Agent v0.20.6 (2026.8.27) · upstream 9e0dc431
HERMES_INSTALL_DIR = C:\Users\david\AppData\Local\hermes\hermes-agent
HERMES_PYTHON = 3.11.16

CURRENT_GATEWAY_STATE = single multiplex runtime (default profile PID 4892) owns:
                          • Telegram gateway
                          • Kanban dispatcher
                          • Cron scheduler
                          • ORCH routing for the orchestrator / suini / ia-vision profiles
GATEWAY_LIST =
  ✓ default                  — PID 4892 (multiplex master, telegram owner)
  ✗ ia-vision                — not running
  ✗ orchestrator             — not running (cron-scheduled jobs registered, dispatcher multiplexes)
  ✗ suini (current)          — not running

HERMES_SERVER_OR_DASHBOARD_RUNNING = NO
  hermes serve --status: 'No hermes dashboard or serve processes running.'
  hermes dashboard --status: same
  hermes serve = port 9119 loopback JSON-RPC/WebSocket backend (default host 127.0.0.1)
  hermes dashboard = port 9119 loopback web dashboard (default host 127.0.0.1)
  Both are inactive. Starting either = 'privileged persistent daemon' per WO = HUMAN_GO_REAL.

API_SERVER_ENABLED = NOT_ENABLED
  No API_SERVER_ENABLED=true in C:\Users\david\AppData\Local\hermes\.env
  No API_SERVER_KEY set
  Enabling API server requires .env mutation = HUMAN_GO_REAL

WEBHOOK_PLATFORM_ENABLED = NOT_ENABLED
  hermes webhook list: 'Webhook platform is not enabled.'
  Enabling webhooks requires platforms.webhook block + .env HMAC secret = HUMAN_GO_REAL

MCP_SERVERS_CONFIGURED = NONE
  hermes mcp list: 'No MCP servers configured.'
  Adding MCP server requires mcp_servers block in config.yaml = HUMAN_GO_REAL

PEERS_REGISTERED = NONE
  hermes peer list: empty
  Adding a peer requires hermes peer add + storing API_SERVER_KEY = HUMAN_GO_REAL

SHELL_HOOKS_CONFIGURED = NONE
  hermes hooks list: 'No shell hooks or outbound webhooks configured.'
OUTBOUND_HOOKS_CONFIGURED = NONE
GATEWAY_HOOKS_INSTALLED = NONE
  (~/.hermes/hooks/ in default profile = absent)
  Installing gateway hooks requires writing to ~/.hermes/hooks/<name>/{HOOK.yaml,handler.py}
  These are NOT config.yaml mutations, but they ARE durable file writes that change runtime
  behavior. They will be added only if an authorized safe gate says they are needed and
  a symmetric HUMAN_GO trigger is hit. Today: WO permits this only as a non-required
  additive option, never a gate for live transport.

MESSAGING_PLATFORMS_LIVE_ON_DEFAULT_GATEWAY =
  ✓ Telegram (TELEGRAM_BOT_TOKEN present, TELEGRAM_HOME_CHANNEL=6650850458)
  ✓ Discord   (DISCORD_BOT_TOKEN present, DISCORD_ALLOWED_USERS=1453895497059405842)
  ✓ WhatsApp  (WHATSAPP_ENABLED=true, mode=self-chat)
  These are the LIVE channels used today. WO says: Telegram becomes optional fallback,
  never source of truth. The interface must work without Telegram.

CONTROL_CODE_HOME = neokyhurtado-cmd/traficlab-factory
  This is the canonical orchestration home (per its README + authority hierarchy).
  Has profiles/, policies/, ASHLEY-AGENT.md but no code for the Control V1 UI yet.
  Branch protection on main: false (so PRs are technically possible, but WO says
  merge to main is HUMAN_GO_REAL, so a feature branch and PR is the maximum reversibility).

EXISTING_CONTROL_UI = NONE
  No UI for TRAFFICLABPRO_CONTROL exists yet. The TraficLab Factory repo houses
  policies + profiles + onboarding only.

IA_VISION_REMOTE_STATE = read-only canonical at planning-time HEAD re-verified
  remote main = 42cb9d60dd3f1656e81722f22a4b9b5ca286453f (matches #4)
  open_issues_count = 23
  default_branch = main
  last push = 2026-09-09T06:56:02Z (today)

SUINI_REMOTE_STATE = read-only canonical at planning-time HEAD re-verified
  remote main = 800ae404c785a6a059206a26c7fb7b9473760206 (matches #4)
  open_issues_count = 28
  default_branch = main
  last push = 2026-09-09T07:15:18Z (today)

IA_VISOR_ENTRYPOINT = NOT_VERIFIED_WITHIN_THIS_WO
  Visor URL convention lives in IA-VISION product (out of scope to mutate here).
  Decision deferred to IA-VISION adapter gate (M5). V0 prototype will deep-link
  to whatever convention IA-VISION exposes via its README/issue.

SUINI_VISOR_ENTRYPOINT = http://localhost:8081 (canonical per #4)
  This is a localhost-only service that SUINI manages. TrafficLab Control will
  NEVER proxy :8081 for remote without explicit HUMAN_GO + SUINI-PRODUCT-CONTRACT
  approval. V0 prototype will show SUINI preview as NOT_AVAILABLE_YET to public
  network and ONLY deep-link from same-loopback client. Cross-host preview is
  out of scope for tonight — it requires the secure preview gateway (#4 D) which
  is itself a future gate.

CURRENT_RUNTIME_OWNER = default gateway PID 4892 (multiplex master)
  No additional gateway process should be created. No PID 4892 restart needed.

CONFIG_MUTATION_REQUIRED_NOW = NO
  Per authoritative gate: V0 prototype will be a static SPA reading only public
  GitHub metadata + IA-VISION/SUINI visors (when same-loopback reachable). No
  config change. No daemon enable. No secrets rotation. No .env write.
```

## What M0 discovered that constrains everything downstream

1. **Two product repos match their planning-time main SHAs exactly.** No drift.
2. **Hermes v0.20.6 has every interface #3 mentions and #4 needs.** API server (`hermes serve` JSON-RPC/WS at 9119), MCP (`hermes mcp serve`), ACP, peer, webhooks, hooks, web dashboard (`hermes dashboard` at 9119) — all present and documented in $LOCALAPPDATA/hermes/hermes-agent/website/docs.
3. **None of those interfaces is currently enabled on the live runtime.** Enabling ANY of them = config/.env mutation or privileged daemon start = **HUMAN_GO_REAL** by the WO.
4. **The default gateway PID 4892 has Telegram/Discord/WhatsApp live** and is the multiplex master. The orchestrator profile's cron jobs are multiplexer-targeted.
5. **The control code home is `traficlab-factory`**, currently doc-only, no UI code. Worktree-based V0 fits.
6. **traficlab-factory main is unprotected** but V0 work must remain a branch off main; PR merge is HUMAN_GO_REAL.
7. **`authority-hierarchy.md` confirms**: HERMES-ORCH owns TRAFFICLABPRO_CONTROL; if `target_product != assigned_product`, STOP. This is the cross-product guard the V0 must honor when it routes write intent.
8. **No `hermes send --list` results**, but Telegram/Discord/WhatsApp are otherwise proven live by parent task t_47131ada + REC-2B throughput on PID 4892. The empty `--list` is a known multiplexer profile-side effect.

## Decision for downstream gates

M0 returns PASS. M1/M2/M3/M4 can proceed in read-only/spec mode. M5 must check eligibility **against the no-config-mutation constraint** because starting the API server, the web dashboard, webhooks, peers, or any daemon needed for live roundtrip is a privileged persistent action classified as HUMAN_GO_REAL by the WO.

Therefore V0 eligibility for live end-to-end Hermes transport is **NOT auto-eligible tonight** under the constraint set. V0 will instead ship a thin static-first prototype that:
- Uses **public GitHub APIs only** for product intelligence (no Hermes server reachable).
- Renders Mission Control + IA-VISION Project + SUINI Project + Visual Review Hub stubs.
- Deep-links to visors IA-VISION/SUINI expose (no localhost proxying).
- Has the integration boundaries clearly defined so that when David later authorizes enabling the Hermes API server + web dashboard + webhooks, the adapter code already in place talks to them without modification.
- Classifies the remaining live-transport work as a single explicit HUMAN_GO_REAL bundle, with the exact minimum config touches listed.

This is the smallest reversible V0 the WO allows. Building it tonight does not advance the live channel question — and that question is the genuinely irreversible one for David.
