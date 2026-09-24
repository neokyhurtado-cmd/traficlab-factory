"""Native SoL-style efficiency primitives for TrafficLab Factory.

The package is intentionally runtime-agnostic: it does not install or depend on
Pi/SoL-Pi and it does not create a scheduler. It composes with the existing
LoopEngine.
"""
from .observation_pack import ObservationPack, ObservationRef, ObservationIntegrityError
from .evidence_reducer import EvidenceReducer, EvidenceDigest, EvidenceFinding
from .action_fusion import ActionFusion, FusedActionResult, Verification
from .context_compact import ContextCompactor, ContextCheckpoint

__all__ = [
    "ObservationPack",
    "ObservationRef",
    "ObservationIntegrityError",
    "EvidenceReducer",
    "EvidenceDigest",
    "EvidenceFinding",
    "ActionFusion",
    "FusedActionResult",
    "Verification",
    "ContextCompactor",
    "ContextCheckpoint",
]
