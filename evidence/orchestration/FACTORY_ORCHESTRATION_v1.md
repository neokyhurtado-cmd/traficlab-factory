# FACTORY_ORCHESTRATION:v1 — TRAFFICLAB-MULTIVIEW-CORE-V1 + ELITE-20+

**Issue:** neokyhurtado-cmd/traficlab-factory#45
**Execution ID:** exec-5740146407-e648fec2 (CARRIED — no duplicate goal)
**Session:** sess-21a9091b7dd5 (CARRIED)
**Kanban task:** t_20e30311 (RESUMED, RUNNING, dispatcher lock WIN-01-AXIA-PANORAMA:28128)
**Owner HEADS at dispatch:**
- Factory `main = b4dd937af8866a5cfb881cf0be94bf1e85b725ec` ✅ (matches EXPECTED_HEAD)
- IA-VISION `main = 2486a031c22c4b8fd80988baea4eb3a7068befa2` ✅ (matches directive reference)

**Orchestrator worktree:** `C:/dev/traficlab-factory-handoff/wt/multiview-orchestration-20260919`
**Branch:** `feat/multiview-orchestration-20260919` (off Factory main b4dd937a)

**DIRECTIVE IDs covered:**
- TRAFFICLAB-MULTIVIEW-CORE-V1-20260919-01 (initial BUILD, source_comment 5740146407)
- TRAFFICLAB-ELITE-20-PLUS-20260919-01 (scope expansion, source_comment 5740160278)

**Hard-stops honored:**
- No IA-VISION main merge, release, deploy
- No destructive canonical DB/media mutation
- No SUINI writes (read-only external dependency)
- No secrets/tokens/global-config/provider/license/payment changes
- No fake track-merging Re-ID; no fake Vissim-native; no fake accuracy claims
- Each capability ends in `PRODUCTIZED | SHADOW_VALIDATED | CONTRACT_READY | REJECTED_WITH_EVIDENCE | BLOCKED_EXTERNAL_REAL`. `NOT_STARTED=0` at owner review.

---

## RUNNING_CONFIRMED proof

```text
worker_pid        = 38016
dispatcher_lock   = WIN-01-AXIA-PANORAMA:28128
task_id           = t_20e30311
run_id            = 250
started_at        = 2026-09-19T07:15:58Z (claim)
heartbeat         = 2026-09-19T07:16:10Z (fresh, <60s)
expected_head     = b4dd937af8866a5cfb881cf0be94bf1e85b725ec
head_verified     = true (git rev-parse HEAD == expected_head)
goal_binding      = traficlab-factory#45 + directive TRAFFICLAB-MULTIVIEW-CORE-V1-20260919-01 + TRAFFICLAB-ELITE-20-PLUS-20260919-01
```

## State of prior reusable work (zero-loss adoption)

- IA-VISION visor series #180–#191 MERGED into `main = 2486a031` (10 PRs in 1h21m)
- visor `:7921` smoke reproducible (PR #191)
- No open PRs collide with multiview scope (verified `gh pr list --state open`)
- Factory PRs open at dispatch: #38 single-front-door, #40 OMH control room, #41 Jev shadow, #42 Ashley docs, #43 Ashley auto-wake installer — none touch the multiview scope

## Master dependency graph (per directive recommended layout)

```
G0 reality sync (auditor lane, READ-ONLY)
   |
   +--> EvidenceGraph / read-model facade --> H3/spatial --> annotations --> NLQ --> exports (OpenDRIVE/OpenSCENARIO/FMI)
   |
   +--> MasterTimeController + media adapter --> WebCodecs path --> Workers/LOD
   |
   +--> Calibration / homography --> drift health --> eagle/3D
   |
   +--> Track / trajectory --> Re-ID SHADOW (reversible) --> SSM
   |
   +--> Renderer benchmark --> instancing/LOD/3D --> visual pass

Cross-cutting (every node carries them):
  - lineage + dataset versions
  - schema/contract registry + compatibility tests
  - observability + SLO baselines (after measurement)
  - uncertainty + provenance as first-class fields
  - privacy derived-media (non-destructive)
  - offline bundle / PWA
  - access control + immutable audit
  - disaster recovery + integrity
  - cost / resource budgets
  - edge/cloud portability contract
  - plugin boundaries (typed extension interfaces)
  - golden engineering scenarios (immutable regression suite)
```

---

## Lane manifest (8 lanes, parallel-safe, one writer per mutable scope)

Each lane runs on its **own isolated worktree + branch off Factory `main`**, mutates a **disjoint file set**, and returns a structured payload with commit SHA + tests + evidence. Lanes that need an IA-VISION branch will create one off IA-VISION `main = 2486a031`. The IA-VISION PR(s) are produced **after** all lanes pass.

| Lane | Role | Profile (assignee) | Mutable scope | Repo | Branch off | Dependencies | Status |
|---|---|---|---|---|---|---|---|
| **A** | Reality auditor + capability matrix | `auditor` (read-only investigator) | READ-ONLY across Factory + IA-VISION | both | n/a | none | READY |
| **B** | EvidenceGraph + lineage + read-model facade + schema registry | `ia-vision-backend` | `ia_vision/evidence/`, new `evidence_graph/`, `tests/` | IA-VISION | `feat/multiview-evidencegraph-v1` | A (verified) | BLOCKED on A |
| **C** | Multiview frontend (MapLibre eagle + Deck.gl trajectory/events + Canvas/Pixi benchmark harness) | `ia-vision-frontend` | `static_visor/js/multiview/`, `static_visor/css/`, `static_visor/index.html` | IA-VISION | `feat/multiview-frontend-v1` | A + B contract | BLOCKED on B contract |
| **D** | Performance + benchmark harness (FPS, draw calls, p50/p95, memory) | `ia-vision-perf` | `tests/perf/`, `scripts/bench_*` | IA-VISION | `feat/multiview-perf-v1` | C runnable surface | BLOCKED on C runnable |
| **E** | Visual worker (Orca + MiniMax Code refinement + drift dashboard UI) | `visual` | CSS pass + drift dashboard UI | IA-VISION | `feat/multiview-visual-v1` | C surface | BLOCKED on C |
| **F** | Interop worker (CSV/JSON/GeoJSON + OpenDRIVE/OpenSCENARIO exporters + round-trip validator + FMI spike) | `ia-vision-interop` | `ia_vision/exporters/`, `tests/exporters/` | IA-VISION | `feat/multiview-interop-v1` | B contract | BLOCKED on B |
| **G** | Independent verifier (Jupiter/Astra adversarial review; no self-cert) | `astra-verifier` | READ-ONLY gate | n/a | n/a | each material gate | READY |
| **H** | Integrator + final 30-row matrix + fan-in PR packaging | `orchestrator` (JUPITER) | merge + PR open (NO IA-VISION main merge) | both | merge commits | all lanes pass | BLOCKED on lanes |

**Concurrent dispatch budget:** MAX_CONCURRENT_CHILDREN = 10. Lane A is the only lane that is READY at t=0. Lanes B/C/F can be planned now but dispatch waits on A's capability-matrix deliverable. Lane D/E dispatch when C has a runnable surface. Lane G reviews each material gate. Lane H is the orchestrator itself.

---

## Beyond-20 cross-cutting capabilities (must be visible at every node)

E6.1 Uncertainty/provenance fields | E6.2 Schema/contract registry + compatibility tests | E6.3 Observability + SLOs | E6.4 Reproducible evidence bundles | E6.5 RBAC + immutable audit trail | E6.6 DR/integrity | E6.7 Cost/resource budgets | E6.8 Edge/cloud portability contract | E6.9 Plugin boundaries | E6.10 Golden engineering scenarios.

---

## Capability matrix (30-row) — initial state

| ID | Capability | STATE (initial) | NEXT_STEP |
|---|---|---|---|
| E1.1 | Homografía automática + salud geométrica | NOT_STARTED | Lane B implements over existing calibration |
| E1.2 | Re-ID transcámara (probabilistic / reversible) | NOT_STARTED | Lane B — SHADOW only, no track renumber |
| E1.3 | Frame-accurate media adapter (native + frame.jpg + WebCodecs) | PARTIAL (existing :7921 native path) | Lane C — capability detection + WebCodecs where safe |
| E1.4 | Async event/ingest contract (typed, idempotent) | NOT_STARTED | Lane B — local durable first; broker only with benchmark |
| E2.1 | Hot temporal store vs semantic graph benchmark | NOT_STARTED | Lane B — SQLite baseline + benchmark candidate |
| E2.2 | H3 / spatial index | NOT_STARTED | Lane B — only for georeferenced; local XY stays local |
| E2.3 | Immutable lineage + dataset versions | PARTIAL (some processing history) | Lane B — provenance bundle on every artifact |
| E2.4 | Privacy-derived media | NOT_STARTED | Lane B — derived asset, no destructive |
| E3.1 | Workerized multiview data plane | NOT_STARTED | Lane C — Web Worker + Transferable + gen-id |
| E3.2 | Instancing (Deck + Three) | NOT_STARTED | Lane C — Deck default; Three only for 3D path |
| E3.3 | Dynamic spatiotemporal LOD | NOT_STARTED | Lane C — zoom/extent/time/count-driven |
| E3.4 | Collaborative anchored annotations | NOT_STARTED | Lane B — schema + UI in Lane C |
| E4.1 | 3D Tiles pipeline contract | BLOCKED_EXTERNAL_REAL (no LiDAR/photogrammetry) | Lane F — parser/contract/test only |
| E4.2 | OpenDRIVE + OpenSCENARIO export | NOT_STARTED | Lane F — versioned exporter + validator |
| E4.3 | FMI/FMU co-sim spike | NOT_STARTED | Lane F — bounded feasibility only |
| E4.4 | Semantic road rules | NOT_STARTED | Lane F — versioned model + rules engine |
| E5.1 | Surrogate Safety Measures (TTC/PET/DRAC) | NOT_STARTED | Lane B — scientific module + synthetic tests |
| E5.2 | Evidence-grounded NLQ / Copilot | NOT_STARTED | Lane B — query planner; read-only; cite evidence |
| E5.3 | Offline field bundle / PWA | NOT_STARTED | Lane C — export + service worker + conflict policy |
| E5.4 | Sensor + model drift dashboard | NOT_STARTED | Lane C UI + Lane B signals; label-distribution vs accuracy-loss |
| E6.1 | Uncertainty as first-class field | NOT_STARTED | Lane B — every derived fact |
| E6.2 | Contract/schema registry + compatibility tests | NOT_STARTED | Lane B — CI compatibility gate |
| E6.3 | Observability + SLOs | NOT_STARTED | Lane B + Lane C — baseline first, no invented thresholds |
| E6.4 | Reproducible evidence bundles | NOT_STARTED | Lane B — one command to package |
| E6.5 | RBAC + immutable audit | NOT_STARTED | Lane B — roles + audit event hook |
| E6.6 | DR / integrity | NOT_STARTED | Lane B — checksum + restore rehearsal |
| E6.7 | Cost / resource budgets | NOT_STARTED | Lane D — benchmark FPS, CPU/GPU, storage |
| E6.8 | Edge/cloud portability | NOT_STARTED | Lane B — capture/edge vs center vs browser separation |
| E6.9 | Plugin boundaries | NOT_STARTED | Lane B — typed extension interfaces |
| E6.10 | Golden engineering scenarios | NOT_STARTED | Lane B + Lane D — immutable regression suite |

```text
ELITE_20_TOTAL = 20
ELITE_20_PRODUCTIZED = 0
ELITE_20_SHADOW_VALIDATED = 0
ELITE_20_CONTRACT_READY = 0
ELITE_20_REJECTED = 0
ELITE_20_BLOCKED_EXTERNAL = 0
ELITE_20_NOT_STARTED = 19   (E1.3 + E2.3 are PARTIAL)
ELITE_20_NOT_STARTED_target = 0

BEYOND_20_TOTAL = 10
BEYOND_20_NOT_STARTED = 10
BEYOND_20_NOT_STARTED_target = 0
```

**NOTE on PARTIAL**: E1.3 (frame-accurate media) is PARTIAL because the existing visor `:7921` native HTML video path + `frame.jpg` server fallback already work. WebCodecs path is the missing capability. E2.3 (lineage) is PARTIAL because processing history is partially captured today; full provenance bundle is missing.

---

## Dispatch order (dependency-graph; not serial obrero)

```text
T0: A (auditor)  ──> capability matrix + capability matrix published on #45
T1: B (evidence) ──> EvidenceGraph + read-model facade + lineage + schema registry
T1: F (interop)  ──> OpenDRIVE/OpenSCENARIO exporters + round-trip validator (parallel after B contract)
T2: C (frontend) ──> multiview surfaces (MapLibre eagle + Deck trajectory + Canvas/Pixi benchmark)
T3: D (perf)     ──> reproducible benchmark harness on C's runnable
T3: E (visual)   ──> Orca + MiniMax visual refinement
T4: G (verifier) ──> adversarial review of every material gate
T5: H (integrator) ──> reconciliation pass, full regression, <=3 coherent IA-VISION PRs (NOT merged)
```

---

## Verification gate (terminal payload verification per governance)

Every lane terminal payload is re-checked by JUPITER against GitHub API live state before the next dispatch:
- branch exists on `origin`
- commits reachable + parents correct
- CI status matches lane claim (when CI exists)
- structured payload contains commit SHA + tests + evidence

`DISPATCHED != RUNNING_CONFIRMED`. Screenshot is not acceptance.

---

## Auto-next safe gate

JUPITER will:
1. Send HEARTBEAT every few minutes during long operations
2. Dispatch Lane A (auditor) immediately
3. Wait for A's capability matrix → cross-reference against the 30-row matrix above → dispatch B + F in parallel
4. Wait for B contract → dispatch C
5. Wait for C runnable surface → dispatch D + E in parallel
6. Dispatch G verifier at each material gate
7. Run cross-agent reconciliation pass BEFORE final E2E (per governance skill)
8. Fan-in via Lane H, publish final 30-row matrix + reopen ASTRA_QUERY with EXACT_HEAD evidence on each PR
9. NEVER merge IA-VISION main; NEVER release/deploy; NEVER mutate canonical DB/media destructively

If Lane A finds any state conflict (e.g. open PR that does collide, or HEAD mismatch), JUPITER publishes `JUPITER_BLOCKED_NOTE_1:v1` and halts.
If any lane hits a real external blocker (e.g. LiDAR data absent), JUPITER marks it `BLOCKED_EXTERNAL_REAL` and continues every other safe gate.

---

**Status:** ORCHESTRATION PUBLISHED. RUNNING_CONFIRMED.
**Next action:** dispatch Lane A (auditor) — capability matrix + state pointer.
