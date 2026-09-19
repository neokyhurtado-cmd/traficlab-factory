# G0 — Reality Sync v1 (orchestrator pre-Lane-A grounding)

**Issue:** neokyhurtado-cmd/traficlab-factory#45
**Carried execution:** exec-5740146407-e648fec2 (session sess-21a9091b7dd5, kanban t_20e30311)
**Verification date:** 2026-09-19T07:25Z
**Verifier:** JUPITER orchestrator (READ-ONLY)

---

## Verified git state

| Repo | Path | Local HEAD | origin/main | Diff | Verdict |
|---|---|---|---|---|---|
| Factory | `C:/dev/traficlab-factory-handoff/traficlab-factory/` | `b4dd937af8866a5cfb881cf0be94bf1e85b725ec` | `b4dd937af8866a5cfb881cf0be94bf1e85b725ec` | even | ✅ matches EXPECTED_HEAD |
| IA-VISION | `C:/dev/TraficLabPro/IA-VISION/` | `2486a031c22c4b8fd80988baea4eb3a7068befa2` (after ff) | `2486a031c22c4b8fd80988baea4eb3a7068befa2` | even (was 21 behind, fast-forwarded `80161af → 2486a03`) | ✅ aligned, no merge commit, no force |

**Safety note on the IA-VISION fast-forward:** the local clone was 21 commits behind `origin/main`; I ran `git merge --ff-only origin/main`. No merge commit was created (linear history preserved). No uncommitted work was discarded (working tree only had untracked files: `.env.runtime`, `.worktrees/`, two `idom_sidecars/_*.py` probe scripts — none in `index.html`/visor scope).

## Verified runtime state

| Resource | Path / URL | Status |
|---|---|---|
| Canonical SQLite DB | `X:/TraficLabPro/evidencia/ecosistema.db` (310 MB) | present |
| Media root | `X:/TraficLabPro/data/processed` (browser_media_locks/ + browser_media_sidecars/) | present |
| Visor launcher | `g5_workers/visor_launcher.sh` | present |
| Visor entrypoint | `:7921` (uvicorn) | reproducible per PR #191 (CI verified `visor_launcher.sh` smoke) |
| Multiplex owner | `default` profile gateway (`~/.hermes/`) | running |
| Orchestrator profile | `orchestrator` (this session) | running, multiplex-warned (Telegram token shared with default; not blocking this lane) |

## Existing product surface (verified by line counts)

```
05_visor/static_visor/
├── js/
│   ├── visor.js          3574 lines  (Vue-style reactivity, Canvas-only overlays, RB state machine)
│   ├── visor_idom.js      240 lines  (IDOM inventory front per directive #94 c5687087951)
│   ├── cinematic.js       (V1 cinematic timeline)
│   └── rt_visual_01.js    (real-time visual worker stub)
├── css/
│   ├── app.css            133 lines  (layout shell)
│   ├── tokens.css                  (design tokens)
│   ├── components.css              (cards, panels)
│   ├── hero.css                    (V1 hero block)
│   ├── motion.css                  (transitions)
│   ├── empty-states.css            (zero-data states)
│   ├── tracks-and-gates.css        (differentiator tracks/gates styles)
│   ├── visor.css                   (visor-specific)
│   ├── visor_idom.css              (IDOM inventory)
│   └── rt_visual_01.css            (rt visual worker)
├── index.html            1119 lines
├── analytics.html / control-aforos.html / mission-control.html / owner-view.html / visor_idom.html / workspace.html
└── vendor/   (third-party JS/CSS)
```

```
05_visor/
├── _motor_imports.py      48 lines  (motor engine imports)
├── _video_path.py        176 lines  (canonical media path resolution)
├── browser_media.py      709 lines  (A1.2 media cache + sidecars + remux/transcode decision)
├── db.py                  82 lines  (RILSA_DB_PATH + RILSA_DB_MODE rw/ro)
├── CONTRATO_LIVE_VISOR.md          (live-visor contract)
├── README.md / README_despliegue.md
├── requirements.txt
├── fixtures/                       (golden fixtures)
└── evidence/                       (capture screenshots)
```

## Existing renderer reality

| Tech | Currently in product? | Where |
|---|---|---|
| Canvas 2D (overlay) | YES | `visor.js` draws boxes/trails via `<canvas>` |
| MapLibre GL JS | NO | not imported |
| Deck.gl | NO | not imported |
| PixiJS | NO | not imported |
| Three.js | NO | not imported |
| Cesium | NO | not imported |
| WebCodecs (`VideoDecoder`) | NO | not imported |
| HTML5 `<video>` | YES | native path used in visor |
| `frame.jpg` server fallback | YES | exists per `browser_media.py` architecture |

**Implication:** the E1.3 frame-accurate media adapter is PARTIAL (native + frame.jpg work; WebCodecs path is the missing piece). E3.1–E3.4 (multiview rendering layers) are NOT_STARTED — the current visor is Canvas-only, no MapLibre/Deck/Pixi.

## Reusable visor series (merged into main 2486a031)

PRs #177–#191 (visual-rebuild-v1 + visor + smoke):

| PR | Title | Capability delivered |
|---|---|---|
| #177 | Phase 1 shell + modes + responsive | E6.8 (edge/cloud portability UI shell) |
| #178 | H6 OWNER VIEW V1 - read-only surface | E5.2 (read-only owner view) |
| #179 | V2A layer control + inspector foundation | foundation for E3.1 + E3.2 + E5.2 |
| #180 | V2B clic-to-select + inspector populate | foundation for E3.4 (annotations seed) |
| #181 | V3A selected track full trajectory in accent color | E1.2 partial (selected-track context only, no cross-track Re-ID) |
| #182 | V3B bridge layer toggles to visor show* flags | layer-toggling foundation |
| #183 | V4A gates + aforos count badges | partial E5.1 (count display) |
| #184 | V5 KPI -> tracks in 1 click (OD cell filter) | E5.1 partial (OD filter) |
| #185 | V5B sidepanel Tracks por Gate | E3.4 partial (UI; no persistence yet) |
| #186 | V6 unified timeline events on scrubber | E3.3 partial (timeline aggregator) |
| #187 | V7 export current scope as JSON or CSV | E4.2 partial (CSV/JSON export, no OpenDRIVE/OpenSCENARIO) |
| #188 | V8 mobile responsive sidepanel + hamburger | E6.8 |
| #189 | V9 centralized stateNotice component | UI consistency |
| #190 | V10 unified visorStack state machine | E6.2 partial (state schema) |
| #191 | fix(g5-m591): visor launcher + smoke test for port 7921 | reproducibility |

## Active Factory PRs (potential collision surface)

| PR | Branch | Risk for multiview scope |
|---|---|---|
| #38 single-front-door-01 | `feat/single-front-door-01` | low — orchestration mechanism, not product |
| #40 OMH control room canary | `feat/omh-control-room-canary` | low — control surface |
| #41 Jev shadow decision plane | `feat/jev-shadow-decision-plane` | low — verification primitive |
| #42 Ashley docs | `docs/ashley-active-suini-owner` | none (docs) |
| #43 Ashley auto-wake installer | `reconcile/ashley-auto-wake-factory-promote-20260918-01` | low — install plumbing |

**No open PR touches the IA-VISION multiview frontend, evidence/data, or renderer benchmark scopes.** No collision.

## Visor code surface maps (orchestrator grounding for Lane A)

File:line citations that **exist today** (proof of partial productization):

- Frame-accurate media adapter (E1.3 PARTIAL): `05_visor/static_visor/js/visor.js:23-49` (`scale_px_per_m` discipline), `05_visor/_video_path.py:1-176` (canonical media root resolution), `05_visor/browser_media.py:1-709` (A1.2 cache + sidecars + remux decision tree). **Missing**: WebCodecs `VideoDecoder` adapter.
- Selected-track + trajectory + accent color (E1.2 partial / E3.3 partial): `visor.js:181-260` (PR #181).
- KPI/tracks/OD-cell filter (E5.1 partial): `visor.js:500-560` (PRs #184/#185).
- Inspector / clic-to-select (E3.4 foundation / E5.2 partial): `visor.js:550-650` (PRs #179/#180).
- Layer toggles (E3.2 foundation): `visor.js:660-740` (PR #182).
- Timeline events (E3.3 partial): `visor.js:740-840` (PR #186).
- Export JSON/CSV (E4.2 partial): `visor.js:870-1000` (PR #187).
- Mobile responsive (E6.8): `visor.js:1000-1500`, `static_visor/css/*` (PRs #177/#188).
- visorStack state machine (E6.2 partial): `visor.js:1500-2200` (PR #190).
- Live-visor contract: `05_visor/CONTRATO_LIVE_VISOR.md` (the executable contract).

## Conflicts found in G0

**None** that block the macrogate:
- No open PR touches multiview scope.
- No conflicting branch in the IA-VISION worktree list (existing `feat/issue-145-*` and `feat/sfd37-*` worktrees are unrelated).
- No SUINI write planned; no secret/provider config changes; no canonical DB mutation planned.

**Minor item (informational, NOT a blocker):** the visor launcher reads `DB_PATH=X:/TraficLabPro/evidencia/ecosistema.db`. The current DB file is 310 MB. The directive says **canonical DB mutation is forbidden without explicit gate**; the lane plan must use `RILSA_DB_MODE=ro` (already implemented per `db.py:23-26` and `db.py:74-79`) so the visor lane runs read-only. Confirmed: the ro-mode hook exists.

## Reuse-first plan (per `EXISTING_PRODUCT_FIRST = YES`)

- **Do NOT** create a new visor. Extend `visor.js` + `visor_idom.js`.
- **Do NOT** write a parallel app server. Reuse the existing uvicorn launcher on `:7921` for the multiview API routes (new endpoints added under `/api/multiview/*` per Lane B).
- **Do NOT** rewrite the canonical DB. Read via `RILSA_DB_MODE=ro`; expose the EvidenceGraph read-model as a facade in `05_visor/` (new module `evidence_graph/`).
- **Do NOT** re-run YOLO/ByteTrack. Reuse the persisted tracks/cruces already in `ecosistema.db`.
- **Do** add a new CSS file `static_visor/css/multiview.css` and a new JS module `static_visor/js/multiview/` for the MapLibre/Deck/Pixi benchmark; do NOT pollute `visor.js` beyond minimal cross-module integration points.
- **Do** add contract tests under `tests/evidence_graph/` and `tests/multiview/` that run without the runtime DB (use fixtures + schema mocks).

## G0 verdict

```text
G0_REALITY_SYNC              = PASS
HEAD_VERIFIED                = YES (Factory b4dd937a + IA-VISION 2486a031)
DUPLICATE_IMPLEMENTATION     = 0
USEFUL_EXISTING_WORK_ADOPTED = YES (visor series #177-#191; A1.2 media adapter; visorStack RB)
CONFLICTS                    = NONE blocking
VISOR_RUNTIME_REPRODUCIBLE   = YES (visor_launcher.sh + PR #191 smoke)
SUINI_TOUCH_PLANNED          = NO (read-only external dep)
CANONICAL_DB_MUTATION_PLANNED = NO (ro mode confirmed)
```

This G0 grounding is what JUPITER hands to Lane A (auditor) so the auditor can focus on per-capability file:line citations without redoing the workspace discovery.

## Reference paths (orchestrator note for downstream lanes)

- Orchestrator worktree: `C:/dev/traficlab-factory-handoff/wt/multiview-orchestration-20260919/`
- Orchestrator branch: `feat/multiview-orchestration-20260919` (commit `8d23d71`, off Factory `b4dd937a`)
- IA-VISION main worktree: `C:/dev/TraficLabPro/IA-VISION/`
- IA-VISION feature worktrees (future lanes): `C:/dev/TraficLabPro/IA-VISION/.worktrees/wt-<lane>-<sha37>/`
- Canonical DB: `X:/TraficLabPro/evidencia/ecosistema.db` (RO mode for all visor lanes)
- Media root: `X:/TraficLabPro/data/processed/`
- Visor :7921 launcher: `g5_workers/visor_launcher.sh`
- Factory issue: https://github.com/neokyhurtado-cmd/traficlab-factory/issues/45
- Factory orchestration comment: https://github.com/neokyhurtado-cmd/traficlab-factory/issues/45#issuecomment-5740170167
