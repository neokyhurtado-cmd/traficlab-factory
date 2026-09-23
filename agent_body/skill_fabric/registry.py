"""Skill Fabric — registry schema, loader, validator.

V1 SCAFFOLD state (skill-fabric-v1-implant-20260922-01).

No external skill may bypass these gates. Intake is fail-closed: any
validation failure rejects the skill entry with an explicit reason.

Authority hierarchy (mirrors issue #51 and Factory canonical policy):

    GitHub durable truth
    > TrafficLab Factory policies / authority
    > Agent Body capability boundaries
    > project contracts
    > external skill instructions

An external skill can add capability. It can NEVER override authority,
merge policy, HUMAN_GO_REAL, source-of-truth rules, secrets rules,
one-writer rules, or product ownership.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml


# ---------- Enums ----------------------------------------------------------


class Mode(str, Enum):
    BLOCKED = "BLOCKED"
    CANDIDATE = "CANDIDATE"
    SHADOW = "SHADOW"
    ACTIVE = "ACTIVE"
    CATALOG = "CATALOG"


# ---------- License allowlist (SPDX) ---------------------------------------


# Conservative set; expand only with explicit Factory approval.
ACCEPTED_SPDX_LICENSES = frozenset(
    {
        "MIT",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "ISC",
        "MPL-2.0",
        "Unlicense",
        "CC0-1.0",
        "CC-BY-4.0",
        "CC-BY-SA-4.0",
    }
)


# ---------- Schema ---------------------------------------------------------


@dataclass(frozen=True)
class SkillEntry:
    id: str
    upstream_repo: str
    upstream_commit: str
    upstream_license: Optional[str]
    mode: Mode
    capabilities: List[str] = field(default_factory=list)
    network_access: bool = False
    filesystem_read: List[str] = field(default_factory=list)
    filesystem_write: List[str] = field(default_factory=list)
    shell_exec: bool = False
    subagent_spawn: bool = False
    prompt_injection_surface: str = "none"
    dependency_install: str = "none"
    conflicts: List[str] = field(default_factory=list)
    allowed_projects: List[str] = field(default_factory=lambda: ["*"])
    activation_scope: str = "on_demand"
    rollback: str = ""
    evidence: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["mode"] = self.mode.value
        return d


# ---------- Validation gates ----------------------------------------------


_HEX40 = re.compile(r"^[0-9a-f]{40}$")


def validate_entry(raw: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Run fail-closed intake gates on a candidate registry entry.

    Returns (ok, reasons). `ok=False` if any reason is present.
    """
    reasons: List[str] = []

    # Required fields
    for required in ("id", "upstream_repo", "upstream_commit", "mode"):
        if required not in raw or raw[required] in (None, ""):
            reasons.append(f"missing required field: {required}")

    if reasons:
        return False, reasons

    # Upstream commit must be exact 40-char hex (no floating refs for ACTIVE/SHADOW)
    commit = str(raw.get("upstream_commit", ""))
    mode = Mode(str(raw.get("mode", "")))
    if mode in (Mode.ACTIVE, Mode.SHADOW):
        if not _HEX40.match(commit):
            reasons.append(
                f"upstream_commit must be 40-char hex SHA for mode={mode.value}; "
                f"got {commit!r}"
            )

    # License gate
    license_id = raw.get("upstream_license")
    if license_id is None or str(license_id).strip() in ("", "UNKNOWN", "NOASSERTION"):
        if mode in (Mode.ACTIVE, Mode.SHADOW):
            reasons.append(
                f"upstream_license must be SPDX-known for mode={mode.value}; "
                f"got {license_id!r}"
            )
    elif str(license_id) not in ACCEPTED_SPDX_LICENSES:
        reasons.append(
            f"upstream_license {license_id!r} is not in the accepted SPDX allowlist"
        )

    # Forbidden capabilities (mirror issue #51 no-go list)
    forbidden = raw.get("forbidden_demands") or []
    forbidden_flags = {
        "DIRECT_MAIN_WRITE",
        "FORCE_PUSH",
        "AUTO_MERGE_MAIN",
        "SECRETS_MUTATION",
        "CONFIG_YAML_MUTATION",
        "ENV_MUTATION",
        "GATEWAY_MUTATION",
        "TELEGRAM_MUTATION",
        "DISCORD_MUTATION",
        "WHATSAPP_MUTATION",
        "MODEL_PROVIDER_CHANGE",
        "NEW_ORCHESTRATOR",
        "NEW_VECTOR_DB",
        "NEW_KNOWLEDGE_BASE",
        "PUBLIC_LISTENER",
        "SECOND_SOURCE_OF_TRUTH",
    }
    for f in forbidden:
        if f in forbidden_flags:
            reasons.append(
                f"skill demands forbidden capability {f}; "
                "external skills may NEVER demand these"
            )

    # Prompt-injection surface gate
    pis = str(raw.get("prompt_injection_surface", "none")).lower()
    if pis in ("high", "critical"):
        if mode in (Mode.ACTIVE, Mode.SHADOW):
            reasons.append(
                f"prompt_injection_surface={pis} is incompatible with "
                f"mode={mode.value}"
            )

    # Dependency install gate
    dep = str(raw.get("dependency_install", "none")).lower()
    if dep not in ("none", "isolated_test_only"):
        reasons.append(
            "dependency_install must be 'none' or 'isolated_test_only'; "
            f"got {dep!r}"
        )

    return (len(reasons) == 0), reasons


# ---------- Loader ---------------------------------------------------------


def load_registry(path: Path) -> List[SkillEntry]:
    """Load all entries from a YAML registry file.

    Entries that fail validation are skipped with a recorded reason; the
    caller can inspect via `last_validation_errors`. Empty list is a valid
    SCAFFOLD state (no external skills registered yet).
    """
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return []
    data = yaml.safe_load(text)
    if not isinstance(data, list):
        raise ValueError(
            f"registry must be a YAML list of entries; got {type(data).__name__}"
        )

    entries: List[SkillEntry] = []
    for i, raw in enumerate(data):
        ok, reasons = validate_entry(raw or {})
        if not ok:
            # In SCAFFOLD state we don't yet have a logger; raise with
            # structured information so the caller can decide.
            raise ValueError(
                f"registry entry #{i} (id={raw.get('id')!r}) failed intake: "
                + "; ".join(reasons)
            )
        entries.append(
            SkillEntry(
                id=str(raw["id"]),
                upstream_repo=str(raw["upstream_repo"]),
                upstream_commit=str(raw["upstream_commit"]),
                upstream_license=raw.get("upstream_license"),
                mode=Mode(str(raw["mode"])),
                capabilities=list(raw.get("capabilities") or []),
                network_access=bool(raw.get("network_access", False)),
                filesystem_read=list(raw.get("filesystem_read") or []),
                filesystem_write=list(raw.get("filesystem_write") or []),
                shell_exec=bool(raw.get("shell_exec", False)),
                subagent_spawn=bool(raw.get("subagent_spawn", False)),
                prompt_injection_surface=str(
                    raw.get("prompt_injection_surface", "none")
                ),
                dependency_install=str(raw.get("dependency_install", "none")),
                conflicts=list(raw.get("conflicts") or []),
                allowed_projects=list(raw.get("allowed_projects") or ["*"]),
                activation_scope=str(raw.get("activation_scope", "on_demand")),
                rollback=str(raw.get("rollback", "")),
                evidence=str(raw.get("evidence", "")),
            )
        )
    return entries


# ---------- Helpers --------------------------------------------------------


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def find_skill(entries: List[SkillEntry], skill_id: str) -> Optional[SkillEntry]:
    for e in entries:
        if e.id == skill_id:
            return e
    return None
