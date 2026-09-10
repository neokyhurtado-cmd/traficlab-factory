"""HUMAN_GO_GATE_V2 — deterministic guard for HUMAN_GO_REAL.

P1 v4 — closes B1/B2/B3/H1 blockers from comment 5613820447.

B1 — Provenance events are now cryptographically bound.
  - Events carry an HMAC-SHA256 signature computed over a canonical
    representation of (event_id, owner_principal, action, repo, pr_number,
    expected_head, issued_at, expires_at).
  - ProvenanceRegistry requires secret_key at construction (no default).
  - add_event() verifies signature BEFORE storing. Forged/tampered events
    are rejected.
  - CLI accepts --events only if the file is signed with the trusted key.

H1 — Default trust material removed.
  - No `secret_key="default"` anywhere.
  - ProvenanceRegistry raises if secret_key is missing/empty/short.

B2 — Replay store corruption is fail-closed.
  - _read_state() raises on JSONDecodeError/OSError. Caller catches and
    treats as REJECTED with reason='replay_store_corrupt'.

B3 — Real enforcement seam wired.
  - New pre_merge_adapter.py: a function that the ORCH/pre-merge code path
    must call before issuing a merge. It calls HUMAN_GO_GATE_V2.evaluate()
    and refuses to proceed without a valid fingerprint.
  - Integration test: stubs the final GitHub call; proves that without the
    adapter's gate eligibility, the merge call is blocked.
"""
import hashlib
import hmac
import json
import os
import re
import time
from typing import Optional


# Canonical action verbs that MUST appear explicitly in owner_text.
ACTION_WORDS = {
    "merge": ("merge", "mergeo", "merging"),
    "deploy": ("deploy", "despliego", "deploying"),
    "release": ("release", "releaseo", "releasing"),
    "secret_write": ("secret_write", "explicit_secret_authorization"),
}

GENERIC_APPROVAL = (
    "apruebo", "aprobado", "aprobada",
    "autorizo", "autorizado", "autorizada",
    "confirmed", "confirmado",
)

# Minimum secret_key length to prevent short/default keys
MIN_SECRET_KEY_LEN = 32


# =====================================================================
# B1: ProvenanceRegistry with HMAC-SHA256 signature verification
# =====================================================================

class ProvenanceRegistry:
    """Server-side registry of pre-verified owner events.

    Each event must be signed with HMAC-SHA256 using the secret_key.
    The signature is computed over a canonical JSON serialization of:
        event_id, owner_principal, action, repo, pr_number, expected_head,
        issued_at, expires_at

    Events without valid signature are NOT accepted.
    """

    SIGNATURE_FIELD = "signature"

    def __init__(self, secret_key: str):
        if not secret_key:
            raise ValueError("secret_key required (cannot be empty)")
        if not isinstance(secret_key, str):
            raise ValueError("secret_key must be a string")
        if len(secret_key) < MIN_SECRET_KEY_LEN:
            raise ValueError(
                f"secret_key too short ({len(secret_key)} chars); "
                f"minimum {MIN_SECRET_KEY_LEN} chars required"
            )
        self.secret_key = secret_key
        self._events = {}

    @staticmethod
    def canonical_payload(evt: dict) -> bytes:
        """Deterministic JSON serialization for HMAC computation.

        Sort keys, no whitespace, fixed separators. Two equivalent events
        produce identical bytes.
        """
        canonical_fields = (
            "event_id", "owner_principal", "action", "repo",
            "pr_number", "expected_head", "issued_at", "expires_at",
        )
        canonical = {k: evt.get(k) for k in canonical_fields}
        return json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def compute_signature(self, evt: dict) -> str:
        """Compute HMAC-SHA256 signature for an event."""
        return hmac.new(
            self.secret_key.encode("utf-8"),
            self.canonical_payload(evt),
            hashlib.sha256,
        ).hexdigest()

    def verify_signature(self, evt: dict) -> bool:
        """Verify HMAC signature of an event."""
        sig = evt.get(self.SIGNATURE_FIELD)
        if not sig:
            return False
        expected = self.compute_signature(evt)
        # constant-time comparison
        return hmac.compare_digest(sig, expected)

    def add_event(self, evt: dict) -> tuple:
        """Verify signature and store. Returns (accepted: bool, reason: str)."""
        if not isinstance(evt, dict):
            return False, "event_not_dict"
        event_id = evt.get("event_id")
        if not event_id:
            return False, "event_id_missing"
        if self.SIGNATURE_FIELD not in evt:
            return False, "signature_field_missing"
        if not self.verify_signature(evt):
            return False, "signature_invalid"
        if event_id in self._events:
            return False, "event_already_registered"
        self._events[event_id] = evt
        return True, "ok"

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


def sign_event(secret_key: str, evt: dict) -> dict:
    """Helper: produce a signed copy of an event dict.

    Used by the trusted control-plane to create events. NOT available to
    untrusted callers — it requires knowledge of the secret_key.
    """
    signed = dict(evt)
    signed["signature"] = hmac.new(
        secret_key.encode("utf-8"),
        ProvenanceRegistry.canonical_payload(evt),
        hashlib.sha256,
    ).hexdigest()
    return signed


# =====================================================================
# B2: ReplayStore — atomic + fail-closed on corruption
# =====================================================================

class ReplayStore:
    """Atomic replay store with file locking and fail-closed on corruption.

    On JSONDecodeError/OSError when reading existing state, raise.
    The caller (HUMAN_GO_GATE_V2) catches and returns REJECTED.

    Two concurrent processes serialize via .lock file.
    """

    def __init__(self, path: str):
        self.path = path
        self._lock_path = path + ".lock"

    def _read_state(self) -> set:
        if not os.path.exists(self.path):
            return set()
        with open(self.path, "r") as f:
            data = json.load(f)  # raises JSONDecodeError on bad JSON
            if not isinstance(data, list):
                raise ValueError(f"replay store at {self.path} has invalid structure (not a list)")
            return set(data)

    def _write_state(self, fingerprints: set) -> bool:
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(sorted(fingerprints), f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
            return True
        except OSError:
            return False

    def reserve(self, fingerprint: str) -> tuple:
        """Try to reserve fingerprint.

        Returns (success: bool, reason: str).
        On lock contention: (False, "lock_unavailable")
        On corruption: (False, "replay_store_corrupt")
        On duplicate: (False, "replay_duplicate")
        On success: (True, "ok")
        """
        try:
            fd = os.open(self._lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.close(fd)
        except FileExistsError:
            return False, "lock_unavailable"
        try:
            try:
                state = self._read_state()  # raises on corruption
            except (json.JSONDecodeError, ValueError, OSError) as e:
                return False, "replay_store_corrupt"
            if fingerprint in state:
                return False, "replay_duplicate"
            state.add(fingerprint)
            if not self._write_state(state):
                return False, "replay_store_write_failure"
            return True, "ok"
        finally:
            try:
                os.unlink(self._lock_path)
            except OSError:
                pass


# =====================================================================
# Gate
# =====================================================================

class HUMAN_GO_GATE_V2:
    AUTHORIZED_ACTIONS = ("merge", "release", "deploy", "secret_write")

    def __init__(
        self,
        provenance_registry: ProvenanceRegistry,
        replay_store: ReplayStore,
    ):
        # B1/H1: provenance_registry is required; no default trust material.
        if provenance_registry is None:
            raise ValueError("provenance_registry is required (no default trust material)")
        # B2: replay_store is mandatory.
        if replay_store is None:
            raise ValueError("replay_store is required (fail-closed)")
        self.provenance_registry = provenance_registry
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
        owner_text = candidate.get("owner_text", "")
        if not owner_text:
            d.update(eligible=False, reason="owner_text_empty")
            return self._finalize(d, "REJECTED")

        owner_short = repo.split("/")[-1]
        pr_num = candidate.get("pr_number")
        if not self._target_and_action_explicit(owner_text, owner_short, pr_num, action):
            d.update(eligible=False, reason="owner_text_not_action_specific")
            return self._finalize(d, "REJECTED")

        # Step 6: repo collision check
        if self._has_repo_collision(owner_text, owner_short):
            d.update(eligible=False, reason="repo_collision_in_owner_text")
            return self._finalize(d, "REJECTED")

        # Step 7: owner_event_id must be a registered, signed, non-expired event
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

        # Step 8: current_owner_text action+repo+PR must match
        if current_owner_text is not None:
            if not self._target_and_action_explicit(current_owner_text, owner_short, pr_num, action):
                d.update(eligible=False, reason="current_owner_text_action_mismatch")
                return self._finalize(d, "REJECTED")

        # Step 9: atomic replay reservation (fail-closed on corruption)
        fingerprint = hashlib.sha256(
            f"{repo}|{pr_num}|{expected}|{action}|{owner_event_id}".encode()
        ).hexdigest()[:16]
        success, reason = self.replay_store.reserve(fingerprint)
        if not success:
            d.update(eligible=False, reason=reason, fingerprint=fingerprint)
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


# =====================================================================
# B3: pre_merge_adapter — the real enforcement seam
# =====================================================================

class GitHubMergeError(Exception):
    pass


def pre_merge_check_and_call(
    gate: HUMAN_GO_GATE_V2,
    candidate: dict,
    current_owner_text: Optional[str] = None,
    github_merge_callable=None,
):
    """B3: real enforcement seam.

    This is the function the ORCH/pre-merge code path MUST call before
    issuing any merge. It refuses to call github_merge_callable unless the
    gate returns eligible=True.

    github_merge_callable: the function that actually calls GitHub's merge
    endpoint. In tests, this is a stub. In production, it would be
    `gh pr merge` or the GitHub API call.

    The function returns a dict with `merged`, `fingerprint`, `gate_result`,
    and optionally `merge_result`. If eligible=False, it returns immediately
    without invoking github_merge_callable.
    """
    if github_merge_callable is None:
        raise ValueError("github_merge_callable required (no default execution path)")

    gate_result = gate.evaluate(candidate, current_owner_text=current_owner_text)
    if not gate_result.get("eligible"):
        return {
            "merged": False,
            "reason": gate_result.get("reason"),
            "gate_result": gate_result,
        }

    fingerprint = gate_result.get("fingerprint")
    try:
        merge_result = github_merge_callable(candidate)
    except Exception as e:
        return {
            "merged": False,
            "reason": "github_merge_failed",
            "fingerprint": fingerprint,
            "gate_result": gate_result,
            "error": str(e),
        }
    return {
        "merged": True,
        "fingerprint": fingerprint,
        "gate_result": gate_result,
        "merge_result": merge_result,
    }


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="HUMAN_GO_GATE_V2 — deterministic guard for HUMAN_GO_REAL."
    )
    parser.add_argument("candidate", help="Path to candidate.json")
    parser.add_argument("--events", required=True,
                        help="Path to JSON file with signed owner events")
    parser.add_argument("--secret-key", required=True,
                        help="Path to file containing the trusted signing secret")
    parser.add_argument("--replay-store", required=True,
                        help="Path to file used as atomic replay store")
    args = parser.parse_args()

    with open(args.candidate) as f:
        candidate = json.load(f)

    with open(args.secret_key, "rb") as f:
        secret_key = f.read().decode("utf-8").strip()

    registry = ProvenanceRegistry(secret_key=secret_key)
    with open(args.events) as f:
        events = json.load(f)
    accepted = 0
    rejected = 0
    reject_reasons = {}
    for evt in events:
        ok, reason = registry.add_event(evt)
        if ok:
            accepted += 1
        else:
            rejected += 1
            reject_reasons[reason] = reject_reasons.get(reason, 0) + 1

    store = ReplayStore(args.replay_store)
    g = HUMAN_GO_GATE_V2(provenance_registry=registry, replay_store=store)
    r = g.evaluate(candidate)

    # Side info: how many events were accepted/rejected
    r["_events_accepted"] = accepted
    r["_events_rejected"] = rejected
    if reject_reasons:
        r["_events_reject_reasons"] = reject_reasons

    print(json.dumps(r, indent=2, ensure_ascii=False))
    sys.exit(0 if r.get("eligible") else 1)
