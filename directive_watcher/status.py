"""Status surface — a small read-only JSON snapshot for War Room integration.

Per #18 the watcher should expose a machine-readable state object. We keep
this dependency-free so the orchestrator profile's existing scheduler can
just point an HTTP probe at the resulting file (or read it directly from
disk) without any new public exposure.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class WatcherStatus:
    watcher_status: str  # "healthy" | "degraded" | "unknown"
    last_poll_at: Optional[int] = None
    last_seen_comment_id: int = 0
    active_execution: Optional[str] = None
    queue_depth: int = 0
    last_result: Optional[str] = None  # directive_id of last finalised directive
    last_result_status: Optional[str] = None
    last_run_status: Optional[str] = None
    last_run_finished_at: Optional[int] = None

    def to_json(self) -> str:
        import json

        return json.dumps(asdict(self), indent=2, sort_keys=True)


def write_status(path: str | Path, status: WatcherStatus) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(status.to_json(), encoding="utf-8")


def read_status(path: str | Path) -> WatcherStatus:
    p = Path(path)
    if not p.exists():
        return WatcherStatus(watcher_status="unknown")
    import json

    data = json.loads(p.read_text(encoding="utf-8"))
    return WatcherStatus(**data)
