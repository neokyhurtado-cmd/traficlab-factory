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
    # STRONG authorization verbs — explicit semantic authorization for sensitive actions.
    # These are required, not optional. Weak continuations like "dale", "ok", "si",
    # "go", "adelante", "avanza" are NOT strong enough for sensitive actions.
    # Rationale: "dale" is a conversational continuation, not an explicit authorization.
    STRONG_VERBS = (
        "apruebo", "aprobado", "aprobada",
        "autorizo", "autorizado", "autorizada",
        "confirmed", "confirmado",
        "merge", "mergeo", "mergeo",
        "despliego", "deploy",
    )

    # Action → required verb(s) for that specific action.
    # Action binding: a merge authorization must NOT authorize deploy/release/secret_write.
    ACTION_VERB_MAP = {
        "merge": ("apruebo", "aprobado", "aprobada",
                  "autorizo", "autorizado", "autorizada",
                  "confirmed", "confirmado",
                  "merge", "mergeo", "mergeo"),
        "deploy": ("despliego", "deploy",
                   "apruebo", "aprobado", "aprobada",
                   "autorizo", "autorizado", "autorizada"),
        "release": ("apruebo", "aprobado", "aprobada",
                    "autorizo", "autorizado", "autorizada",
                    "release", "releaseo"),
        "secret_write": ("explicit_secret_authorization",
                         "autorizo", "autorizado", "autorizada"),
    }

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
        # Gap 7: never echo raw candidate / owner_text into the result.
        # Keep only the action/repo/pr/expected_head in the candidate echo.
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
            verb_pattern_str = "|".join(re.escape(v) for v in self.STRONG_VERBS)
            verb_pattern = re.compile(verb_pattern_str, re.IGNORECASE)
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

        # Gap 2: action binding — verb in owner_text must be specific to the candidate action.
        # A merge authorization must NOT authorize deploy/release/secret_write.
        # Additionally: the verb must appear EARLY in the line (within first 5 words),
        # NOT just anywhere. This prevents "el merge" / "merge" as noun from passing
        # and prevents weak verbs like "dale" + "merge" passing because "merge" is
        # present somewhere in the line.
        action = candidate.get("action")
        allowed_verbs = self.ACTION_VERB_MAP.get(action, ())
        if not allowed_verbs:
            d.update(eligible=False, reason="no_verbs_for_action")
            return self._finalize(d, "REJECTED")

        # Pattern: optional connective (comma, colon, "Ok", etc.) followed by a verb
        # in the allowed list, then the target reference.
        action_specific_pattern = re.compile(
            r"^\s*(?:[A-Za-z]{1,20}[,.:;]\s+)*("
            + "|".join(re.escape(v) for v in allowed_verbs)
            + r")\b",
            re.IGNORECASE,
        )
        auth_lines = [l for l in target_lines if action_specific_pattern.search(l)]
        if not auth_lines:
            d.update(eligible=False, reason="no_action_specific_authorization_verb")
            return self._finalize(d, "REJECTED")

        # Step 5: replay protection
        fingerprint = hashlib.sha256(
            f"{repo}|{pr_num}|{expected}|{action}".encode()
        ).hexdigest()[:16]
        if fingerprint in self._used_fingerprints:
            d.update(eligible=False, reason="replay_detected", fingerprint=fingerprint)
            return self._finalize(d, "REJECTED")

        # Step 6: live_pr_head must match expected_head (required for merge, optional for others but recommended)
        live = candidate.get("live_pr_head")
        if live is None:
            d.update(eligible=False, reason="live_pr_head_required")
            return self._finalize(d, "REJECTED")
        if live != expected:
            d.update(eligible=False, reason="stale_head_detected")
            return self._finalize(d, "REJECTED")

        # Step 7 (Gap 5): owner provenance check — caller must supply trusted owner source.
        # owner_provenance is a dict supplied by an authenticated caller; if absent, fail-closed.
        provenance = candidate.get("owner_provenance")
        if not provenance:
            d.update(eligible=False, reason="owner_provenance_missing")
            return self._finalize(d, "REJECTED")
        if not self._verify_provenance(provenance):
            d.update(eligible=False, reason="owner_provenance_invalid")
            return self._finalize(d, "REJECTED")

        # Step 8 (Gap 6): exact-target repo identity — no substring/prefix/suffix/collision matches.
        # Reject if owner_text contains a repo-like string that would create ambiguity.
        if self._has_repo_collision(owner_text, owner_short):
            d.update(eligible=False, reason="repo_collision_in_owner_text")
            return self._finalize(d, "REJECTED")

        # ALL PASS
        self._used_fingerprints.add(fingerprint)
        self._save()
        # Gap 7 already handled at start of evaluate: candidate never carries raw owner_text.
        d.update(eligible=True, reason="all_gates_passed", fingerprint=fingerprint)
        d["action"] = action
        d["repo"] = repo
        d["pr_number"] = pr_num
        return self._finalize(d, "ELIGIBLE")

    def _verify_provenance(self, provenance: dict) -> bool:
        """Gap 5: trusted owner provenance.

        Provenance is a dict supplied by an authenticated caller.
        Must include: source (str, one of AUTHENTICATED_SOURCES),
                      verified_at (ISO 8601 timestamp),
                      verifier (e.g. 'pinned_user_check', 'openai_oauth', 'github_oauth').
        This gate treats ALL provenance as 'trusted if and only if it has these
        fields and source is in the allowlist'. The caller is responsible for
        actually authenticating the owner. The gate just enforces the contract.
        """
        if not isinstance(provenance, dict):
            return False
        source = provenance.get("source")
        verified_at = provenance.get("verified_at")
        verifier = provenance.get("verifier")
        if not source or not verified_at or not verifier:
            return False
        if source not in ("pinned_user", "openai_oauth", "github_oauth", "tailscale_auth"):
            return False
        # verified_at must be a parseable ISO timestamp
        try:
            from datetime import datetime
            datetime.fromisoformat(verified_at.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return False
        return True

    def _has_repo_collision(self, owner_text: str, owner_short: str) -> bool:
        """Gap 6: repo identity must be exact. Reject prefix/suffix/collision.

        Examples that MUST be rejected:
        - 'old-traficlab-factory-backup' (suffix collision)
        - 'traficlab-factory-old' (suffix)
        - 'my-traficlab-factory' (prefix)
        - 'xtraficlab-factoryx' (subword)
        """
        # Look for any contiguous word/hyphen pattern that contains owner_short
        # but is NOT exactly owner_short.
        pattern = re.compile(r"[a-zA-Z0-9_-]*" + re.escape(owner_short) + r"[a-zA-Z0-9_-]*", re.IGNORECASE)
        for m in pattern.finditer(owner_text):
            if m.group().lower() != owner_short.lower():
                return True
        # Also check if owner_short appears with prefix (alphanumeric or hyphen before)
        prefix_pattern = re.compile(r"[a-zA-Z0-9]" + re.escape(owner_short) + r"\b", re.IGNORECASE)
        if prefix_pattern.search(owner_text):
            return True
        # Suffix check
        suffix_pattern = re.compile(r"\b" + re.escape(owner_short) + r"[a-zA-Z0-9]", re.IGNORECASE)
        if suffix_pattern.search(owner_text):
            return True
        return False

    def _finalize(self, d, status):
        d["status"] = status
        return d


if __name__ == "__main__":
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(
        description="HUMAN_GO_GATE_V2 — deterministic guard for HUMAN_GO_REAL."
    )
    parser.add_argument("candidate", help="Path to candidate.json")
    parser.add_argument("current_owner_text", nargs="?", default=None,
                        help="Path to file with latest owner message text")
    parser.add_argument("--persist", default=None,
                        help="Path to file for persisting replay fingerprints across invocations")
    args = parser.parse_args()

    with open(args.candidate) as f:
        candidate = json.load(f)
    cot = None
    if args.current_owner_text:
        with open(args.current_owner_text) as f:
            cot = f.read()
    g = HUMAN_GO_GATE_V2(persist_path=args.persist)
    r = g.evaluate(candidate, current_owner_text=cot)
    print(json.dumps(r, indent=2, ensure_ascii=False))
    sys.exit(0 if r.get("eligible") else 1)
