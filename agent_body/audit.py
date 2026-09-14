"""BODY-1 audit event store.

Per AGENT_BODY_27_READONLY_AUDIT §5.5: audit events are STRUCTURED ONLY.
No free-text body. No prompt content. No chain-of-thought. No PII. No
secrets. The dataclass intentionally has NO `body_text` / `body` field —
construction of an AuditEvent with such a kwarg raises TypeError, which
is the executable enforcement of the schema invariant.

Public surface:
    AuditStore(path) -> store
    store.append(event) -> None
    store.all_events(task_id=...) -> list[AuditEvent]
"""
from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_events (
    event_id        TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL,
    action          TEXT NOT NULL,
    capability_used TEXT NOT NULL,
    source_evidence_pointers TEXT NOT NULL,
    outcome         TEXT NOT NULL,
    timestamp       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_task ON audit_events(task_id);
"""


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    task_id: str
    action: str
    capability_used: str
    source_evidence_pointers: List[str]
    outcome: str
    timestamp: int = field(default_factory=lambda: int(time.time()))


class AuditStore:
    _lock = threading.Lock()

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, sqlite3.connect(str(self.path)) as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    def append(self, ev: AuditEvent) -> None:
        with self._lock, sqlite3.connect(str(self.path)) as conn:
            conn.execute(
                """
                INSERT INTO audit_events(
                    event_id, task_id, action, capability_used,
                    source_evidence_pointers, outcome, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ev.event_id,
                    ev.task_id,
                    ev.action,
                    ev.capability_used,
                    ";".join(ev.source_evidence_pointers),
                    ev.outcome,
                    ev.timestamp,
                ),
            )
            conn.commit()

    def all_events(self, task_id: Optional[str] = None) -> List[AuditEvent]:
        with sqlite3.connect(str(self.path)) as conn:
            if task_id is None:
                rows = conn.execute(
                    "SELECT event_id, task_id, action, capability_used, "
                    "source_evidence_pointers, outcome, timestamp "
                    "FROM audit_events ORDER BY timestamp ASC"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT event_id, task_id, action, capability_used, "
                    "source_evidence_pointers, outcome, timestamp "
                    "FROM audit_events WHERE task_id = ? ORDER BY timestamp ASC",
                    (task_id,),
                ).fetchall()
        return [
            AuditEvent(
                event_id=r[0],
                task_id=r[1],
                action=r[2],
                capability_used=r[3],
                source_evidence_pointers=r[4].split(";") if r[4] else [],
                outcome=r[5],
                timestamp=r[6],
            )
            for r in rows
        ]


def new_event(
    task_id: str,
    action: str,
    capability_used: str,
    source_evidence_pointers: List[str],
    outcome: str,
) -> AuditEvent:
    return AuditEvent(
        event_id=str(uuid.uuid4()),
        task_id=task_id,
        action=action,
        capability_used=capability_used,
        source_evidence_pointers=source_evidence_pointers,
        outcome=outcome,
    )
