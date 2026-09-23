"""BODY-x Skill Fabric V1 — registry + validator.

Loads the canonical skills registry under ``.hermes/skills-registry/skills.yaml``
and validates every entry against the intake policy in
``policies/skill-fabric-intake.md`` plus the license gate in
``policies/license-gate.md``.

Public surface:

    load_registry(path=None) -> Registry
        Returns the loaded and SHAPE-validated registry.  Shape validation
        here is purely structural — ``validate_entry`` does the
        policy-level checks.

    validate_entry(entry, *, live_sha=None, drift_strategy="CANDIDATE") -> list[str]
        Returns a list of human-readable validation failures.  An empty list
        means PASS.  The function NEVER raises — ``validate_registry``
        raises ``RegistryValidationError`` ONLY if you ask it to surface
        a hard failure.

    validate_registry(registry, *, ..., live_sha_for=...) -> RegistryValidationResult
        Validates the whole registry.  Returns a result object with
        ``passed_ids``, ``blocked_ids``, ``fail_messages``.

    detect_authority_conflicts(entries) -> dict[id, list[str]]
        Pure analysis: which entries claim any kind of authority over
        decision / merge / dispatch / hierarchy.  Used by the conflict
        resolver.

    resolve_skill_router(intent, registry) -> list[id]
        Task-scoped router used by ``.hermes/skills/skill-fabric-router``.
        Given a free-text intent, return the ordered list of skill ids
        that match (intent-aware), respecting mode + allowed_projects.

Hardening rules:

  - All functions fail closed: ambiguous input returns the safer
    verdict.  No function raises a bare ``Exception``.
  - No network calls.  Live SHAs are passed in by the caller.
  - No mutation of the input registry.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import yaml


# ----- SHA / license primitives -------------------------------------------------

VALID_MODES = ("BLOCKED", "CANDIDATE", "CATALOG", "SHADOW", "ACTIVE")
OSI_OR_SOURCE_AVAILABLE_LICENSES = frozenset({
    "MIT",
    "BSD-2-CLAUSE",
    "BSD-3-CLAUSE",
    "APACHE-2.0",
    "MPL-2.0",
    "ISC",
})
BLOCKING_LICENSES = frozenset({
    "BSL-1.1",
    "SSPL-1.0",
    "SSPL",
    "BUSL-1.1",
    "BUSL",
})
NON_LICENSES = frozenset({
    "NOASSERTION",
    "NONE",
    "OTHER",
    "UNLICENSED",
})


def is_valid_sha(sha: str) -> bool:
    """True iff the string is a 40-character lowercase hex SHA."""
    if not isinstance(sha, str) or len(sha) != 40:
        return False
    return all(c in "0123456789abcdef" for c in sha)


def is_open_license(spdx: str) -> bool:
    return isinstance(spdx, str) and spdx.upper() in OSI_OR_SOURCE_AVAILABLE_LICENSES


def is_blocking_license(spdx: str) -> bool:
    return isinstance(spdx, str) and spdx.upper() in {x.upper() for x in BLOCKING_LICENSES}


def is_non_license(spdx: str) -> bool:
    return isinstance(spdx, str) and spdx.upper() in {x.upper() for x in NON_LICENSES}


# ----- Data classes -------------------------------------------------------------


@dataclass(frozen=True)
class SkillEntry:
    id: str
    upstream_repo: str
    upstream_commit: str
    upstream_default_branch: str
    upstream_license: str
    spdx_id_ok: bool
    mode: str
    capabilities: Mapping[str, Any]
    conflicts: List[str]
    allowed_projects: List[str]
    activation_scope: str
    rollback: Mapping[str, Any]
    evidence: str
    rationale: str
    raw: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_dual_license(self) -> bool:
        return isinstance(self.upstream_license, str) and self.upstream_license.upper() == "DUAL"

    @property
    def is_pinnable(self) -> bool:
        return is_valid_sha(self.upstream_commit)


@dataclass(frozen=True)
class Registry:
    version: int
    schema: str
    fail_closed: bool
    defaults: Mapping[str, Any]
    entries: List[SkillEntry]
    raw: Mapping[str, Any]

    def by_id(self, skill_id: str) -> Optional[SkillEntry]:
        for e in self.entries:
            if e.id == skill_id:
                return e
        return None


@dataclass(frozen=True)
class RegistryValidationResult:
    passed_ids: List[str]
    candidate_ids: List[str]   # PASS shape, but mode == CANDIDATE awaiting shadow canary
    catalog_ids: List[str]
    shadow_ids: List[str]
    active_ids: List[str]
    blocked_ids: List[str]
    fail_messages: Dict[str, List[str]]   # entry.id -> list of failure messages

    @property
    def any_failures(self) -> bool:
        return bool(self.fail_messages)


class RegistryValidationError(RuntimeError):
    """Raised by ``validate_registry(strict=True)`` when a hard gate fails."""


# ----- Loader -------------------------------------------------------------------


_DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parent.parent / ".hermes" / "skills-registry" / "skills.yaml"


def load_registry(path: Optional[Path] = None) -> Registry:
    """Load the registry from disk.  Pure structural validation here."""
    p = Path(path or _DEFAULT_REGISTRY_PATH)
    if not p.exists():
        raise FileNotFoundError(f"Skill Fabric registry not found: {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}

    if not isinstance(raw, Mapping):
        raise RegistryValidationError("Registry root must be a mapping")

    schema = raw.get("schema", "")
    if schema != "skill-fabric/v1":
        raise RegistryValidationError(
            f"Unsupported registry schema: {schema!r}. Expected 'skill-fabric/v1'."
        )

    version = int(raw.get("version", 0))
    if version != 1:
        raise RegistryValidationError(
            f"Unsupported registry version: {version}. Only version 1 is currently supported."
        )

    fail_closed = bool(raw.get("fail_closed", True))

    defaults = raw.get("defaults", {}) or {}
    if not isinstance(defaults, Mapping):
        raise RegistryValidationError("Registry `defaults` must be a mapping")

    skills_raw = raw.get("skills", [])
    if not isinstance(skills_raw, list):
        raise RegistryValidationError("Registry `skills` must be a list")

    entries: List[SkillEntry] = []
    for s in skills_raw:
        entries.append(_entry_from_raw(s))

    return Registry(
        version=version,
        schema=schema,
        fail_closed=fail_closed,
        defaults=defaults,
        entries=entries,
        raw=raw,
    )


def _entry_from_raw(raw: Mapping[str, Any]) -> SkillEntry:
    """Construct a SkillEntry from a raw mapping.  No policy validation here."""
    sid = str(raw.get("id", "")).strip()
    if not sid:
        raise RegistryValidationError("Skill entry missing `id`")
    return SkillEntry(
        id=sid,
        upstream_repo=str(raw.get("upstream_repo", "")).strip(),
        upstream_commit=str(raw.get("upstream_commit", "")).strip(),
        upstream_default_branch=str(raw.get("upstream_default_branch", "")).strip(),
        upstream_license=str(raw.get("upstream_license", "")).strip(),
        spdx_id_ok=bool(raw.get("spdx_id_ok", False)),
        mode=str(raw.get("mode", "CATALOG")).strip().upper(),
        capabilities=dict(raw.get("capabilities", {}) or {}),
        conflicts=list(raw.get("conflicts", []) or []),
        allowed_projects=list(raw.get("allowed_projects", []) or []),
        activation_scope=str(raw.get("activation_scope", "cataloged-only")),
        rollback=dict(raw.get("rollback", {}) or {}),
        evidence=str(raw.get("evidence", "")),
        rationale=str(raw.get("rationale", "")),
        raw=dict(raw),
    )


# ----- Single-entry validator ----------------------------------------------------


def validate_entry(
    entry: SkillEntry,
    *,
    live_sha: Optional[str] = None,
    drift_strategy: str = "CANDIDATE",
) -> List[str]:
    """Return a list of failure messages.  Empty list means PASS.

    ``drift_strategy`` controls what to do when ``live_sha`` is supplied
    and differs from ``entry.upstream_commit``.  Allowed values:

      - "CANDIDATE" (default):  downgrade to CANDIDATE in the returned
        pass-class, do not block.
      - "BLOCK":                treat as a hard failure.

    Does NOT mutate the entry.  Callers decide whether to override the
    entry's mode.
    """
    failures: List[str] = []

    # 1. ID present.
    if not entry.id:
        failures.append("FAIL: missing entry.id")

    # 2. Upstream repo present.
    if not entry.upstream_repo or "/" not in entry.upstream_repo:
        failures.append(f"FAIL: upstream_repo malformed (entry={entry.id!r})")

    # 3. Pin exactly: 40-char hex SHA.
    if not entry.upstream_commit:
        failures.append(f"FAIL[{entry.id}]: upstream_commit missing")
    elif not is_valid_sha(entry.upstream_commit):
        failures.append(
            f"FAIL[{entry.id}]: upstream_commit {entry.upstream_commit!r} is not a 40-char hex SHA"
        )

    # 4. SHA drift against live.
    if live_sha is not None:
        if not is_valid_sha(live_sha):
            failures.append(
                f"FAIL[{entry.id}]: live_sha passed in but is not a 40-char hex value"
            )
        elif live_sha != entry.upstream_commit and entry.mode in ("SHADOW", "ACTIVE"):
            msg = (
                f"DRIFT[{entry.id}]: upstream_commit {entry.upstream_commit} differs from "
                f"live default_branch HEAD {live_sha}. mode={entry.mode} requires re-audit."
            )
            if drift_strategy == "BLOCK":
                failures.append("FAIL" + msg[4:])  # upgrade DRIFT to FAIL
            else:
                failures.append(msg)

    # 5. License gate (single SPDX).
    if entry.is_dual_license:
        # Dual-license: require an explicit license_detail with permissive + restrictive
        ld = entry.raw.get("license_detail", {}) or {}
        permissive = str(ld.get("permissive", "")).upper()
        restrictive = str(ld.get("restrictive", "")).upper()
        if not is_open_license(permissive):
            failures.append(
                f"LICENSE_GATE_FAIL[{entry.id}]: dual-license entry has no permissive SPDX "
                f"in license_detail.permissive (got {ld.get('permissive')!r})"
            )
        if restrictive and not is_blocking_license(restrictive):
            failures.append(
                f"LICENSE_GATE_WARN[{entry.id}]: dual-license restrictive label "
                f"{restrictive!r} not in known BSL/SSPL set"
            )
        # Mode higher than CATALOG requires vendored_directories to be [] or
        # all under permissive scope.
        if entry.mode in ("SHADOW", "ACTIVE"):
            vd = entry.raw.get("vendored_directories", []) or []
            if vd:
                failures.append(
                    f"LICENSE_GATE_FAIL[{entry.id}]: mode={entry.mode} with vendored_directories "
                    f"{vd!r} is incompatible with dual-license under LICENSE_GATE"
                )
    else:
        lic = entry.upstream_license.upper()
        if is_non_license(lic):
            # NOASSERTION / NONE / UNLICENSED:
            #   - CATALOG: warn only (catalog is reference material)
            #   - higher modes: hard fail
            if entry.mode == "CATALOG":
                failures.append(
                    f"LICENSE_GATE_WARN[{entry.id}]: upstream_license={entry.upstream_license!r} "
                    f"catalogued without a known SPDX; cannot promote above CATALOG"
                )
            else:
                failures.append(
                    f"LICENSE_GATE_FAIL[{entry.id}]: upstream_license={entry.upstream_license!r} "
                    f"is not a valid SPDX identifier (mode={entry.mode})"
                )
        elif is_blocking_license(lic):
            if entry.mode in ("SHADOW", "ACTIVE"):
                failures.append(
                    f"LICENSE_GATE_FAIL[{entry.id}]: upstream_license={entry.upstream_license!r} "
                    f"is blocking at mode {entry.mode}"
                )
        elif not is_open_license(lic):
            failures.append(
                f"LICENSE_GATE_FAIL[{entry.id}]: upstream_license={entry.upstream_license!r} "
                f"not in OSI/source-available allow-list"
            )

    # 6. Mode sanity.
    if entry.mode not in VALID_MODES:
        failures.append(
            f"FAIL[{entry.id}]: mode {entry.mode!r} not in {VALID_MODES}"
        )

    # 7. SHADOW / ACTIVE: spdx_id_ok must be True and a non-empty evidence pointer must exist.
    if entry.mode in ("SHADOW", "ACTIVE"):
        if not entry.spdx_id_ok:
            failures.append(
                f"FAIL[{entry.id}]: SHADOW/ACTIVE requires spdx_id_ok=true"
            )
        if not entry.evidence:
            failures.append(
                f"FAIL[{entry.id}]: SHADOW/ACTIVE requires non-empty `evidence` pointer"
            )
        if not entry.allowed_projects:
            failures.append(
                f"FAIL[{entry.id}]: SHADOW/ACTIVE requires non-empty `allowed_projects`"
            )

    # 8. Side-effect declaration complete.
    required_caps = {"network_access", "filesystem_read", "filesystem_write",
                     "shell_exec", "subagent_spawn", "prompt_injection_surface",
                     "dependency_install"}
    missing = required_caps - set(entry.capabilities.keys())
    if missing and entry.mode in ("SHADOW", "ACTIVE", "CANDIDATE"):
        failures.append(
            f"FAIL[{entry.id}]: missing capability declarations: {sorted(missing)}"
        )

    # 9. Rollback discipline.
    if entry.mode in ("SHADOW", "ACTIVE", "CANDIDATE"):
        rb = entry.rollback or {}
        rb_type = rb.get("type")
        if rb_type not in {"filesystem-mirror", "filesystem-marker",
                            "filesystem-cache", "opt-in-flag", "derived-cache"}:
            failures.append(
                f"FAIL[{entry.id}]: rollback.type {rb_type!r} not in the deterministic "
                f"rollback taxonomy"
            )
        if not rb.get("disable_command"):
            failures.append(
                f"FAIL[{entry.id}]: rollback.disable_command missing — every vendored skill "
                f"must declare how to disable itself"
            )

    # 10. Activation scope sanity.
    if entry.activation_scope not in {
        "task-scoped", "cataloged-only", "cataloged-discovery-feed",
        "read-only-derived-adapter", "per-subskill-on-demand",
    }:
        failures.append(
            f"FAIL[{entry.id}]: activation_scope {entry.activation_scope!r} is not in "
            f"the canonical set"
        )

    return failures


# ----- Whole-registry validation ------------------------------------------------


def validate_registry(
    registry: Registry,
    *,
    live_sha_for: Optional[Mapping[str, str]] = None,
    strict: bool = False,
) -> RegistryValidationResult:
    """Validate every entry.  If ``strict``, raise on any failure.

    ``live_sha_for`` is a mapping of entry.id -> live default-branch HEAD
    SHA (40-char hex).  Used for drift detection.
    """
    live_sha_for = live_sha_for or {}
    passed: List[str] = []
    candidate: List[str] = []
    catalog: List[str] = []
    shadow: List[str] = []
    active: List[str] = []
    blocked: List[str] = []
    fails: Dict[str, List[str]] = {}

    for entry in registry.entries:
        live_sha = live_sha_for.get(entry.id)
        msgs = validate_entry(entry, live_sha=live_sha)
        if msgs:
            # Any FAIL -> BLOCKED.
            fails[entry.id] = msgs
            blocked.append(entry.id)
        else:
            if entry.mode == "BLOCKED":
                blocked.append(entry.id)
            elif entry.mode == "CATALOG":
                catalog.append(entry.id)
                passed.append(entry.id)
            elif entry.mode == "CANDIDATE":
                candidate.append(entry.id)
                passed.append(entry.id)
            elif entry.mode == "SHADOW":
                shadow.append(entry.id)
                passed.append(entry.id)
            elif entry.mode == "ACTIVE":
                active.append(entry.id)
                passed.append(entry.id)
            else:
                blocked.append(entry.id)

    if strict and fails:
        raise RegistryValidationError(
            "Skill Fabric registry failed: " +
            "; ".join(f"{k}: {'; '.join(v)}" for k, v in fails.items())
        )

    return RegistryValidationResult(
        passed_ids=passed,
        candidate_ids=candidate,
        catalog_ids=catalog,
        shadow_ids=shadow,
        active_ids=active,
        blocked_ids=blocked,
        fail_messages=fails,
    )


# ----- Conflict analyzer + router ----------------------------------------------


AUTHORITY_KEYWORDS = (
    "merge_to_main",
    "merge",
    "release",
    "dispatch",
    "scheduler",
    "orchestrat",
    "authority",
    "hierarchy",
    "system-instruction",
    "override",
    "rewrite",
    "policy",
    "AGENTS.md",
    "CLAUDE.md",
    "SOUL.md",
)


def detect_authority_conflicts(entries: List[SkillEntry]) -> Dict[str, List[str]]:
    """Pure analysis: list authority-shaped surfaces in each entry.

    The Skill Fabric conflict resolver uses this to refuse to load two
    skills simultaneously when both touch the same authority surface.
    """
    out: Dict[str, List[str]] = {}
    for e in entries:
        surfaces: List[str] = []
        for kw in AUTHORITY_KEYWORDS:
            if kw.lower() in e.rationale.lower():
                surfaces.append(kw)
            for c in e.conflicts:
                if kw.lower() in c.lower():
                    surfaces.append(f"conflict:{c}:{kw}")
        if surfaces:
            out[e.id] = sorted(set(surfaces))
    return out


def resolve_skill_router(
    intent: str,
    registry: Registry,
    *,
    project: Optional[str] = None,
    intent_keywords: Optional[List[str]] = None,
) -> List[str]:
    """Select an ordered list of skill ids for a free-text intent.

    Heuristic (deliberately conservative so progressive discovery
    holds — a fresh worker must NOT load every skill on every prompt):

    1. Build a token set from the intent: lower-cased word-split, with
       a small stop-word list removed.
    2. For each registry entry, score by:
         - id / repo-anchor literal match (strong)
         - explicit intent-keywords supplied by the caller (very strong)
         - catalog-mode bias
         - activation_scope bias
         - mode bias (ACTIVE > SHADOW > CANDIDATE > CATALOG)
    3. Project allowlist:
         - entries with empty `allowed_projects` and mode==CATALOG:
           score=0 unless caller supplies intent_keywords that match
           the entry's id (catalog reference material).
         - entries with non-empty `allowed_projects`: HARD-EXCLUDE if
           `project` is supplied and not in the allowlist.
    4. Final score must be >= 4 to make the cut.  Empty list means
       "fall back to canonical Factory behavior".

    Returns an ordered list of skill ids (best match first).
    """
    if not isinstance(intent, str) or not intent.strip():
        return []
    text = intent.lower()
    tokens = _tokenize_intent(text)
    explicit = set((intent_keywords or []) or [])
    explicit = {t.lower() for t in explicit if isinstance(t, str)}

    scored: List[tuple] = []   # (score, skill_id)
    for entry in registry.entries:
        if entry.mode == "BLOCKED":
            continue

        # 1. Project allowlist HARD GATE.
        if project is not None and entry.allowed_projects:
            if project not in entry.allowed_projects:
                continue   # entry is not available for this project at all

        rid = entry.id.lower()
        repo_anchor = entry.upstream_repo.split("/")[-1].lower() if entry.upstream_repo else ""
        id_tokens = _id_tokens(rid)

        score = 0

        # 2. Strong literal match: id or repo-anchor literal in intent text.
        for tok in tokens:
            if not tok:
                continue
            if tok == rid or tok in id_tokens:
                score += 8
            elif tok == repo_anchor:
                score += 6

        # 3. Caller-provided explicit keywords (caller contracts the router
        # by saying "this task is about X").
        for ek in explicit:
            if ek == rid or ek in id_tokens or ek == repo_anchor:
                score += 10

        # 4. Mode bias.
        if entry.mode == "ACTIVE":
            score += 3
        elif entry.mode == "SHADOW":
            score += 2
        elif entry.mode == "CANDIDATE":
            score += 1
        # CATALOG gets no bias; only literal/explicit matches lift it above 0.

        # 5. Activation-scope bias.
        if entry.activation_scope in {
            "task-scoped", "per-subskill-on-demand",
            "read-only-derived-adapter"
        }:
            score += 1
        elif entry.activation_scope == "cataloged-only":
            # Catalog-only entries are reference material — they should
            # NOT load on ordinary intent matches, only via explicit
            # ``intent_keywords`` supplied by the caller.  Floor the score
            # so a literal id match alone never trips the threshold.
            score = max(0, score - 8)

        if score >= 4:
            scored.append((score, entry.id))

    scored.sort(key=lambda x: (-x[0], x[1]))
    return [sid for _, sid in scored]


_INTENT_STOPWORDS = frozenset({
    "the", "and", "for", "with", "from", "into", "what", "how", "why",
    "that", "this", "these", "those", "have", "has", "had",
    "are", "was", "were", "be", "been", "being",
    "to", "of", "in", "on", "at", "by", "as", "or", "an", "a", "is",
    "i", "we", "you", "they", "he", "she", "it",
    "do", "did", "does", "doing",
    "use", "using", "used",
    "need", "needs", "needed",
    "task", "tasks", "work", "code", "make", "run",
    "plan", "plans", "tested", "tests",
    "end", "to", "during", "before", "after", "over", "under",
})


def _tokenize_intent(text: str) -> List[str]:
    out: List[str] = []
    for tok in text.replace("/", " ").replace("-", " ").replace(".", " ").split():
        tok = tok.strip(".,;:?!()[]{}\"'`").lower()
        if not tok or tok in _INTENT_STOPWORDS:
            continue
        if len(tok) < 3:
            continue
        out.append(tok)
    return out


def _id_tokens(skill_id: str) -> set:
    return {t for t in skill_id.replace("-", " ").split() if len(t) >= 3}


# ----- Convenience used by tests / CLI ------------------------------------------

def summarize(result: RegistryValidationResult) -> str:
    return (
        f"skill-fabric/v1 registry: "
        f"passed={len(result.passed_ids)} blocked={len(result.blocked_ids)} "
        f"catalog={len(result.catalog_ids)} candidate={len(result.candidate_ids)} "
        f"shadow={len(result.shadow_ids)} active={len(result.active_ids)}"
    )
