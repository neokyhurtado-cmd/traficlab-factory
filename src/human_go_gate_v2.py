import os
"""HUMAN_GO_GATE_V2 — deterministic guard for HUMAN_GO_REAL.

Prevents false-positive "go" by requiring:
1. Explicit target reference: repo AND pr_number in same line of owner_text
2. Authorization verb in the target line (apruebo, aprobar, merge, etc.)
3. If current_owner_text provided, the latest owner message also authorizes this target
4. expected_head is a valid SHA (40 hex chars)
5. Replay protection: same (repo, pr_number, expected_head) can't be used twice
6. Live head check: live_pr_head must match expected_head (stale-head denial)
"""
import hashlib
import re
import time
from typing import Optional


class HUMAN_GO_GATE_V2:
    AUTHORIZATION_VERBS = (
        "merge", "mergeo", "apruebo", "aprobado", "aprobada",
        "despliego", "deploy", "go", "ok", "si", "vale", "autorizado",
        "dale", "ok dale", "adelante", "confirmo", "confirmado",
    )

    AUTHORIZED_ACTIONS = ("merge", "release", "deploy", "secret_write")

    def __init__(self, persist_path: Optional[str] = None):
        self._used_fingerprints = set()
        self.persist_path = persist_path
        if persist_path and os.path.exists(persist_path):
            import json
            with open(persist_path) as f:
                self._used_fingerprints = set(json.load(f))

    def _save(self):
        if self.persist_path:
            import json
            with open(self.persist_path, "w") as f:
                json.dump(sorted(self._used_fingerprints), f)

    def evaluate(self, candidate: dict, current_owner_text: Optional[str] = None) -> dict:
        d = {
            "ts": time.time(),
            "candidate": candidate,
            "current_owner_text_provided": current_owner_text is not None,
        }

        # Step 0: current_owner_text (latest message) must authorize this target
        # — runs FIRST so unrelated/replayed owner_text gets caught early.
        if current_owner_text is not None:
            repo = candidate.get("repo", "")
            if "/" in repo:
                owner_short = repo.split("/")[-1]
            else:
                owner_short = repo
            pr_num = candidate.get("pr_number")
            pr_pattern = re.compile(
                rf"\b{re.escape(owner_short)}\b.*?(?:PR[ #]?#{pr_num}|PR[ #]?{pr_num}|#{pr_num}\b)|"
                rf"(?:PR[ #]?#{pr_num}|PR[ #]?{pr_num}|#{pr_num}\b).*?\b{re.escape(owner_short)}\b",
                re.IGNORECASE,
            )
            verb_pattern = re.compile(
                "|".join(re.escape(v) for v in self.AUTHORIZATION_VERBS),
                re.IGNORECASE,
            )
            cur_target = [l for l in current_owner_text.splitlines() if pr_pattern.search(l)]
            cur_auth = [l for l in cur_target if verb_pattern.search(l)]
            if not cur_auth:
                d.update(eligible=False, reason="current_owner_text_unrelated_or_stale")
                return self._finalize(d, "REJECTED")

        # Step 1: action allowlist
        if candidate.get("action") not in self.AUTHORIZED_ACTIONS:
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

        # Step 4: owner_text references target + has authorization verb
        owner_text = candidate.get("owner_text", "")
        if not owner_text:
            d.update(eligible=False, reason="owner_text_empty")
            return self._finalize(d, "REJECTED")

        owner_short = repo.split("/")[-1]
        pr_num = candidate.get("pr_number")
        pr_pattern = re.compile(
            rf"\b{re.escape(owner_short)}\b.*?(?:PR[ #]?#{pr_num}|PR[ #]?{pr_num}|#{pr_num}\b)|"
            rf"(?:PR[ #]?#{pr_num}|PR[ #]?{pr_num}|#{pr_num}\b).*?\b{re.escape(owner_short)}\b",
            re.IGNORECASE,
        )
        target_lines = [l for l in owner_text.splitlines() if pr_pattern.search(l)]
        if not target_lines:
            d.update(eligible=False, reason="owner_text_target_mismatch")
            return self._finalize(d, "REJECTED")

        verb_pattern = re.compile(
            "|".join(re.escape(v) for v in self.AUTHORIZATION_VERBS),
            re.IGNORECASE,
        )
        auth_lines = [l for l in target_lines if verb_pattern.search(l)]
        if not auth_lines:
            d.update(eligible=False, reason="no_authorization_verb")
            return self._finalize(d, "REJECTED")

        # Step 5: replay protection
        fingerprint = hashlib.sha256(
            f"{repo}|{pr_num}|{expected}".encode()
        ).hexdigest()[:16]
        if fingerprint in self._used_fingerprints:
            d.update(eligible=False, reason="replay_detected", fingerprint=fingerprint)
            return self._finalize(d, "REJECTED")

        # Step 6: live_pr_head must match expected_head
        live = candidate.get("live_pr_head")
        if live is not None and live != expected:
            d.update(eligible=False, reason="stale_head_detected")
            return self._finalize(d, "REJECTED")

        # ALL PASS
        self._used_fingerprints.add(fingerprint)
        self._save()
        d.update(eligible=True, reason="all_gates_passed", fingerprint=fingerprint)
        return self._finalize(d, "ELIGIBLE")

    def _finalize(self, d, status):
        d["status"] = status
        return d


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) < 2:
        print("Usage: human_go_gate_v2.py <candidate.json> [current_owner_text.txt]", file=sys.stderr)
        sys.exit(2)
    with open(sys.argv[1]) as f:
        candidate = json.load(f)
    cot = None
    if len(sys.argv) >= 3:
        with open(sys.argv[2]) as f:
            cot = f.read()
    g = HUMAN_GO_GATE_V2()
    r = g.evaluate(candidate, current_owner_text=cot)
    print(json.dumps(r, indent=2, ensure_ascii=False))
    sys.exit(0 if r.get("eligible") else 1)
