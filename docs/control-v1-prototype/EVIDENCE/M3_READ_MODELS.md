# M3 — Control read model + event/correlation contract

Provider-neutral schemas. These are Control read models, not new product-domain
authorities. IA-VISION and SUINI remain the canonical authorities for their own
domain semantics (Truth Lens, calibration, model lineage, simulation runs,
etc.). The Control read models are the shape the UI consumes; the underlying
authority never migrates.

---

## Read models

### ProjectSummary

```json
{
  "schema_version": "control.project.summary/v1",
  "project_id": "GLOBAL | IA-VISION | SUINI | TRAFFICLAB-CONTROL",
  "display_name": "string",
  "repo": "neokyhurtado-cmd/<repo>",
  "default_branch": "main",
  "remote_head_sha": "string (40-char git sha)",
  "remote_head_short": "string",
  "open_issues": "integer >= 0",
  "open_prs": "integer >= 0",
  "last_remote_push_at": "RFC 3339, UTC",
  "visor_entrypoint": "string | null (URL convention, never localhost unless same-host)",
  "visor_state_in_control": "AVAILABLE_NOW | PARTIAL | NOT_AVAILABLE_YET",
  "owner_worker": "HERMES-IA | HERMES-SUINI | HERMES-ORCH",
  "control_layer": "HERMES-ORCH (per authority-hierarchy.md)"
}
```

### GoalSummary

```json
{
  "schema_version": "control.goal.summary/v1",
  "goal_id": "string (GitHub issue number as string for product goals; kanban task id for control goals)",
  "project_id": "ProjectSummary.project_id",
  "title": "string",
  "body": "string (truncated to 1024 chars in summary; full body fetched on detail)",
  "state": "open | closed | merged | done | blocked | ready | running",
  "labels": ["array of strings"],
  "assignees": ["array of strings"],
  "milestone": "string | null",
  "url": "string (canonical)",
  "created_at": "RFC 3339, UTC",
  "updated_at": "RFC 3339, UTC",
  "kind": "PRODUCT_GOAL | CONTROL_GOAL | AUTO_DISPATCH | MACRO_GOAL",
  "macro_parent_id": "string | null",
  "human_go_required": "boolean",
  "blocked_by_external": "boolean",
  "evidence_refs": [
    {"ref_type": "github_pr | github_commit | screenshot | visor_capture | control_finding | hermes_run | kanban_run",
     "uri": "string",
     "label": "string"}
  ]
}
```

### RunSummary

```json
{
  "schema_version": "control.run.summary/v1",
  "run_id": "string (kanban task id)",
  "goal_id": "GoalSummary.goal_id",
  "project_id": "ProjectSummary.project_id",
  "title": "string",
  "assignee": "string",
  "status": "ready | running | review | blocked | done",
  "started_at": "RFC 3339, UTC | null",
  "ended_at": "RFC 3339, UTC | null",
  "runtime_owner_pid": "integer | null",
  "runtime_session_id": "string | null",
  "result_summary": "string | null",
  "artifacts": [
    {"label": "string", "absolute_path": "string"}
  ],
  "git": {
    "branch": "string | null",
    "head_sha": "string | null",
    "pr_url": "string | null"
  }
}
```

### AgentSummary

```json
{
  "schema_version": "control.agent.summary/v1",
  "agent_id": "string (profile-name)",
  "display_name": "string",
  "model": "string",
  "provider": "string",
  "gateway_pid": "integer | null",
  "gateway_status": "running | stopped",
  "last_activity_at": "RFC 3339, UTC | null",
  "active_runs": ["array of run_id"],
  "platforms": ["telegram | discord | whatsapp | api_server | mcp | acp | webhook"]
}
```

### HumanGoDecision

```json
{
  "schema_version": "control.humango.decision/v1",
  "decision_id": "string (idempotency_key)",
  "task_id": "RunSummary.run_id",
  "goal_id": "GoalSummary.goal_id",
  "project_id": "ProjectSummary.project_id",
  "title": "string",
  "one_sentence_decision": "string",
  "why_now": "string",
  "consequences_if_yes": "string",
  "consequences_if_no": "string",
  "consequences_if_defer": "string",
  "evidence_refs": [{"ref_type": "uri", "label": "string"}],
  "affected": {
    "repo": "string",
    "branch": "string | null",
    "pr_url": "string | null",
    "sha": "string | null"
  },
  "reversible": "boolean",
  "irreversible_classification": "string | null",
  "created_at": "RFC 3339, UTC",
  "expires_at": "RFC 3339, UTC | null",
  "expires_action": "string | null",
  "status": "open | approved | rejected | deferred | expired",
  "decided_at": "RFC 3339, UTC | null",
  "decided_by": "string | null",
  "decision_note": "string | null"
}
```

### EvidenceItem

```json
{
  "schema_version": "control.evidence.item/v1",
  "evidence_id": "string (uuidv7 in control)",
  "ref_type": "github_pr | github_commit | github_comment | test_report | preview_screenshot | visor_capture | control_finding | hermes_run | kanban_run | obsidian_doc",
  "uri": "string",
  "label": "string",
  "captured_at": "RFC 3339, UTC",
  "produced_by": "string (worker or 'control-ui')",
  "linked_goal": "GoalSummary.goal_id | null",
  "linked_run": "RunSummary.run_id | null",
  "linked_decision": "HumanGoDecision.decision_id | null",
  "identity": {
    "product": "string",
    "repo": "string",
    "base_sha": "string | null",
    "candidate_sha_pr": "string | null",
    "preview_build_id": "string | null",
    "url_route": "string | null",
    "viewport": "string | null",
    "dataset_video_network_scenario_run": "string | null",
    "frame_or_sim_time": "string | null",
    "capture_timestamp": "RFC 3339, UTC | null"
  }
}
```

### PreviewTarget

```json
{
  "schema_version": "control.preview.target/v1",
  "preview_id": "string",
  "project_id": "ProjectSummary.project_id",
  "product": "IA-VISION | SUINI",
  "kind": "video_review | panorama | visor | dashboard | decision_workspace",
  "entry_url": "string (HTTPS, never inline raw shell)",
  "visibility": "public_readonly | signed_token | loopback_only | internal_only",
  "expires_at": "RFC 3339, UTC | null",
  "revocable": "boolean",
  "internal_route_owner": "HERMES-IA | HERMES-SUINI",
  "preview_build_id": "string | null",
  "identity": {
    "repo": "string",
    "sha_or_pr": "string",
    "network_scenario_run": "string | null",
    "video_id": "string | null"
  },
  "state": "AVAILABLE_NOW | PARTIAL | NOT_AVAILABLE_YET | UNREACHABLE_FROM_NETWORK",
  "captured_at": "RFC 3339, UTC"
}
```

### VisualReviewFinding

```json
{
  "schema_version": "control.visual.finding/v1",
  "finding_id": "string (uuidv7)",
  "reviewer": "string",
  "project_id": "ProjectSummary.project_id",
  "product_kind": "IA-VISION | SUINI",
  "review_mode": "IA-VISION_REVIEW | SUINI_REVIEW",
  "identity": {
    "product": "string",
    "repo": "string",
    "base_sha": "string | null",
    "candidate_sha_pr": "string | null",
    "preview_build_id": "string | null",
    "url_route": "string",
    "viewport": "string (e.g., 'phone-393x852' or 'desktop-1440x900')",
    "dataset_video_network_scenario_run": "string",
    "frame_or_sim_time": "string",
    "capture_timestamp": "RFC 3339, UTC"
  },
  "screenshot_ref": {"ref_type": "preview_screenshot", "uri": "string"},
  "annotation": "string",
  "result": "PASS | FINDING | INCONCLUSIVE",
  "summary": "string (one-sentence)",
  "linked_goal": "GoalSummary.goal_id | null",
  "linked_run": "RunSummary.run_id | null",
  "linked_decision": "HumanGoDecision.decision_id | null",
  "created_at": "RFC 3339, UTC"
}
```

### HealthSnapshot

```json
{
  "schema_version": "control.health.snapshot/v1",
  "snapshot_id": "string (uuidv7)",
  "captured_at": "RFC 3339, UTC",
  "hermes": {
    "version": "string",
    "default_pid": "integer | null",
    "default_role": "string | null",
    "multiplex": "boolean",
    "profiles": [
      {"name": "string", "model": "string", "gateway_status": "running | stopped"}
    ],
    "serve_running": "boolean",
    "dashboard_running": "boolean",
    "api_server_enabled": "boolean",
    "webhook_enabled": "boolean",
    "mcp_servers_count": "integer",
    "peers_count": "integer",
    "hooks_count": "integer",
    "platforms_live": ["telegram | discord | whatsapp | api_server | mcp | acp | webhook"]
  },
  "products": {
    "IA-VISION": {"remote_head_sha": "string", "open_issues": "integer", "open_prs": "integer"},
    "SUINI":     {"remote_head_sha": "string", "open_issues": "integer", "open_prs": "integer"}
  },
  "config_changed": "boolean",
  "env_changed": "boolean",
  "product_repo_changed": "boolean",
  "public_port_open": "boolean"
}
```

---

## Event/correlation identity minimum

Every event flowing through the Control BFF carries:

```text
schema_version      : control.event/v1
correlation_id      : uuidv7 (groups all events for one user-action)
project_id          : ProjectSummary.project_id
goal_id             : GoalSummary.goal_id (when applicable)
run_id              : RunSummary.run_id (when applicable)
event_id            : uuidv7 (unique per event)
sequence            : integer (monotonic per (correlation_id))
source              : "github" | "kanban" | "hermes" | "control-ui" | "visor"
kind                : string (semantic event type, e.g. "goal.created",
                      "run.status.changed", "evidence.added",
                      "decision.humango.opened", "agent.started", etc.)
created_at          : RFC 3339, UTC, with millisecond precision
freshness_seconds   : integer (computed at receive time)
idempotency_key     : string (when the event is the result of an action)
payload_ref         : EvidenceItem reference or uri
evidence_ref        : EvidenceItem reference (when applicable)
```

### Reconnect/dedupe/stale rules

- **Reconnect**: the client passes `Last-Event-ID` and `sequence` to the BFF
  stream endpoint. The BFF replays the tail from the durable event log and
  tags each event with the `sequence` value the client last saw. The client
  accepts events with `sequence > last_seen` and dedupes by `event_id`. SSE
  used when available; HTTP polling with If-None-Match is the fallback.
- **Stale-event rejection**: an event whose `(received_at - created_at) >
  freshness_budget` is dropped from the UI render but retained in the durable
  log. Default `freshness_budget = 2 * stream_poll_interval`. Bounded to 5
  minutes for SSE sources and 30 minutes for polling sources.
- **Reconnect deduplication**: a client receiving the same `event_id` twice is
  de-duplicated. The BFF and the durable log are both idempotent on
  `(source, event_id)` keys.
- **Browser refresh must NOT create a second task**: any POST action carries
  an `idempotency_key` generated client-side and stored in localStorage AND
  in-memory. The BFF rejects duplicate `(idempotency_key, project_id,
  action_kind)` tuples within a 1-hour window with a 409 + the original
  response payload.
- **No duplicate task creation from observer perspective**: the Control BFF
  treats events as durable. Even if a worker is asked twice, the BFF records
  one canonical task and shows the worker response.

### Read-model authority

- A Control read model is **never** a new authority over IA-VISION or SUINI
  domain semantics (Truth Lens, simulation state, calibration, model lineage,
  tracks/crossings/speeds, etc.). The read model consumes the product's
  authoritative payload or the GitHub durable record and renders it.
- Cross-product write guard: a CONTROL_ACTION targeting a non-Control
  product MUST be routed via HERMES-ORCH. The BFF enforces this: any
  CONTROL_ACTION whose target contains a `product_invariant_write` key is
  rejected unless the request body's `route_owner` is the matching
  `HERMES-IA` or `HERMES-SUINI` and the action was forwarded by ORCH.

---

## BFF endpoints (composition A; composition B documented but disabled)

```text
GET    /api/projects                      -> [ProjectSummary]
GET    /api/projects/{project_id}         -> ProjectSummary
GET    /api/projects/{project_id}/goals   -> [GoalSummary]
GET    /api/goals/{goal_id}               -> GoalSummary (full body)
GET    /api/runs                          -> [RunSummary]
GET    /api/runs/{run_id}                 -> RunSummary (result detail)
GET    /api/runs/{run_id}/events          -> SSE stream or polling (Resume-Token: <sequence>)
GET    /api/agents                        -> [AgentSummary]
GET    /api/decisions/humango             -> [HumanGoDecision]
POST   /api/decisions/{decision_id}       -> HumanGoDecision (write; gated)
GET    /api/evidence                      -> [EvidenceItem]
GET    /api/previews/{preview_id}         -> PreviewTarget
GET    /api/health                        -> HealthSnapshot
GET    /api/events/stream                 -> SSE stream of ControlEvent, Resume-Token: <sequence>
```

All endpoints include `If-None-Match` / `ETag` for polling. SSE streams accept
`Last-Event-ID` and `Resume-Token`. Errors return RFC 7807 Problem+JSON.

---

## Storage layout (composition A — durable evidence on disk)

```text
~/.hermes/control-v1/
  evidence/
    findings/
      2026-09-09T07-00-00Z_<uuid>.json     # VisualReviewFinding
      2026-09-09T07-00-00Z_<uuid>.png      # associated screenshot
    review-state/
      finding_<uuid>.json                  # per-finding state
  log/
    events.jsonl                            # append-only ControlEvent log
    polling-cache.jsonl                     # Idempotency cache
    humango-cache.jsonl                     # HUMAN_GO idempotency
  snapshots/
    health_<utc>.json                       # HealthSnapshot
```

This is durable, git-ignorable, and lives entirely on the same host that owns
the Control BFF. No product repo is mutated by the Control BFF in composition A.

---

## Versioning

- All schemas carry `schema_version: control.<name>/v1`. Bumping to v2 requires
  a new key (`v2_*` fields or separate endpoint). The BFF refuses to render
  data with an unknown `schema_version` and emits a `schema_version.unknown`
  warning event in its own event log.
- Backward compatibility is supported within the v1 schema for additive
  optional fields. Required-field additions are a v2.
