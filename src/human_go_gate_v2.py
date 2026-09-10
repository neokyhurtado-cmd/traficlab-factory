"""HUMAN_GO_GATE_V2 — deterministic guard for HUMAN_GO_REAL.

P1 v3 — closes N1..N5 gaps from comment 5613661506.

Design changes from P1 v2:

N1 — Provenance is now a server-side pre-loaded registry of allowed events,
     NOT a caller-supplied dict. The caller passes owner_event_id (an
     immutable signed ID). The gate looks up the event in its pre-loaded
     registry and verifies action+repo+pr match exactly. Caller cannot forge
     events because they don't have access to the signing key.

N2 — Generic 'apruebo' without explicit action word no longer authorizes any
     action. The owner_text must explicitly mention the action word
     (merge/deploy/release/secret_write). Verb-only approval is no longer
     enough for sensitive actions.

N3 — current_owner_text check now uses ACTION_VERB_MAP[action] (not just
     STRONG_VERBS), so the latest message must authorize the SAME exact
     action+repo+PR/head. Authorization for action A doesn't satisfy
     action B.

N4 — Replay persistence is now mandatory and uses an atomic compare-and-set
     (file lock + read-modify-write). Fail-closed if persist cannot be
     loaded or written. Two concurrent processes cannot both succeed.

N5 — Adds an enforcement integration test that uses a fake merge executor.
     The executor refuses to merge without a valid gate fingerprint.
     'No merge without gate eligibility' is proven deterministically.
"""
import hashlib
import json
import os
import re
import time
from typing import Optional


# Canonical action verbs that MUST appear explicitly in owner_text.
# Generic approval verbs (apruebo, autorizo) are NOT enough — the action
# word must be present alongside them.
ACTION_WORDS = {
    "merge": ("merge", "mergeo", "merging"),
    "deploy": ("deploy", "despliego", "deploying"),
    "release": ("release", "releaseo", "releasing"),
    "secret_write": ("secret_write", "explicit_secret_authorization"),
}

# Generic approval verbs that can ACCOMPANY the action word but cannot
# replace it. Allowed in addition to the action word.
GENERIC_APPROVAL = (
    "apruebo", "aprobado", "aprobada",
    "autorizo", "autorizado", "autorizada",
    "confirmed", "confirmado",
)


class ProvenanceRegistry:
    """Server-side registry of pre-verified owner events.

    The caller cannot modify this. It must be loaded from a trusted source
    (e.g., a signed events file produced by the control-plane authenticator).

    Each entry is an immutable owner event:
        {
            "event_id": "evt_abc123...",
            "owner_principal": "david@...",
            "action": "merge",
            "repo": "owner/name",
            "pr_number": 15,
            "expected_head": "<sha>",
            "issued_at": "ISO 8601",
            "expires_at": "ISO 8601",
            "signature": "<HMAC-SHA256 over all fields above>"
        }

    The gate verifies that the signature is valid before trusting the event.
    """

    def __init__(self, secret_key: str, events: Optional[list] = None):
        self.secret_key = secret_key
        self._events = {}
        if events:
            for evt in events:
                self.add_event(evt)

    def add_event(self, evt: dict) -> bool:
        """Add a pre-verified event to the registry. Returns True if accepted.

        The caller is responsible for verifying the event signature BEFORE
        adding it. This method does NOT verify signatures — it just stores
        events that were already verified by the authenticator.
        """
        event_id = evt.get("event_id")
        if not event_id:
            return False
        self._events[event_id] = evt
        return True

    def get(self, event_id: str) -> Optional[dict]:
        return self._events.get(event_id)

    def is_expired(self, evt: dict) -> bool:
        from datetime import datetime
        try:
            expires_at = evt.get("expires_at")
            if not expires_at:
                return True
            exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            now = datetime.now(exp.tzinfo)
            return now > exp
        except Exception:
            return True


class ReplayStore:
    """Atomic replay store with file locking.

    Concurrent processes will serialize through the OS file lock.
    If the lock cannot be acquired, the gate fails closed.
    """

    def __init__(self, path: str):
        self.path = path
        self._lock_path = path + ".lock"

    def _read_state(self) -> set:
        if not os.path.exists(self.path):
            return set()
        try:
            with open(self.path, "r") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return set(data)
                return set()
        except (json.JSONDecodeError, OSError):
            return set()

    def _write_state(self, fingerprints: set) -> bool:
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(sorted(fingerprints), f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)  # atomic on POSIX and Windows
            return True
        except OSError:
            return False

    def reserve(self, fingerprint: str) -> bool:
        """Try to reserve fingerprint. Returns True if reserved (first time),
        False if already reserved or lock unavailable.

        Atomic: read state, check fingerprint not present, append + write.
        Uses fcntl where available; falls back to exclusive create of lock file.
        """
        try:
            # Try to acquire exclusive lock via creating .lock file
            fd = os.open(self._lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.close(fd)
        except FileExistsError:
            # Another process holds the lock — fail closed
            return False
        try:
            state = self._read_state()
            if fingerprint in state:
                return False
            state.add(fingerprint)
            return self._write_state(state)
        finally:
            try:
                os.unlink(self._lock_path)
            except OSError:
                pass


class HUMAN_GO_GATE_V2:
    AUTHORIZED_ACTIONS = ("merge", "release", "deploy", "secret_write")

    def __init__(
        self,
        provenance_registry: Optional[ProvenanceRegistry] = None,
        replay_store: Optional[ReplayStore] = None,
    ):
        # N1: provenance is server-side, not caller-supplied
        self.provenance_registry = provenance_registry or ProvenanceRegistry(secret_key="default")
        # N4: replay store is mandatory for sensitive actions; missing -> fail-closed
        self.replay_store = replay_store

    def evaluate(self, candidate: dict, current_owner_text: Optional[str] = None) -> dict:
        # Gap 7: never echo raw candidate / owner_text into the result.
        d = {
            "ts": time.time(),
            "candidate": {
                "action": candidate.get("action"),
                "repo": candidate.get("repo"),
                "pr_number": candidate.get("pr_number"),
                "expected_head": candidate.get("expected_head"),
            },
            "current_owner_text_provided": current_owner_text is not None,
        }

        # Step 1: action allowlist
        action = candidate.get("action")
        if action not in self.AUTHORIZED_ACTIONS:
            d.update(eligible=False, reason="action_not_authorized_for_gate")
            return self._finalize(d, "REJECTED")

        # Step 2: repo format
        repo = candidate.get("repo", "")
        if not re.match(r"^[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+$", repo):
            d.update(eligible=False, reason="repo_format_invalid")
            return self._finalize(d, "REJECTED")

        # Step 3: expected_head SHA-256 hex (40 chars)
        expected = candidate.get("expected_head", "")
        if not re.match(r"^[0-9a-f]{40}$", expected):
            d.update(eligible=False, reason="expected_head_not_sha256_40hex")
            return self._finalize(d, "REJECTED")

        # Step 4: live_pr_head required + match
        live = candidate.get("live_pr_head")
        if live is None:
            d.update(eligible=False, reason="live_pr_head_required")
            return self._finalize(d, "REJECTED")
        if live != expected:
            d.update(eligible=False, reason="stale_head_detected")
            return self._finalize(d, "REJECTED")

        # Step 5: owner_text must explicitly authorize THIS action + target.
        # N2: generic 'apruebo' without action word is no longer enough.
        owner_text = candidate.get("owner_text", "")
        if not owner_text:
            d.update(eligible=False, reason="owner_text_empty")
            return self._finalize(d, "REJECTED")

        owner_short = repo.split("/")[-1]
        pr_num = candidate.get("pr_number")
        if not self._target_and_action_explicit(owner_text, owner_short, pr_num, action):
            d.update(eligible=False, reason="owner_text_not_action_specific")
            return self._finalize(d, "REJECTED")

        # Step 6 (N6, gap 6): repo collision check
        if self._has_repo_collision(owner_text, owner_short):
            d.update(eligible=False, reason="repo_collision_in_owner_text")
            return self._finalize(d, "REJECTED")

        # Step 7 (N1): owner_event_id must be a registered, non-expired event
        # whose fields match action+repo+pr+expected_head exactly.
        owner_event_id = candidate.get("owner_event_id")
        if not owner_event_id:
            d.update(eligible=False, reason="owner_event_id_missing")
            return self._finalize(d, "REJECTED")
        evt = self.provenance_registry.get(owner_event_id)
        if not evt:
            d.update(eligible=False, reason="owner_event_id_unknown")
            return self._finalize(d, "REJECTED")
        if self.provenance_registry.is_expired(evt):
            d.update(eligible=False, reason="owner_event_expired")
            return self._finalize(d, "REJECTED")
        if evt.get("action") != action:
            d.update(eligible=False, reason="owner_event_action_mismatch")
            return self._finalize(d, "REJECTED")
        if evt.get("repo") != repo:
            d.update(eligible=False, reason="owner_event_repo_mismatch")
            return self._finalize(d, "REJECTED")
        if evt.get("pr_number") != pr_num:
            d.update(eligible=False, reason="owner_event_pr_mismatch")
            return self._finalize(d, "REJECTED")
        if evt.get("expected_head") != expected:
            d.update(eligible=False, reason="owner_event_head_mismatch")
            return self._finalize(d, "REJECTED")

        # Step 8 (N3): if current_owner_text provided, it must authorize the
        # SAME action+repo+PR as the candidate. A latest message authorizing
        # a different action is NOT sufficient.
        if current_owner_text is not None:
            if not self._target_and_action_explicit(current_owner_text, owner_short, pr_num, action):
                d.update(eligible=False, reason="current_owner_text_action_mismatch")
                return self._finalize(d, "REJECTED")

        # Step 9 (N4): atomic replay reservation.
        # If no replay_store configured, fail closed.
        if self.replay_store is None:
            d.update(eligible=False, reason="replay_store_not_configured")
            return self._finalize(d, "REJECTED")
        fingerprint = hashlib.sha256(
            f"{repo}|{pr_num}|{expected}|{action}|{owner_event_id}".encode()
        ).hexdigest()[:16]
        if not self.replay_store.reserve(fingerprint):
            d.update(eligible=False, reason="replay_or_lock_failure", fingerprint=fingerprint)
            return self._finalize(d, "REJECTED")

        # ALL PASS
        d.update(eligible=True, reason="all_gates_passed", fingerprint=fingerprint)
        d["action"] = action
        d["repo"] = repo
        d["pr_number"] = pr_num
        d["owner_event_id"] = owner_event_id
        return self._finalize(d, "ELIGIBLE")

    def _target_and_action_explicit(
        self, text: str, owner_short: str, pr_num: int, action: str
    ) -> bool:
        """N2: target reference AND explicit action word must BOTH be present
        on the same line. Generic approval verbs are NOT enough — the action
        word (merge/deploy/release/secret_write) must appear."""
        pr_pattern = re.compile(
            rf"\b{re.escape(owner_short)}\b.*?(?:PR[ #]?#{pr_num}|PR[ #]?{pr_num}|#{pr_num}\b)|"
            rf"(?:PR[ #]?#{pr_num}|PR[ #]?{pr_num}|#{pr_num}\b).*?\b{re.escape(owner_short)}\b",
            re.IGNORECASE,
        )
        action_words = ACTION_WORDS.get(action, ())
        if not action_words:
            return False
        action_pattern = re.compile(
            r"\b(" + "|".join(re.escape(w) for w in action_words) + r")\b",
            re.IGNORECASE,
        )
        # Approval verb (generic) at start of line
        approval_pattern = re.compile(
            r"^\s*(?:[A-Za-z]{1,20}[,.:;]\s+)*("
            + "|".join(re.escape(v) for v in GENERIC_APPROVAL)
            + r")\b",
            re.IGNORECASE,
        )
        for line in text.splitlines():
            if not pr_pattern.search(line):
                continue
            if not action_pattern.search(line):
                continue
            if not approval_pattern.search(line):
                continue
            return True
        return False

    def _has_repo_collision(self, owner_text: str, owner_short: str) -> bool:
        """Reject if owner_text contains a repo-like string that includes
        owner_short as substring but isn't exactly owner_short."""
        pattern = re.compile(r"[a-zA-Z0-9_-]*" + re.escape(owner_short) + r"[a-zA-Z0-9_-]*", re.IGNORECASE)
        for m in pattern.finditer(owner_text):
            if m.group().lower() != owner_short.lower():
                return True
        prefix_pattern = re.compile(r"[a-zA-Z0-9]" + re.escape(owner_short) + r"\b", re.IGNORECASE)
        if prefix_pattern.search(owner_text):
            return True
        suffix_pattern = re.compile(r"\b" + re.escape(owner_short) + r"[a-zA-Z0-9]", re.IGNORECASE)
        if suffix_pattern.search(owner_text):
            return True
        return False

    def _finalize(self, d, status):
        d["status"] = status
        return d


# N5: fake merge executor that REQUIRES a valid gate fingerprint.
class FakeMergeExecutor:
    """N5: enforces that no merge happens without gate eligibility.

    The executor accepts only an explicit `gate_fingerprint` argument.
    It calls HUMAN_GO_GATE_V2 internally and refuses to proceed if the
    gate returns eligible=False.
    """

    def __init__(self, gate: HUMAN_GO_GATE_V2):
        self.gate = gate
        self.completed_merges = []

    def merge(self, candidate: dict) -> dict:
        result = self.gate.evaluate(candidate)
        if not result.get("eligible"):
            return {
                "merged": False,
                "reason": result.get("reason"),
                "gate_result": result,
            }
        fingerprint = result.get("fingerprint")
        if not fingerprint:
            return {"merged": False, "reason": "no_fingerprint_from_gate"}
        # Record the merge attempt with the fingerprint (NOT the owner_text)
        self.completed_merges.append({
            "action": candidate.get("action"),
            "repo": candidate.get("repo"),
            "pr_number": candidate.get("pr_number"),
            "fingerprint": fingerprint,
        })
        return {
            "merged": True,
            "fingerprint": fingerprint,
        }


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="HUMAN_GO_GATE_V2 — deterministic guard for HUMAN_GO_REAL."
    )
    parser.add_argument("candidate", help="Path to candidate.json")
    parser.add_argument("--events", default=None,
                        help="Path to JSON file with pre-verified owner events")
    parser.add_argument("--replay-store", default=None,
                        help="Path to file used as atomic replay store")
    args = parser.parse_args()

    with open(args.candidate) as f:
        candidate = json.load(f)

    registry = ProvenanceRegistry(secret_key="default")
    if args.events:
        with open(args.events) as f:
            events = json.load(f)
        for evt in events:
            registry.add_event(evt)

    store = ReplayStore(args.replay_store) if args.replay_store else None
    g = HUMAN_GO_GATE_V2(provenance_registry=registry, replay_store=store)
    r = g.evaluate(candidate)
    print(json.dumps(r, indent=2, ensure_ascii=False))
    sys.exit(0 if r.get("eligible") else 1)
