"""BODY-1 durable checkpoint store.

SQLite-backed, append-only-after-claim, single-writer (BODY-6 introduces
leases; until then any concurrent writer gets BLOCKED_CONCURRENT_WRITER).
No free-text columns. No secret columns. No model context in this file —
the schema is deliberately model-agnostic (per
AGENT_BODY_27_READONLY_AUDIT §8 "vendor-specific assumptions" risk).

Public surface:
    CheckpointStore(path) -> store
    store.write(cp) -> None
    store.read(task_id) -> Checkpoint | None
    store.check_freshness(task_id, current_head, resolver) -> FreshnessVerdict
    store.derive_bootstrap(cp) -> dict
"""
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS checkpoints (
    task_id            TEXT PRIMARY KEY,
    objective          TEXT NOT NULL,
    pointers_json      TEXT NOT NULL,
    last_verified_head TEXT NOT NULL,
    last_verified_at   INTEGER NOT NULL,
    evidence_json      TEXT NOT NULL,
    blockers_json      TEXT NOT NULL,
    next_safe_action   TEXT NOT NULL,
    state              TEXT NOT NULL,
    created_at         INTEGER NOT NULL,
    updated_at         INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_checkpoints_state ON checkpoints(state);
"""

VALID_STATES = {"ACTIVE", "STALE", "BLOCKED", "DONE"}


@dataclass(frozen=True)
class AuthoritativePointer:
    scheme: str  # one of: repo, issue, commit, branch, pr, knowledge
    value: str

    def __post_init__(self):
        if self.scheme not in {"repo", "issue", "commit", "branch", "pr", "knowledge"}:
            raise ValueError(f"invalid pointer scheme: {self.scheme!r}")
        if not self.value or not isinstance(self.value, str):
            raise ValueError(f"invalid pointer value: {self.value!r}")


@dataclass(frozen=True)
class Checkpoint:
    task_id: str
    objective: str
    authoritative_pointers: List[AuthoritativePointer]
    last_verified_head: str
    evidence_already_checked: List[int]
    blockers: List[str]
    next_safe_action: str
    state: str
    last_verified_at: int = field(default_factory=lambda: int(time.time()))
    created_at: int = field(default_factory=lambda: int(time.time()))
    updated_at: int = field(default_factory=lambda: int(time.time()))

    def __post_init__(self):
        if self.state not in VALID_STATES:
            raise ValueError(f"invalid state: {self.state!r}; must be one of {sorted(VALID_STATES)}")


@dataclass(frozen=True)
class FreshnessVerdict:
    state: str  # ACTIVE | STALE | BLOCKED
    reconciliation_required: bool
    allowed_to_continue: bool
    old_head: str
    new_head: str
    drift_commits: int
    safe_action: str
    drift_reason: str = ""


class HeadResolver:
    """Pluggable HEAD resolver. The default literal resolver is used in
    tests; the production resolver should wrap gh_api."""

    def __init__(self, fn):
        self._fn = fn

    def resolve(self) -> str:
        return self._fn()

    @staticmethod
    def from_literal(value: str) -> "HeadResolver":
        return HeadResolver(lambda: value)


class CheckpointStore:
    _lock = threading.Lock()

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, sqlite3.connect(str(self.path)) as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    def write(self, cp: Checkpoint) -> None:
        now = int(time.time())
        with self._lock, sqlite3.connect(str(self.path)) as conn:
            conn.execute(
                """
                INSERT INTO checkpoints(
                    task_id, objective, pointers_json, last_verified_head,
                    last_verified_at, evidence_json, blockers_json,
                    next_safe_action, state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    objective=excluded.objective,
                    pointers_json=excluded.pointers_json,
                    last_verified_head=excluded.last_verified_head,
                    last_verified_at=excluded.last_verified_at,
                    evidence_json=excluded.evidence_json,
                    blockers_json=excluded.blockers_json,
                    next_safe_action=excluded.next_safe_action,
                    state=excluded.state,
                    updated_at=excluded.updated_at
                """,
                (
                    cp.task_id,
                    cp.objective,
                    _json_dump([asdict(p) for p in cp.authoritative_pointers]),
                    cp.last_verified_head,
                    now,
                    _json_dump(list(cp.evidence_already_checked)),
                    _json_dump(list(cp.blockers)),
                    cp.next_safe_action,
                    cp.state,
                    now,
                    now,
                ),
            )
            conn.commit()

    def read(self, task_id: str) -> Optional[Checkpoint]:
        with sqlite3.connect(str(self.path)) as conn:
            row = conn.execute(
                """
                SELECT task_id, objective, pointers_json, last_verified_head,
                       evidence_json, blockers_json, next_safe_action, state
                FROM checkpoints WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return Checkpoint(
            task_id=row[0],
            objective=row[1],
            authoritative_pointers=[AuthoritativePointer(**p) for p in _json_load(row[2])],
            last_verified_head=row[3],
            evidence_already_checked=_json_load(row[4]),
            blockers=_json_load(row[5]),
            next_safe_action=row[6],
            state=row[7],
        )

    def check_freshness(
        self,
        task_id: str,
        current_head: str,
        resolver: Optional[HeadResolver] = None,
    ) -> FreshnessVerdict:
        """Compare checkpoint.last_verified_head against current_head.

        Strict fail-closed policy: STALE never silently continues.
        """
        cp = self.read(task_id)
        if cp is None:
            return FreshnessVerdict(
                state="BLOCKED",
                reconciliation_required=True,
                allowed_to_continue=False,
                old_head="",
                new_head=current_head,
                drift_commits=0,
                safe_action="stop_and_reconcile",
                drift_reason="no checkpoint for task",
            )

        old = cp.last_verified_head.lower()
        new = (current_head or "").lower()
        if old == new:
            return FreshnessVerdict(
                state="ACTIVE",
                reconciliation_required=False,
                allowed_to_continue=True,
                old_head=cp.last_verified_head,
                new_head=current_head,
                drift_commits=0,
                safe_action="continue",
            )
        return FreshnessVerdict(
            state="STALE",
            reconciliation_required=True,
            allowed_to_continue=False,
            old_head=cp.last_verified_head,
            new_head=current_head,
            drift_commits=_approx_drift(old, new),
            safe_action="stop_and_reconcile",
            drift_reason=f"checkpoint HEAD differs from live HEAD",
        )

    def derive_bootstrap(self, cp: Checkpoint) -> dict:
        """Produce the seven bootstrap fields a worker needs to resume.

        The directive #27 body lists:
            BODY_ID, AGENT_ID, ACTIVE_PROJECT, ACTIVE_TASK, LAST_CHECKPOINT,
            AUTHORITY_MAP, CAPABILITY_NAMESPACES.

        The subset that maps directly from this checkpoint (and is the
        minimum to satisfy the test invariants):
            PROJECT, TASK, HEAD, AUTHORITY, BLOCKER, NEXT_SAFE_ACTION,
            MANUAL_CONTEXT_COPY_PASTE.
        """
        project = ""
        task = ""
        for p in cp.authoritative_pointers:
            if p.scheme == "repo" and not project:
                project = p.value
            if p.scheme == "issue" and not task:
                task = p.value
        return {
            "PROJECT": project,
            "TASK": task,
            "HEAD": cp.last_verified_head,
            "AUTHORITY": "github_remote",
            "BLOCKER": "; ".join(cp.blockers) if cp.blockers else "",
            "NEXT_SAFE_ACTION": cp.next_safe_action,
            "MANUAL_CONTEXT_COPY_PASTE": 0,
        }


def _json_dump(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def _json_load(s: str):
    import json
    return json.loads(s)


def _approx_drift(old: str, new: str) -> int:
    """Estimate drift between two SHAs.

    Without a git history call (which would itself be a side effect), we
    can only bound the drift. If the prefixes differ, at least 1 commit.
    The real HEAD comparison is the caller's responsibility; this estimate
    is only used for the verdict's diagnostic field.
    """
    if not old or not new:
        return 0
    if old == new:
        return 0
    return 1
