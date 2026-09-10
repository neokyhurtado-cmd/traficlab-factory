# M4 — Architecture + threat-model checkpoint

The thinnest first-party architecture supported by M0-M3.

---

## Architecture target shape

```text
David phone/desktop
      ↓ HTTPS + realtime (loopback-only, tunneled-only, or local LAN)
TrafficLab Control UI (PWA-installable web app, mobile-first)
      ↓ BFF REST + Server-Sent Events, same-origin
Control BFF (loopback-only host process)
      ├── Composition A adapters (live tonight):
      │     ├── GitHub REST adapter       (public, no auth needed for read)
      │     ├── Kanban CLI adapter         (already authorized)
      │     ├── Hermes CLI adapter         (hermes gateway list, hermes profile list, etc.)
      │     └── Evidence dir adapter       (durable local JSONL)
      └── Composition B adapters (HUMAN_GO_REAL feature-flagged, off tonight):
            ├── Hermes API client          (port 9119, when API server enabled)
            ├── Hermes ACP client
            ├── Hermes MCP server adapter
            ├── Hermes peer client
            └── Hermes webhooks receiver
                                            ↓
HERMES-ORCH (PID 4892 multiplex master)
   ↙             ↓               ↘
IA-VISION        SUINI           worker profiles
   ↓                ↓
product code + visors + canonical data
```

Each arrow is annotated with its security characteristic in the threat model
below.

---

## Architecture properties (composition A only — what ships tonight)

- **Local/private first.** The Control BFF binds `127.0.0.1:9119` (default) and
  is reachable only via the same loopback or a tunneled connection David
  authorizes through his Hermes runtime.
- **No public unauthenticated bind.** The BFF does NOT bind `0.0.0.0` and
  does NOT advertise a public port. The same loopback security the Hermes
  serve/dashboard already enforces is reused.
- **Browser never sees Hermes/provider secrets.** The BFF has its own
  loopback session cookie; the Hermes `API_SERVER_KEY`, GitHub PAT, plugin
  tokens, etc. live only in the BFF process env. Browser code is built
  without secrets inlined (verified by the build pipeline + the test suite
  in M6).
- **Narrow CORS when used.** Default = same-origin only. CORS is configurable
  via env, but only for the loopback port and the exact origin David runs
  the frontend from; never `*`.
- **Explicit approval audit trail.** Every HUMAN_GO action posts a comment
  to the originating task with author + decision_note + timestamp. The
  durable log is append-only JSONL on disk.
- **No raw secret payloads in logs/events.** All logs run through a single
  redactor that matches bearer-token / PAT / API key shapes and replaces them
  with `***`. The redactor is part of the M6 test suite.
- **No Telegram/Discord dependence for continuity.** Telegram/Discord remain
  status-only fallback notifications; if Telegram's bot token is rotated,
  the Control UI continues to function.
- **No Codex dependence.** Codex is not in any control path.

The same properties apply when composition B activates behind a feature flag
once David authorizes the necessary config changes.

---

## Threat model

Six categories. For each, the threat, the mitigation, and the residual risk.

### T1. Authentication & session fixation

- **Threat**: An attacker scans for the BFF port or hijacks the loopback
  cookie and impersonates David.
- **Mitigation**:
  - BFF only binds `127.0.0.1` by default. `--host 0.0.0.0` triggers an
    explicit `--insecure-binding-acknowledged` flag and refuses to start
    unless an external auth provider is configured.
  - The loopback cookie is `HttpOnly`, `Secure` (when HTTPS), `SameSite=Strict`,
    rotated on login. CSRF tokens required for all POST writes (HMAC bound to
    session id).
  - The BFF supports `password` and `oauth` auth providers; tunneled
    deployments must use one. Documented in the BFF `README` (a future
    gate, separate from V0).
- **Residual**: loopback-only is the only mode shipping in V0. Once an
  external bind is authorized, a strong external auth provider is required.

### T2. Replay / duplicate events

- **Threat**: A stale event from a stuck stream or a duplicate POST creates
  a phantom task or duplicates a HUMAN_GO action.
- **Mitigation**:
  - Every event carries `(source, event_id, sequence)`; clients dedupe by
    `(source, event_id)`.
  - Every control-side POST carries an `idempotency_key`; the BFF rejects
    repeats within 1 hour with 409 + the canonical response body.
  - Browser refresh always replays POST actions with the same
    `idempotency_key` recovered from localStorage.
- **Residual**: a hostile actor who can read localStorage can replay an old
  idempotency key. Bounded by 1-hour retention and HMAC binding.

### T3. Stale approvals

- **Threat**: An approval is granted, the underlying condition changes (new
  evidence arrives, the PR re-pushes), and the approval still applies.
- **Mitigation**:
  - A HUMAN_GO decision always carries `(affected_repo, branch, sha)`. The
    BFF applies the decision only if the canonical SHA matches at the moment
    of execution. Mismatch → 409 with a "stale approval, re-confirm" error
    and a deep-link to the new evidence.
  - Decisions also carry `expires_at`; expired decisions are visually
    marked on the inbox and require re-confirmation.
- **Residual**: a human can still approve an outdated decision if they
  ignore the warning. UX makes the staleness state obvious.

### T4. Prompt injection from webhook / event sources

- **Threat**: A malicious GitHub issue body or a poisoned `gh api` response
  embeds instructions that change the LLM's behavior when an evidence item
  is summarized.
- **Mitigation**:
  - All evidence items rendered in the UI are escaped; the UI never
    executes or evaluates content from event sources.
  - When an event is fed to the LLM (e.g. for a Visual Review
    annotation), the payload is wrapped in a clearly demarcated
    `<<EXTERNAL>>...<</EXTERNAL>>` block with a system instruction
    forbidding instructions from that block.
  - Comments and decisions are quoted, not summarized, by default.
- **Residual**: any LLM integration is inheritable risk; future gates
  must revisit.

### T5. Cross-product write escalation

- **Threat**: The Control UI attempts to mutate IA-VISION or SUINI product
  state directly, bypassing HERMES-ORCH.
- **Mitigation**:
  - The BFF has NO direct write path to either product repo. Cross-product
    writes are rejected at the BFF layer with `PRODUCT_OWNERSHIP_MISMATCH`.
  - Writes to SUINI `:8081` are not proxied through the BFF (no
    localhost cross-product proxy).
  - The BFF forwards any cross-product action to a HERMES-ORCH worker
    through the `peer dm` (composition B) or via comment-mediated dispatch
    on GitHub (composition A).
  - `authority-hierarchy.md` is enforced in code.
- **Residual**: visual review finding annotations are post-GitHub only
  when David has approved the next safe gate; until then they are
  persisted locally with `pending_post: true`.

### T6. Preview URL leakage

- **Threat**: A preview URL meant to be ticket-authenticated leaks to a
  public endpoint.
- **Mitigation**:
  - V0 does NOT proxy IA-VISION visor streams or SUINI `:8081`. Preview
    cards deep-link to the product's own URL convention; they do not
    inline any iframe.
  - When composition B activates, preview URL handling is delegated to the
    product's own authentication. The BFF never embeds a SUINI/IA-VISION
    preview URL with a token into its own pages.
- **Residual**: deep-linking still relies on the product's URL convention.
  Each product must promise its own URL is not world-accessible; the
  Control product never assumes it.

### Additional security minimums

- Header security: `Content-Security-Policy` with strict `default-src 'self'`,
  `frame-ancestors 'none'` (no embedding), `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: no-referrer`.
- Build pipeline: SRI hashes for every script + style; secrets scanner
  (`gitleaks` style) on every PR.
- Logging: redactor on all structured logs; no Authorization headers,
  API keys, or PATs ever logged.
- Dependency: lockfiles + `pip-audit` for Python and `npm audit` for
  JavaScript; CI blocks on CRITICAL severity.
- Deprovisioning: a `hermes control uninstall` command removes the BFF
  process, the evidence dir, and the loopback cookie jar.

---

## Architecture properties NOT included in V0

- Native iOS/Android apps (deferred; PWA-installable first).
- Cross-host visors (deferred; requires SUINI/IA-VISION contract
  authorization for the secure preview gateway).
- Multi-user tenancy (single-user loopback first; multi-user behind an
  external auth provider when tunneled).

These are documented so future iterations have a roadmap but stay out of
the V0 surface area, which keeps V0 small and reversible.
