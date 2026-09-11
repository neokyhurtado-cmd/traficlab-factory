"""B3 enforcement seam — pre-merge check that wraps any merge callable.

This module is the **only** sanctioned seam through which a Hermes 2.0
merge of PR #19 may be invoked. Any other path that tries to call the
merge callable is **bypass** and is detected by `test_b3_bypass_impossible`.

Design contract (from directive #18 comment 5637493526):
  1. The seam MUST be the only path that can call `merge_callable`.
  2. The seam MUST verify gate eligibility BEFORE the callable runs.
  3. The seam MUST refuse to invoke the callable when gate reports
     any rejection reason (signature_invalid, replay_detected,
     stale_head_detected, owner_text_target_mismatch, no_authorization_verb,
     etc.).
  4. The seam MUST NOT itself issue any GitHub call. It only enforces;
     the actual GitHub client is `directive_watcher.gh_client`.
  5. The seam MUST record a `BITES_WITHOUT_GATE` event whenever
     something tries to invoke a Hermes 2.0 irreversible operation
     without going through it. `bite_record` persists into a separate
     file (since `ReplayStore` is reserved for gate-internal replay
     protection).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from typing import Any, Callable, Optional

# Allow running both as a module and as a standalone file
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_HERE, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from human_go_gate_v2 import (  # noqa: E402  (after sys.path bootstrap)
    HUMAN_GO_GATE_V2,
    ProvenanceRegistry,
    ReplayStore,
    pre_merge_check_and_call,
    sign_event,
    MIN_SECRET_KEY_LEN,
)


# Single shared instance guarded by a module-level lock so any caller
# (concurrent ORCH tick, parallel watcher fork, etc.) sees the same
# replay store and registry.
_GATE_LOCK = threading.Lock()
_GATE_INSTANCE: Optional[HUMAN_GO_GATE_V2] = None
_REPLAY_PATH: Optional[str] = None
_BITES_PATH: Optional[str] = None


def _default_replay_path() -> str:
    return os.path.join(
        tempfile.gettempdir(),
        "hermes2_b3_seam_replay.json",
    )


def _default_bites_path() -> str:
    return os.path.join(
        tempfile.gettempdir(),
        "hermes2_b3_seam_bites.json",
    )


def _default_secret_key() -> str:
    """Return a default secret for the seam. In production this MUST be
    supplied by the caller; we only fall back to a deterministic test
    default to keep the seam usable without breaking the contract that
    `ProvenanceRegistry` raises on missing secret (H1).
    """
    key_path = os.environ.get("HERMES2_B3_SECRET_KEY_FILE")
    if key_path and os.path.exists(key_path):
        with open(key_path, "rb") as f:
            key = f.read().decode("utf-8").strip()
        if len(key) >= MIN_SECRET_KEY_LEN:
            return key
    raise RuntimeError(
        "HERMES2_B3_SECRET_KEY_FILE must point to a >=32-char secret. "
        "H1 invariant: no default trust material is allowed in production."
    )


def init_gate(secret_key: Optional[str] = None,
              replay_path: Optional[str] = None,
              bites_path: Optional[str] = None,
              events: Optional[list] = None) -> HUMAN_GO_GATE_V2:
    """Initialize (or return the cached) gate instance for the seam.

    Idempotent: subsequent calls with the same secret/replay return the
    existing instance. The lock prevents two threads from racing the
    initialization.
    """
    global _GATE_INSTANCE, _REPLAY_PATH, _BITES_PATH
    with _GATE_LOCK:
        if _GATE_INSTANCE is not None:
            return _GATE_INSTANCE
        sk = secret_key or _default_secret_key()
        rp = replay_path or _default_replay_path()
        bp = bites_path or _default_bites_path()
        registry = ProvenanceRegistry(secret_key=sk)
        if events:
            for evt in events:
                registry.add_event(evt)
        store = ReplayStore(rp)
        _GATE_INSTANCE = HUMAN_GO_GATE_V2(
            provenance_registry=registry,
            replay_store=store,
        )
        _REPLAY_PATH = rp
        _BITES_PATH = bp
        return _GATE_INSTANCE


def get_replay_path() -> str:
    return _REPLAY_PATH or _default_replay_path()


def get_bites_path() -> str:
    return _BITES_PATH or _default_bites_path()


def run_or_bite(candidate: dict,
                merge_callable: Callable[[], Any],
                *,
                gate: Optional[HUMAN_GO_GATE_V2] = None) -> dict:
    """The B3 seam. Wraps `merge_callable` behind gate v2 eligibility.

    On eligible: returns the gate result merged with the merge_callable
    result.

    On any rejection: returns the gate result and DOES NOT call
    `merge_callable`. The caller must not retry without a fresh
    authorization.

    Note: `pre_merge_check_and_call(gate, candidate, github_merge_callable=...)`
    takes `gate` as positional (not kwarg), per the original signature.
    """
    g = gate or init_gate()
    # pre_merge_check_and_call signature: (gate, candidate, current_owner_text, github_merge_callable)
    raw = pre_merge_check_and_call(g, candidate, github_merge_callable=merge_callable)
    # Normalize the result shape for the seam:
    #   original returns {"merged": True, "fingerprint": ..., "gate_result": ..., "merge_result": ...}
    # We add an `eligible` key for convenience.
    if "eligible" not in raw:
        raw["eligible"] = raw.get("merged", False)
    return raw


def bite_record(reason: str, *,
                attempted_action: Optional[str] = None,
                attempted_repo: Optional[str] = None,
                attempted_pr: Optional[int] = None,
                bites_path: Optional[str] = None) -> dict:
    """Record a `BITES_WITHOUT_GATE` event into the bites file.

    Persists a JSON line-append event with:
      - kind: "BITES_WITHOUT_GATE"
      - reason: short reason text
      - attempted_*: optional attempted target fields
      - captured_at: epoch seconds

    The bites file is separate from the gate's `ReplayStore` because the
    latter is reserved for gate-internal replay protection. The bites
    file is for external monitoring that detects bypass attempts.
    """
    bp = bites_path or get_bites_path()
    evt = {
        "kind": "BITES_WITHOUT_GATE",
        "reason": reason,
        "attempted_action": attempted_action,
        "attempted_repo": attempted_repo,
        "attempted_pr": attempted_pr,
        "captured_at": time.time(),
    }
    # Read-modify-write under thread lock so concurrent bites don't lose each other.
    with _GATE_LOCK:
        existing = []
        if os.path.exists(bp):
            try:
                with open(bp, "r", encoding="utf-8") as f:
                    raw = f.read()
                # Tolerate empty file
                if raw.strip():
                    existing = json.loads(raw)
            except (OSError, json.JSONDecodeError):
                existing = []
        if not isinstance(existing, list):
            existing = []
        existing.append(evt)
        with open(bp, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)
    return evt


def read_bites(bites_path: Optional[str] = None) -> list:
    """Read all bites from the bites file. Tests only."""
    bp = bites_path or get_bites_path()
    if not os.path.exists(bp):
        return []
    try:
        with open(bp, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def reset_for_tests(replay_path: Optional[str] = None,
                    bites_path: Optional[str] = None,
                    secret_key: Optional[str] = None) -> None:
    """Reset module-level gate cache. Tests only."""
    global _GATE_INSTANCE, _REPLAY_PATH, _BITES_PATH
    with _GATE_LOCK:
        _GATE_INSTANCE = None
        _REPLAY_PATH = replay_path
        _BITES_PATH = bites_path
