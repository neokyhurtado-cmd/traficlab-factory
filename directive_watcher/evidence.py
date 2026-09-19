"""Visual evidence contract.

Per #18, the watcher defines the convention for future visual reviews:

    evidence/visual/<execution_id>/
        before/
        after/
        manifest.json
        notes.md

This module owns the directory creation and the manifest writer. The
caller (a future task that has UI impact) is responsible for populating
``before/`` and ``after/``; the watcher only ensures the skeleton exists
when it claims a directive and pins the absolute path into the RESULT
post so Astra can find it.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class EvidenceManifest:
    execution_id: str
    directive_id: str
    source_comment_id: int
    created_at: int = field(default_factory=lambda: int(time.time()))
    before_dir: str = ""
    after_dir: str = ""
    notes: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)


def evidence_visual_root(base_dir: str | Path) -> Path:
    """Return ``<base_dir>/evidence/visual``.

    ``base_dir`` is the watcher's working directory; the canonical evidence
    layout lives under ``<base>/evidence/visual/<execution_id>/``.
    """
    return Path(base_dir) / "evidence" / "visual"


def prepare_execution_dir(
    base_dir: str | Path,
    execution_id: str,
    directive_id: str,
    source_comment_id: int,
) -> Path:
    """Create ``<base_dir>/evidence/visual/<execution_id>/`` with the canonical
    subdirectories and a starting manifest.json. Returns the absolute path."""
    exec_dir = evidence_visual_root(base_dir) / execution_id
    (exec_dir / "before").mkdir(parents=True, exist_ok=True)
    (exec_dir / "after").mkdir(parents=True, exist_ok=True)
    manifest = EvidenceManifest(
        execution_id=execution_id,
        directive_id=directive_id,
        source_comment_id=source_comment_id,
        before_dir=str(exec_dir / "before"),
        after_dir=str(exec_dir / "after"),
    )
    (exec_dir / "manifest.json").write_text(manifest.to_json(), encoding="utf-8")
    notes_path = exec_dir / "notes.md"
    if not notes_path.exists():
        notes_path.write_text(
            f"# Evidence notes — execution {execution_id}\n\n"
            f"Directive: `{directive_id}` (source comment {source_comment_id})\n\n"
            f"Populate `before/` and `after/` with screenshots / artifacts and\n"
            f"annotate them here. Hermes will reference this directory in the\n"
            f"`[HERMES_RESULT:v1]` post.\n",
            encoding="utf-8",
        )
    return exec_dir.resolve()


def read_manifest(base_dir: str | Path, execution_id: str) -> dict[str, Any] | None:
    path = evidence_visual_root(base_dir) / execution_id / "manifest.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
