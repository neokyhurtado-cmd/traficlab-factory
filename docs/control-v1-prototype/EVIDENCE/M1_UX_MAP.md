# M1 — Freeze the David-specific UX journey

10 required screens, each with explicit backend contract mapping.

Each screen is annotated with:

```
REAL_BACKEND_CONTRACT
AVAILABLE_NOW | PARTIAL | NOT_AVAILABLE_YET
READ_ONLY | CONTROL_ACTION
SOURCE_OF_TRUTH
FRESHNESS / RECONNECT BEHAVIOR
```

Constraints respected:
- Mobile-first, desktop parity (per #4 §Experience architecture)
- No Telegram, no Codex, no copy/paste required paths
- Cross-product ownership boundary: writes must route via HERMES-ORCH; reads may pull from public product sources when contract permits
- Touch-first, reduced-motion-aware, accessible

---

## 1. HOME / COMMAND

A combined entry surface. Mobile shows a single vertical scroll of active cards; desktop shows the same data plus a side rail.

```yaml
REAL_BACKEND_CONTRACT:
  Hermes /v1/capabilities (when API server enabled)  - NOT_AVAILABLE_YET (HUMAN_GO_REAL to enable)
  GitHub REST: /repos/{owner}/{repo}/pulls + issues   - AVAILABLE_NOW (public, read-only, no auth)
  Kanban DB (read via hermes kanban show)             - AVAILABLE_NOW (private, profile-scoped via CLI)
AVAILABLE_NOW: PARTIAL
  - Mission status + product health + HUMAN_GO queue visible
  - Chat send/stream requires live Hermes API server
READ_ONLY_or_CONTROL_ACTION:
  - Status cards: READ_ONLY
  - Command bar: CONTROL_ACTION (only after Hermes API server authorized + bearer key not exposed to browser)
SOURCE_OF_TRUTH:
  - Product state: product repo GitHub remote
  - HERMES-ORCH state: kanban DB at ~/.hermes/profiles/<profile>/state.db
  - VISOR state: NEVER this screen; visors stay in product lanes
FRESHNESS / RECONNECT:
  - Mission status card polls every 60s with If-None-Match (or ETag from GitHub)
  - Browser refresh must NOT dispatch duplicate goals
  - Reconnect dedupes by (project_id, run_id, sequence)
  - Stale events dropped after freshness budget = 2x poll interval
```

## 2. MISSION CONTROL

The "what is happening now" screen. Dense.

```yaml
REAL_BACKEND_CONTRACT:
  GitHub: /repos/{owner}/{repo}/pulls[?state=open]
  GitHub: /repos/{owner}/{repo}/issues[?state=open]
  Kanban DB: kanban list / show filtered by status in [ready, running, blocked, review]
  Hermes runs: POST /v1/runs + GET /v1/runs/{id}/events (SSE) - NOT_AVAILABLE_YET
AVAILABLE_NOW: PARTIAL (status cards only; live event feed requires Hermes API server)
READ_ONLY_or_CONTROL_ACTION:
  - READ_ONLY cards (Goals, Runs, Agents, Gateways, CI, Blockers, Events)
  - Selected run CANNOT be cancelled from Mission Control in V0; cancellation goes through
    a dedicated "advance/pause" screen reached by deep-linking to HERMES-ORCH.
SOURCE_OF_TRUTH:
  - Goals/Issues/PRs: GitHub remote (issuer of record)
  - Runs: kanban DB (local operational truth)
  - Agents/Gateways: Hermes profile list + gateway list output (CLI; surfaces as static JSON
    once read; auto-refresh on interval)
FRESHNESS / RECONNECT:
  - Cards re-fetch on focus + every 30s
  - Event feed (when enabled): SSE with Last-Event-ID; browser resumes; server dedupes
  - Reconnect budget = 5 exponential backoffs (1s, 2s, 4s, 8s, 16s capped 30s)
```

## 3. IA-VISION Project

Single-product deep view for IA-VISION.

```yaml
REAL_BACKEND_CONTRACT:
  GitHub: repos/neokyhurtado-cmd/IA-VISION/issues
  GitHub: repos/neokyhurtado-cmd/IA-VISION/pulls
  GitHub: repos/neokyhurtado-cmd/IA-VISION/commits
  IA-VISION visor URL: discovered from IA-VISION README / open issues (#4 lists PR #44
    "recovered visor/browser transport" as a fix; precise URL must come from the product's
    current main or human-confirmed contract)
AVAILABLE_NOW: PARTIAL (issues/PRs/commits yes; visor launch depends on IA-VISION product
  contract discovery — never assume visor path; the IA-VISION adapter gate must resolve it
  before V0 claims VISOR_AVAILABLE_NOW)
READ_ONLY_or_CONTROL_ACTION:
  - V0: READ_ONLY across all surfaces
SOURCE_OF_TRUTH:
  - IA-VISION product repo
  - IA-VISION product visor (canonical video/track/crossing data)
FRESHNESS / RECONNECT:
  - Same GitHub poll semantics as Mission Control
  - Visor deep-link is a new tab to the IA-VISION-visor URL; the TrafficLab Control
    does NOT proxy visual content in V0
```

## 4. SUINI Project

Single-product deep view for SUINI.

```yaml
REAL_BACKEND_CONTRACT:
  GitHub: repos/neokyhurtado-cmd/suini/issues
  GitHub: repos/neokyhurtado-cmd/suini/pulls
  SUINI runtime: http://localhost:8081 (canonical; NOT proxied through Control)
  Truth Lens state: SUINI product endpoint (URL TBD during SUINI adapter gate)
AVAILABLE_NOW: PARTIAL (issues/PRs/commits yes; runtime/Truth Lens state behind
  NEXT_SAFE_GATE: SUINI contract discovery. Per authority-hierarchy.md the SUINI
  adapter cannot bypass SUINI ownership — must consume via accepted product contract.)
READ_ONLY_or_CONTROL_ACTION:
  - V0: READ_ONLY
SOURCE_OF_TRUTH:
  - SUINI product repo
  - SUINI runtime (canonical simulation authority — Control never replicates)
  - Authority: HERMES-SUINI owns SUINI; Control never claims simulation truth
FRESHNESS / RECONNECT:
  - Same GitHub polling
  - SUINI runtime: V0 displays status as `NOT_AVAILABLE_YET` to the public
    network (localhost state is host-internal; cross-host preview is a
    future HUMAN_GO_GATE gate per #4 §D Preview gateway)
```

## 5. VISUAL REVIEW HUB — mandatory

This is the differentiator. Two review modes, never conflated.

### 5A. IA-VISION review mode

```yaml
REAL_BACKEND_CONTRACT:
  IA-VISION visor endpoint (when discovered) — review handoff via deep link in V0;
    iframe embedding is a NEXT_SAFE_GATE pending IA-VISION contract verification.
  Evidence capture: client-side canvas/PNG of the deep-linked viewport + frame ID +
    SHA/PR pinned to the review screenshot.
AVAILABLE_NOW: PARTIAL (visual review requires the IA-VISION visor URL; V0 prototype
  exposes the review shell UI + capture/persistence pipeline that records evidence
  even when the underlying visor link is placeholder.)
READ_ONLY_or_CONTROL_ACTION:
  - READ_ONLY over the IA-VISION visor
  - CONTROL_ACTION only to create a VisualReviewFinding artifact
SOURCE_OF_TRUTH:
  - Review finding: this Control product's evidence dir (durable JSON + screenshot)
  - Video/track data: IA-VISION product visor
FRESHNESS / RECONNECT:
  - Capture identity MUST include: PRODUCT, REPO, BASE_SHA, CANDIDATE_SHA/PR,
    URL/ROUTE, VIEWPORT, DATASET/VIDEO, FRAME_OR_SIM_TIME, CAPTURE_TIMESTAMP,
    SCREENSHOT_REF, USER_ANNOTATION, RESULT = PASS | FINDING | INCONCLUSIVE
  - A screenshot without identity is NOT acceptance evidence — UI enforces this contract.
  - Findings post to GitHub Issues via gh CLI from the Control backend only when
    David has authorized the next safe gate for write side; in V0 findings
    are saved locally and queued.
```

### 5B. SUINI review mode

```yaml
REAL_BACKEND_CONTRACT:
  SUINI Panorama/visor (canonical per #4). Currently documented at:
    http://localhost:8081 (host-internal).
  Truth Lens state via SUINI product endpoint (TBD).
AVAILABLE_NOW: PARTIAL (read paths same as SUINI Project screen)
READ_ONLY_or_CONTROL_ACTION:
  - READ_ONLY
SOURCE_OF_TRUTH:
  - Truth Lens / Provenance: SUINI canonical
  - Control never re-evaluates simulation truth. Review findings attach provenance
    metadata; Control does NOT compute its own Truth Lens value.
FRESHNESS / RECONNECT:
  - Same evidence identity contract as IA-VISION
  - Control page must visibly label visor state as OBSERVED / SIMULATED /
    SYNTHETIC / VALIDATED / EXTERNAL / WARNING / FAILED / UNKNOWN based on what
    SUINI reports; Control reads these values; it never invents them.
  - If SUINI runtime is unreachable from the user's network, screen shows
    `NOT_AVAILABLE_YET` and a deep-link back to SUINI product docs — never a
    placeholder image masquerading as canonical.
```

## 6. GOAL / RUN DETAIL

Deep dive on one goal or one run.

```yaml
REAL_BACKEND_CONTRACT:
  GitHub: GET /repos/{owner}/{repo}/issues/{number}
  GitHub: GET /repos/{owner}/{repo}/issues/{number}/comments
  Kanban DB: kanban show --task-id={id}
  Hermes: GET /v1/runs/{id}/events — NOT_AVAILABLE_YET (HUMAN_GO_REAL)
AVAILABLE_NOW: PARTIAL (GitHub + kanban; live event feed after API server authorized)
READ_ONLY_or_CONTROL_ACTION:
  - V0: READ_ONLY
SOURCE_OF_TRUTH:
  - GitHub remote (durable)
  - Kanban DB (operational)
FRESHNESS / RECONNECT:
  - Comments list re-fetches on focus; events feed SSE when enabled
  - task_id-level stale-event rejection: events with created_at older than the
    task's terminal state timestamp are dropped silently
```

## 7. PR / REVIEW LAB

Review Lab, unified diff + CI + tests + visual.

```yaml
REAL_BACKEND_CONTRACT:
  GitHub: GET /repos/{owner}/{repo}/pulls/{number}
  GitHub: GET /repos/{owner}/{repo}/pulls/{number}/commits
  GitHub: GET /repos/{owner}/{repo}/pulls/{number}/files
  GitHub: GET /repos/{owner}/{repo}/commits/{sha}/check-runs
  VisualReviewFinding: Control evidence dir
  HfGateway: gates/audit/evidence pulled from the related repo's tests dir
AVAILABLE_NOW: PARTIAL (GitHub REST yes; visual-findings integration yes when findings
  are produced by VISUAL REVIEW HUB; CI/rest details rely on public GitHub Checks API)
READ_ONLY_or_CONTROL_ACTION:
  - READ_ONLY — but PR Reviewer state advances trigger GitHub PR review submissions
    via gh CLI on an authorized code path; in V0 the action button is wired but
    gated behind David's explicit "post review" HUMAN_GO per touch.
SOURCE_OF_TRUTH:
  - PR metadata: GitHub
  - Visual findings: Control evidence dir, then promoted to GitHub review comment
  - CI: GitHub Checks (when authorized)
FRESHNESS / RECONNECT:
  - File diff immutable per PR head SHA; once committed, cache
  - Check-runs refetch every 30s while open
  - Reconnect resumes at last seen sequence
```

## 8. EVIDENCE TIMELINE

Single chronological stream per goal/run.

```yaml
REAL_BACKEND_CONTRACT:
  Composite: github events for the product repo (issues/comments/PRs/commits/checks)
  + Kanban DB events (status transitions)
  + VisualReviewFinding events (this product, when produced)
  + Hermes agent:start/end events - NOT_AVAILABLE_YET
AVAILABLE_NOW: PARTIAL (GitHub + kanban + visual findings yes; Hermes agent lifecycle
  events require API server + webhooks which need daemon/config enable.)
READ_ONLY_or_CONTROL_ACTION:
  - READ_ONLY
SOURCE_OF_TRUTH:
  - Each event subclass has its own source of truth:
    * Commits/PRs: GitHub
    * Status transitions: Kanban DB
    * Visual findings: Control evidence dir
    * Agent lifecycle: Hermes hook payload (future)
FRESHNESS / RECONNECT:
  - Stream items deduplicate by (source, event_id)
  - Stale-event rejection: items whose freshness header predates the last-seen
    event are dropped
  - Resume: client sends Last-Event-ID; server replays the tail
```

## 9. HUMAN-GO INBOX

The decision queue. Critical because it filters out non-decisions.

```yaml
REAL_BACKEND_CONTRACT:
  Decision cards produced by upstream tasks tagged "HUMAN_GO" in their task body.
  In V0: built offline by re-parsing open/ready/blocked kanban tasks for a
  `HUMAN_GO` marker in body or comments.
AVAILABLE_NOW: PARTIAL
  - V0 surface renders all decision-eligible open tasks, lets David filter by
    product, repo, urgency. A "real" inbox requires the API server + webhooks.
READ_ONLY_or_CONTROL_ACTION:
  - CONTROL_ACTION for APPROVE/REJECT/DEFER, each backed by a durable
    comment in the originating task + a transition to the next state
  - The CARD itself is the system of record; HUMAN_GO actions post here only.
SOURCE_OF_TRUTH:
  - Kanban DB (HERMES-ORCH operational truth)
  - GitHub Issues (durable evidence of the HUMAN_GO items themselves)
FRESHNESS / RECONNECT:
  - Inbox polls every 30s
  - Reconnect resumes from last seen task id
  - Duplicate actions from a refresh are deduped via (task_id, action, idempotency_key)
  - A HUMAN_GO action is never double-computed: the action endpoint requires
    a unique idempotency key generated client-side and stored in localStorage
    AND in-memory; refresh uses the cached key.
```

## 10. SYSTEM HEALTH

Operational status of HERMES-ORCH and the two product lanes.

```yaml
REAL_BACKEND_CONTRACT:
  Hermes: hermes gateway list --json (CLI; in V0 read via subprocess)
  Hermes: hermes profile list --json
  Hermes: hermes serve --status (when applicable)
  GitHub status: anonymous check via GET / (HEAD-only)
AVAILABLE_NOW: AVAILABLE_NOW (CLI read in V0)
READ_ONLY_or_CONTROL_ACTION:
  - READ_ONLY diagnostic surface
SOURCE_OF_TRUTH:
  - Local Hermes state (CLI invocations)
FRESHNESS / RECONNECT:
  - Refresh on focus + every 60s
  - Each subsystem card shows: name, status, last check, last error, action
```

---

## Cross-screen contracts

The same 4 contracts are reused by multiple screens. Always pinned:

1. **Identity minimum** in every event/evidence item:
   ```
   schema_version
   correlation_id
   project_id            (GLOBAL | IA-VISION | SUINI | CONTROL)
   goal_id               (GitHub issue number or kanban task id)
   run_id                (kanban task id)
   event_id / sequence
   source                (github | kanban | hermes | control-ui | visor)
   kind                  (action-specific)
   created_at            (RFC 3339, UTC)
   freshness             (seconds since created_at)
   idempotency_key       (when applicable)
   payload_ref / evidence_ref
   ```
2. **Reconnect semantics**: every stream endpoint must support a resume cursor. A browser refresh must NOT create a duplicate task or send a duplicate event. SSE endpoints use Last-Event-ID; poll endpoints use If-None-Match / ETag; webhook receivers persist received event_ids and dedupe.
3. **Stale-event rule**: events with `freshness > 2 * max_expected_interval` are dropped silently from the UI but retained in the durable evidence dir.
4. **Cross-product write guard**: any CONTROL_ACTION that aims at IA-VISION or SUINI data must be routed via HERMES-ORCH. The Control UI never talks to a product repo's mutation API directly. Authority-hierarchy.md enforces this; the V0 enforces it in code.

## Mobile-first vs desktop parity rule

Every screen ships with two layouts:
- **phone** (< 640 px): single column, full-width cards, big touch targets ≥ 44 px, sticky bottom command bar
- **desktop** (≥ 1024 px): dashboard grid + side nav + larger tables + diff viewer + inspector panels

No hover-only controls. Reduced-motion media query honored. Status semantics beyond color (icons + text labels).

## What this M1 does NOT yet cover

- Pixel-perfect visual identity. The visual language ("scientific + cinematic + operational") is M5/V1 work, beyond tonight's V0.
- Native iOS/Android app. PWA-installable first; native is a future gate.
- Backend authority. M3 defines the read models and event/correlation contract.
