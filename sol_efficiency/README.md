# SoL Efficiency Layer

Native TrafficLab implementation inspired by the efficiency ideas in NVlabs/SoL-Pi.
It does not install Pi or SoL-Pi and does not add a second scheduler.

## Components

- ObservationPack: content-addressed archival of verbose text, exact recall,
  SHA-256 integrity checks, bounded previews.
- EvidenceReducer: archives first, then surfaces only exact verified lines.
- ActionFusion: one action callable followed immediately by one verifier
  callable; no shell executor is introduced.
- ContextCompactor: creates a bounded semantic checkpoint at loop boundaries.

## LoopEngine modes

TRAFICLAB_SOL_MODE controls integration:

- off (default): legacy behavior.
- shadow: archive/reduce oversized evidence and write context checkpoints,
  but do not replace worker evidence.
- enforce: oversized worker evidence is replaced by a compact verified digest
  whose obs://sha256/... handle can recall the original exactly.

Optional:
- TRAFICLAB_SOL_ROOT defaults to .sol_artifacts
- threshold can be passed as sol_threshold_bytes to LoopEngine.

Runtime artifacts are local and ignored by Git.

## Safety properties

1. PASS validation runs before evidence compaction.
2. Original evidence is archived before any compact representation is emitted.
3. Every surfaced reducer line is recalled from the archive and marked verified/unverified.
4. Archive recall recomputes SHA-256 and fails on tampering.
5. ActionFusion does not execute shell commands itself.
6. Default mode is off; rollout can be measured in shadow first.
