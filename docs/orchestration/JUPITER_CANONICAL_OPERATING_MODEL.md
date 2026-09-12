# JUPITER Canonical Operating Model

**Policy ID:** `JUPITER-COM-1.1`  
**Status:** PROPOSED VERSIONED CANONICAL SOURCE; OWNER policy effective via `traficlab-factory#18` comments `5643135371` and `5643225198`  
**Scope:** projects registered in `orchestrator/config/routing.yaml`  
**Normative owner decisions:** `traficlab-factory#18#issuecomment-5643135371`, `traficlab-factory#18#issuecomment-5643225198`

## 1. Purpose

This document removes an ambiguity that existed between three already-documented truths:

1. `traficlab-factory#18` defines `[ASTRA_DIRECTIVE:v1]` as a fail-closed trusted ingress that wakes/dispatches Hermes Director and produces durable ACK/RESULT evidence.
2. `orchestrator/README.md` and `orchestrator/config/routing.yaml` define HERMES-ORCH as the single routing/polling authority for registered repositories.
3. Product-level workflows such as `SUINI#40` allow reversible same-scope review/fix iterations to continue without a new human micro-GO.

The missing rule was whether such continuation remains inside JUPITER ownership or bypasses JUPITER. `JUPITER-COM-1` resolved that explicitly. `JUPITER-COM-1.1` further freezes the operating posture of Hermes Director: conversational director first, multi-task delegation through JUPITER, mandatory Mission Control alignment, and active supervision of dispatched agents.

## 2. Audit classification

### DOCUMENTED before JUPITER-COM-1

- Hermes Director is the execution orchestration role (`traficlab-factory#18`).
- GitHub is durable truth (`traficlab-factory#18`).
- Structured `[ASTRA_DIRECTIVE:v1]` comments are the executable trusted ingress for the Directive Watcher; free-form prose is information only.
- ACK/RESULT binds source comment, directive and execution IDs.
- `orchestrator/scripts/github_poller.py` is the single production polling/tick authority for WO + directive ingestion.
- `orchestrator/config/routing.yaml` is the repo -> product -> assignee routing authority; unknown repos fail closed.
- SUINI is registered in the canonical routing table.
- Protected boundaries require `HUMAN_GO_REAL`; a directive cannot manufacture authorization.
- Same directive/restart/race handling is expected to be idempotent and exactly-once.

### INFERRED before JUPITER-COM-1

- That a worker continuing a same-scope reversible fix loop could be treated as a continuation of an already-owned JUPITER execution rather than a new independent execution.
- That JUPITER ownership could persist without issuing a fresh directive/ACK on every micro-iteration.

### NOT_DOCUMENTED before JUPITER-COM-1

- A global rule separating the orchestration plane from the authorization plane.
- `JUPITER_ALWAYS_IN_EXECUTION_PATH` semantics for registered projects.
- Explicit continuation semantics for `CHANGES_REQUESTED -> FIX -> TEST -> NEW SHA -> RE-REVIEW`.
- A compact durable execution record that survives micro-iterations without comment spam.
- Explicit rules preventing a new directive from accidentally creating a second writer over an already-active scope.

### CONTRADICTORY / AMBIGUOUS before JUPITER-COM-1

`SUINI#40` contained both:

- owner instructions requiring JUPITER to be the real orchestration surface for subsequent macroturns; and
- a later clarification saying ordinary review/fix work must not wait on a new JUPITER dispatch.

Those statements are compatible only if routing/orchestration and authorization are separated. This document makes that compatibility normative.

## 3. Canonical policy

```text
JUPITER_POLICY_SCOPE = REGISTERED_PROJECTS_ONLY
REGISTRATION_AUTHORITY = orchestrator/config/routing.yaml
JUPITER_ALWAYS_IN_EXECUTION_PATH = YES
ORCHESTRATION_PLANE = JUPITER / HERMES-ORCH
ROUTING_IS_AUTHORIZATION = NO
ONE_ACTIVE_WRITER_PER_SCOPE = YES
DIRECT_PARALLEL_HERMES_WRITER = NO
HERMES_ROLE = CONVERSATIONAL_DIRECTOR
DIRECTOR_SELF_EXECUTION_MAX = 1_ATOMIC_TASK
MULTI_TASK_WORK = MUST_DELEGATE_THROUGH_JUPITER
MISSION_CONTROL_VISIBILITY = REQUIRED
DIRECTOR_IDLE_MODE = ACTIVE_AGENT_SUPERVISION
```

For every registered project, all technical execution belongs logically to a JUPITER execution context. A worker may act locally or on another host, but it is a worker **under** the orchestration plane, not a replacement for it.

`JUPITER_ALWAYS_IN_EXECUTION_PATH = YES` does **not** mean every file edit must trigger a fresh dispatch. It means execution ownership, lifecycle, single-writer state and durable evidence remain attributable to JUPITER.

## 4. Orchestration plane

The orchestration plane owns:

```text
execution ownership
single-writer arbitration
worker dispatch
execution lifecycle
run/session identity
gate state
branch/head continuity
evidence/result collection
recovery/handoff state
```

Canonical value:

```text
ORCHESTRATION_PLANE = JUPITER / HERMES-ORCH
```

The current implementation is composed from the existing HERMES-ORCH routing/poller, Directive Watcher, OrchestratorDispatcher, kanban primitive and session/evidence records. Do not create a second scheduler, router or orchestration truth to implement this policy.

## 5. Authorization plane

The authorization plane determines what the execution is allowed to do.

```text
AUTHORIZATION_PLANE =
  standing OWNER goal/scope
  + explicit owner/directive scope when required
  + HUMAN_GO_REAL at protected boundaries
```

Authorization includes:

- approved product goal and reversible scope;
- protected files/domains and scientific/product constraints;
- whether a new macro-goal is in scope;
- merge/main/release/deploy/destructive boundaries;
- secrets, credentials, providers, runtime/global configuration and other protected changes.

A route or active JUPITER session is not authorization to cross those boundaries.

## 6. Standing execution and continuation semantics

Once an authorized scope has an active JUPITER execution context, ordinary reversible iterations continue inside that context.

```text
REVIEW
  -> CHANGES_REQUESTED
  -> REMEDIATING
  -> TESTING
  -> NEW_SHA
  -> INDEPENDENT_REREVIEW
  -> PASS | CHANGES_REQUESTED
```

For this loop:

```text
NEW_ASTRA_DIRECTIVE = NO
NEW_HUMAN_GO_REAL = NO
NEW_JUPITER_AUTHORIZATION = NO
NEW_WRITER = NO
JUPITER_OWNERSHIP_CONTINUES = YES
```

The worker may be `HERMES-ASHLEY-01`, MiniMax, Director Shadow/Codex or another assigned execution/review worker. Their identity does not replace the orchestration plane.

## 7. Review/fix semantics

Canonical meaning of:

```text
CHANGES_REQUESTED -> HERMES FIX
```

is:

```text
JUPITER / HERMES-ORCH
  -> active EXECUTION_GROUP
     -> current single-writer worker
        -> fix
        -> tests
        -> new SHA
        -> re-review
```

It is **not** canonical as:

```text
Ashley -> independent direct Hermes writer -> fix outside JUPITER
```

A same-scope continuation does not require `WAITING_JUPITER_DISPATCH` because ownership already exists.

## 8. When a new ASTRA_DIRECTIVE is required

A new `[ASTRA_DIRECTIVE:v1]` is required when a fresh trusted ingress/claim is needed, including:

1. a new macro-goal or owner-requested action not covered by the active standing scope;
2. a new cross-host dispatch when no valid active execution context already owns the work;
3. wake/resume when there is no active execution or the prior execution is closed/abandoned;
4. recovery/re-dispatch after stale or failed ownership where a new claim is required;
5. a fresh exact-head JUPITER route proof when a gate explicitly requires a new round-trip;
6. an explicit Astra/Owner action that is intended to enter through the Directive Watcher.

The Directive Watcher remains fail-closed on repository, issue, branch/head, author, directive ID, protected boundary and stale context.

## 9. When a new ASTRA_DIRECTIVE is NOT required

No fresh directive is required for ordinary reversible work already inside an authorized active execution context, including:

- review -> fix;
- correction of a test failure;
- correction of documentation;
- implementation adjustment explicitly requested by the current review;
- rerunning tests/evidence;
- pushing a new SHA on the same authorized feature branch;
- requesting independent re-review;
- repeating the review/fix loop until the current gate resolves.

These are continuation events, not new authorization events.

## 10. Single-writer protocol

```text
ONE ACTIVE WRITER PER SCOPE = REQUIRED
```

A scope is identified by enough context to prevent destructive overlap, normally:

```text
PROJECT + GOAL/EXECUTION_GROUP + BRANCH + CURRENT_GATE
```

Rules:

1. If an execution context has an active writer, no new directive may create a parallel writer for the same scope.
2. A worker continuing the same context is `CONTINUATION = YES`, `NEW_WRITER = NO`.
3. New overlapping directives are denied, queued, or marked superseded until ownership is released.
4. `EXPECTED_HEAD` binding remains fail-closed. A stale directive must never be used to claim a newer head.
5. Ownership can transfer only through an explicit durable handoff/recovery state.

## 11. Durable evidence minimum

Every active JUPITER execution must be reconstructable from durable state with at least:

```text
ORCHESTRATOR = JUPITER
EXECUTION_GROUP = <stable logical group>
EXECUTION_ID = <claim/execution id>
JUPITER_RUN_OR_SESSION_ID = <physical/logical run or session id>
ACTIVE_WORKER = <current writer/executor>
CURRENT_GATE = <gate name>
CURRENT_BRANCH = <branch>
START_HEAD = <sha>
CURRENT_HEAD = <sha>
OWNER_SCOPE = <bounded authorized scope reference>
LAST_REVIEW = <review/comment/id/verdict>
CURRENT_STATE = <state>
NEXT_ACTION = <next safe action>
```

### Durable callback events

GitHub callbacks are required for material lifecycle events, not every micro-action:

- first claim/start of execution group;
- worker ownership transfer;
- gate transition;
- protected-boundary stop;
- blocked external/scientific decision;
- explicit route-proof gate;
- recovery from stale/failed execution;
- terminal PASS/DONE/result.

Ordinary edits, individual test runs and local substeps should remain in commits, PR evidence and execution logs unless they materially change state.

## 12. ACK/RESULT semantics

`[HERMES_ACK:v1]` and `[HERMES_RESULT:v1]` remain the canonical Directive Watcher round-trip for **new directive claims**.

They are not required to be re-issued for every same-scope micro-iteration inside one active execution group.

A long-lived execution may therefore contain many SHAs/reviews while retaining one logical execution group. A new ACK/RESULT pair is required when a new directive claim creates a new execution/recovery/route-proof round-trip.

## 13. HUMAN_GO_REAL boundaries

JUPITER-COM-1.1 does not loosen protected-boundary policy.

Unless separately and explicitly authorized by the governing product contract, stop for HUMAN_GO_REAL before:

- merge to main/protected branch;
- release/deploy;
- secrets/tokens/credentials;
- provider/model/global runtime configuration;
- destructive filesystem/data operations;
- other irreversible or owner-reserved decisions.

A reviewer may request reversible fixes without HUMAN_GO_REAL. A worker may execute them automatically while remaining inside the active JUPITER context.

## 14. Cross-host behavior

A new cross-host dispatch requires a fresh trusted dispatch event **when no valid active JUPITER execution context already owns that remote worker/session**.

If the current execution already owns and tracks that worker/session, same-scope continuation does not require another directive merely because another host is involved.

Every physical handoff must preserve the execution group, current head, owner scope and single-writer identity.

## 15. Recovery and stale-HEAD behavior

If an execution becomes stale, dies, loses its worker, or cannot prove current-head ownership:

```text
CURRENT_STATE = RECOVERY_REQUIRED | STALE
NEW_WRITES = STOP until ownership is resolved
```

Recovery must determine whether the original writer is alive. It must never start a second writer speculatively.

If a new claim is required, emit a new directive with fresh context and exact head. Old directives with stale `EXPECTED_HEAD` remain non-executable.

## 16. Project applicability

```text
JUPITER_POLICY_SCOPE = REGISTERED_PROJECTS_ONLY
```

A project enters this model when it is registered in `orchestrator/config/routing.yaml` (or a future explicitly designated successor canonical registry).

As of this policy creation, the routing table includes SUINI, IA-VISION and traficlab-factory itself. Unknown repos fail closed and are not silently treated as JUPITER-managed projects.

This is therefore neither `SUINI_ONLY` nor an unbounded claim over every repository Hermes might ever see.

## 17. SUINI #40 reconciliation

For `SUINI-CLOSE-40-v1`:

```text
SUINI_JUPITER_ALWAYS_IN_PATH = YES
SUINI_DIRECT_ASHLEY_TO_HERMES_CANONICAL = NO
REVIEW_FIX_REQUIRES_NEW_ASTRA_DIRECTIVE = NO
REVIEW_FIX_REQUIRES_NEW_HUMAN_GO = NO
REVIEW_FIX_REMAINS_UNDER_JUPITER_OWNERSHIP = YES
JUPITER_ROUTE_PROOF_BEFORE_F2 = YES
CURRENT_F1_REMEDIATION_CONTINUES = YES
```

The four F1 findings already authorized by review `5184860576` remain authorized for remediation. Governance clarification must not stop that work unless a real concurrent-writer conflict, protected boundary or material owner contradiction appears.

Earlier SUINI interpretations are reconciled as follows:

- comments requiring JUPITER as the real orchestration surface remain valid;
- the comment allowing direct same-scope remediation remains valid **as authorization semantics**;
- any reading that turns that remediation into an execution outside JUPITER is superseded;
- any reading that requires a fresh directive for every review/fix iteration is also superseded.

## 18. Industrialization guard

The protocol exists to prevent recurrence of the same ambiguity.

Every future orchestration implementation or workflow for registered projects must be reviewable against these invariants:

```text
INV-1  one canonical routing authority
INV-2  one active writer per scope
INV-3  orchestration != authorization
INV-4  continuation does not create a new writer
INV-5  no micro-directive for same-scope reversible fix loops
INV-6  protected boundaries still require their owner gate
INV-7  stale HEAD fails closed
INV-8  durable execution identity survives review/fix iterations
INV-9  GitHub records material state transitions without micro-step spam
INV-10 unknown/unregistered repos fail closed
INV-11 Hermes Director self-executes at most one atomic task
INV-12 multi-task work is decomposed and delegated through JUPITER
INV-13 Mission Control reflects every active execution group and material task state
INV-14 Hermes enters active supervision while delegated workers are active
```

Do not create a second architecture, scheduler, router, directive protocol or shadow execution registry to enforce these rules. Extend the existing HERMES-ORCH / Directive Watcher / session-state mechanisms.

## 19. Canonical route diagram

```text
OWNER / ASHLEY product decision
        |
        | approved scope / directive when required
        v
HERMES DIRECTOR                           <- CONVERSATIONAL DIRECTOR
        |
        +--> exactly one atomic task? ---- YES ---> may execute directly
        |
        +--> multiple/separable tasks ---- YES ---> JUPITER decomposition + dispatch
                                                    |
                                                    v
                                             worker(s) / reviewer(s)
                                                    ^
                                                    |
                                             ACTIVE SUPERVISION
                                                    ^
                                                    |
JUPITER / HERMES-ORCH -------------------- MISSION CONTROL
        |
        v
active EXECUTION_GROUP
        |
        +--> fix / build / test / evidence
        +--> review -> CHANGES_REQUESTED -> fix -> re-review
        +--> same-scope reversible loops continue automatically
        |
        v
JUPITER durable state / evidence
        |
        +--> next reversible gate automatically when standing scope allows
        +--> HUMAN_GO_REAL only at protected boundary
        v
OWNER / independent review at required gates

NO MICRO-GO FOR REVERSIBLE SAME-SCOPE WORK
NO NEW ASTRA_DIRECTIVE FOR ORDINARY REVIEW/FIX CONTINUATION
NO DIRECT PARALLEL HERMES WRITER OUTSIDE JUPITER
HERMES DIRECTOR STAYS CONVERSATIONALLY AVAILABLE
MULTI-TASK WORK IS DELEGATED THROUGH JUPITER
MISSION CONTROL MUST MATCH REAL EXECUTION STATE
NO PASSIVE IDLE WHILE DISPATCHED AGENTS ARE ACTIVE
```

## 20. Hermes Director operating posture — JUPITER-COM-1.1

### Rule 1 — conversational director, not primary builder

Hermes Director must remain primarily conversational, supervisory and available to David/Ashley.

```text
DIRECTOR_SELF_EXECUTION_MAX = 1_ATOMIC_TASK
```

Hermes may personally execute one bounded atomic task when that task is the entire current unit of work. If the work contains two or more separable tasks, a multi-step implementation, parallelizable investigation/build/review, or would occupy Hermes as a long-running worker, Hermes must decompose and delegate through JUPITER.

```text
ONE_ATOMIC_TASK = DIRECTOR_MAY_EXECUTE
TWO_OR_MORE_TASKS = JUPITER_DELEGATION_REQUIRED
DIRECTOR_LONG_RUNNING_BUILD_WORKER = NO
DIRECTOR_MUST_REMAIN_CONVERSATIONALLY_AVAILABLE = YES
```

Delegation does not remove Hermes accountability. The Director remains responsible for decomposition, dispatch, supervision, integration, evidence quality and return of the result.

### Rule 2 — mandatory Mission Control alignment

Every active execution group must be represented in Mission Control or its canonical successor state surface. David, Ashley, Astra and Hermes must be able to reconstruct what is happening without asking individual workers.

Minimum shared state:

```text
EXECUTION_GROUP
CURRENT_GOAL
CURRENT_GATE
ACTIVE_WORKERS
TASKS_DISPATCHED
TASK_OWNER
CURRENT_BRANCH
CURRENT_HEAD
CURRENT_STATE
LAST_RESULT_OR_REVIEW
BLOCKERS
NEXT_ACTION
```

```text
MISSION_CONTROL_ALIGNED = REQUIRED
HIDDEN_ACTIVE_TASKS = FORBIDDEN
STATE_DRIFT_BETWEEN_JUPITER_AND_MISSION_CONTROL = DEFECT
```

Local worker logs are allowed, but material lifecycle/state must reconcile back to Mission Control/JUPITER.

### Rule 3 — active supervision instead of idle

If Hermes has no new owner-facing task to dispatch while workers or reviewers from its execution group remain active, Hermes enters `ACTIVE_SUPERVISION`.

```text
NO_NEW_TASK + ACTIVE_WORKERS = ACTIVE_SUPERVISION
PASSIVE_IDLE_WHILE_WORKERS_ACTIVE = NO
SUPERVISION_DOES_NOT_MEAN_SECOND_WRITER = YES
```

Active supervision includes:

- checking progress and scope adherence;
- resolving context/questions that do not require OWNER decisions;
- ensuring tests and evidence are real, non-vacuous and tied to the right SHA;
- detecting duplicated work, stalled agents, stale HEAD, scope drift or single-writer conflicts;
- coordinating worker/reviewer handoffs;
- requesting correction before bad work propagates;
- keeping Mission Control/JUPITER state aligned with material progress.

Hermes must not use supervision time to invent unrelated work, become a second writer, or cross protected boundaries.
