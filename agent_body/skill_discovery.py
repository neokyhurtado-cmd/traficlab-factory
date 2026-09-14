"""BODY-1 skill discoverability helper.

The internal-consult skill lives at .hermes/skills/internal-consult/SKILL.md
(added by #31). A fresh worker must be able to find it WITHOUT a hardcoded
absolute path. This module does what hermes skills_list / skill_view would
do: walk from the workspace root, locate .hermes/skills/<name>/SKILL.md,
parse the YAML frontmatter, and return a typed handle.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import yaml


@dataclass(frozen=True)
class DiscoveredSkill:
    name: str
    path: Path
    frontmatter: dict

    @property
    def exists(self) -> bool:
        return self.path.exists()


def discover_skill(name: str, workspace_root: Optional[Path] = None) -> Optional[DiscoveredSkill]:
    """Find a skill by name from the workspace root, walking .hermes/skills/.

    Mirrors the convention Hermes uses: skills live under
    .hermes/skills/<name>/SKILL.md with YAML frontmatter.
    """
    root = Path(workspace_root or Path.cwd()).resolve()
    candidate = root / ".hermes" / "skills" / name / "SKILL.md"
    if not candidate.exists():
        # Walk upward — useful when the caller is inside a subdirectory.
        cur = Path.cwd().resolve()
        while cur != cur.parent:
            cand = cur / ".hermes" / "skills" / name / "SKILL.md"
            if cand.exists():
                candidate = cand
                break
            cur = cur.parent
    if not candidate.exists():
        return None
    text = candidate.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    # Parse the frontmatter
    end = text.find("---", 3)
    if end < 0:
        return None
    fm = yaml.safe_load(text[3:end])
    return DiscoveredSkill(name=str(fm.get("name", name)), path=candidate, frontmatter=fm)


def list_skill_names(workspace_root: Optional[Path] = None) -> List[str]:
    """List every skill discoverable under .hermes/skills/."""
    root = Path(workspace_root or Path.cwd()).resolve()
    skills_dir = root / ".hermes" / "skills"
    if not skills_dir.exists():
        return []
    out = []
    for entry in sorted(skills_dir.iterdir()):
        if (entry / "SKILL.md").exists():
            out.append(entry.name)
    return out
