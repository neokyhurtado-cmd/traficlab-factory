"""Durable sidecar state for the GitHub Directive Watcher.

The store is a small SQLite database kept SEPARATE from any product
canonical DB. Per #18:

  - last_seen_comment_id
  - processed_directive_ids
  - comment_id → directive_id → execution_id
  - last_processed_head
  - ack_status
  - result_status
  - processed_at

Concurrency: every claim is wrapped in an IMMEDIATE transaction with
``BEGIN IMMEDIATE`` semantics. SQLite serialises writes; combined with the
UNIQUE constraint on ``directive_id``, two concurrent watcher instances
cannot both claim the same directive.
"""
from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS directive_seen (
    comment_id      INTEGER PRIMARY KEY,
    directive_id    TEXT,
    body_sha256     TEXT NOT NULL,
    first_seen_at   INTEGER NOT NULL,
    last_seen_at    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS directive_processed (
    directive_id    TEXT PRIMARY KEY,
    source_comment_id INTEGER NOT NULL,
    execution_id    TEXT NOT NULL UNIQUE,
    head_before     TEXT,
    head_after      TEXT,
    ack_status      TEXT NOT NULL,
    result_status   TEXT,
    processed_at    INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL,
    last_body_sha256 TEXT NOT NULL,
    body_edited     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS watcher_run (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      INTEGER NOT NULL,
    finished_at     INTEGER,
    status          TEXT NOT NULL,
    notes           TEXT
);
"""

ACK_CLAIMED = "CLAIMED"
RESULT_READY = "READY_FOR_ASTRA_REAUDIT"
RESULT_BLOCKED = "BLOCKED_EXTERNAL_REAL"
RESULT_SCIENTIFIC = "SCIENTIFIC_DECISION_REQUIRED"
RESULT_HUMAN_GO = "HUMAN_GO_REAL_REQUIRED"

RESULT_STATUSES = frozenset({
    RESULT_READY,
    RESULT_BLOCKED,
    RESULT_SCIENTIFIC,
    RESULT_HUMAN_GO,
})


@dataclass(frozen=True)
class Claim:
    """Record returned when a watcher instance successfully claims a directive."""

    execution_id: str
    directive_id: str
    source_comment_id: int
    head_before: Optional[str]


class AlreadyProcessed(Exception):
    """Raised when claim() is called for a directive that is already finalised
    or already claimed by another instance."""


class DirectiveEditedAfterAck(Exception):
    """Raised when the same comment_id now has a different body_sha256 than
    the one recorded at ACK time. The watcher must NOT silently re-execute
    the directive — it must mark DIRECTIVE_CHANGED_AFTER_ACK and require a
    new DIRECTIVE_ID."""


class SidecarStore:
    """Thin wrapper around a SQLite file. Thread-safe via a re-entrant lock."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        # check_same_thread=False so two threads in the same process can
        # share a connection; we still serialise writes via the lock.
        self._conn = sqlite3.connect(
            str(self._db_path),
            isolation_level=None,  # we manage txns explicitly
            check_same_thread=False,
        )
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)

    @contextmanager
    def _txn(self) -> Iterator[sqlite3.Connection]:
        """Serialised immediate transaction. SQLite serialises writes; the
        lock keeps readers consistent across threads in this process."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    # --- seen tracking ------------------------------------------------------

    def mark_seen(self, comment_id: int, body_sha256: str) -> bool:
        """Record that we have observed ``comment_id``. Returns True if the
        observation was NEW, False if it was already known.

        Pure observation; does NOT mark the directive as processed.
        """
        now = int(time.time())
        with self._txn() as c:
            row = c.execute(
                "SELECT body_sha256 FROM directive_seen WHERE comment_id = ?",
                (comment_id,),
            ).fetchone()
            if row is None:
                c.execute(
                    "INSERT INTO directive_seen "
                    "(comment_id, body_sha256, first_seen_at, last_seen_at) "
                    "VALUES (?, ?, ?, ?)",
                    (comment_id, body_sha256, now, now),
                )
                return True
            if row[0] != body_sha256:
                c.execute(
                    "UPDATE directive_seen SET body_sha256 = ?, last_seen_at = ? "
                    "WHERE comment_id = ?",
                    (body_sha256, now, comment_id),
                )
            else:
                c.execute(
                    "UPDATE directive_seen SET last_seen_at = ? "
                    "WHERE comment_id = ?",
                    (now, comment_id),
                )
            return False

    def get_seen_body_sha(self, comment_id: int) -> Optional[str]:
        with self._lock:
            row = self._conn.execute(
                "SELECT body_sha256 FROM directive_seen WHERE comment_id = ?",
                (comment_id,),
            ).fetchone()
            return row[0] if row else None

    def last_seen_comment_id(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(comment_id), 0) FROM directive_seen"
            ).fetchone()
            return int(row[0]) if row else 0

    # --- claim / idempotency ----------------------------------------------

    def claim(
        self,
        directive_id: str,
        source_comment_id: int,
        body_sha256: str,
        head_before: Optional[str],
    ) -> Claim:
        """Atomically claim a directive for execution.

        - Raises ``AlreadyProcessed`` if the directive is already finalised
          with a result.
        - Raises ``AlreadyProcessed`` if the directive is currently CLAIMED
          (another instance won the race) — the caller should NOT retry.
        - Returns a ``Claim`` on success. The caller must post the ACK and
          then call ``record_result`` to finalise.

        Exactly-once claim semantics: the UNIQUE constraint on
        ``directive_id`` makes a second claim impossible.
        """
        existing = self._fetch_processed(directive_id)
        if existing is not None:
            raise AlreadyProcessed(
                f"directive {directive_id} already processed "
                f"(status={existing['result_status'] or existing['ack_status']})"
            )
        execution_id = self._mint_execution_id(directive_id, source_comment_id)
        now = int(time.time())
        with self._txn() as c:
            try:
                c.execute(
                    "INSERT INTO directive_processed "
                    "(directive_id, source_comment_id, execution_id, "
                    " head_before, ack_status, processed_at, updated_at, "
                    " last_body_sha256, body_edited) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
                    (
                        directive_id,
                        source_comment_id,
                        execution_id,
                        head_before,
                        ACK_CLAIMED,
                        now,
                        now,
                        body_sha256,
                    ),
                )
            except sqlite3.IntegrityError as e:
                raise AlreadyProcessed(
                    f"directive {directive_id} claim lost the race: {e}"
                ) from e
        return Claim(
            execution_id=execution_id,
            directive_id=directive_id,
            source_comment_id=source_comment_id,
            head_before=head_before,
        )

    def record_result(
        self,
        directive_id: str,
        result_status: str,
        head_after: Optional[str],
    ) -> None:
        """Finalise a directive. The caller must already hold a claim."""
        if result_status not in RESULT_STATUSES:
            raise ValueError(f"unknown result status: {result_status!r}")
        now = int(time.time())
        with self._txn() as c:
            cur = c.execute(
                "UPDATE directive_processed "
                "SET result_status = ?, head_after = ?, updated_at = ? "
                "WHERE directive_id = ? AND result_status IS NULL",
                (result_status, head_after, now, directive_id),
            )
            if cur.rowcount == 0:
                raise AlreadyProcessed(
                    f"directive {directive_id} has no open claim"
                )

    def detect_body_edit_after_ack(self, directive_id: str, body_sha256: str) -> bool:
        """Returns True if the comment body SHA256 has changed since the ACK
        was issued for this directive. The watcher must NOT silently
        re-execute in that case — it must mark DIRECTIVE_CHANGED_AFTER_ACK
        and require a new DIRECTIVE_ID."""
        with self._txn() as c:
            row = c.execute(
                "SELECT last_body_sha256, body_edited, result_status "
                "FROM directive_processed WHERE directive_id = ?",
                (directive_id,),
            ).fetchone()
            if row is None:
                return False
            recorded_sha, body_edited, _ = row
            if recorded_sha == body_sha256:
                return False
            # Body changed. Flip the flag once (idempotent).
            if not body_edited:
                c.execute(
                    "UPDATE directive_processed "
                    "SET body_edited = 1, updated_at = ? "
                    "WHERE directive_id = ?",
                    (int(time.time()), directive_id),
                )
            return True

    def get_processed(self, directive_id: str) -> Optional[dict]:
        """Return a snapshot of the directive_processed row, or None."""
        row = self._fetch_processed(directive_id)
        return row

    def _fetch_processed(self, directive_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT directive_id, source_comment_id, execution_id, "
                "       head_before, head_after, ack_status, result_status, "
                "       processed_at, updated_at, last_body_sha256, body_edited "
                "FROM directive_processed WHERE directive_id = ?",
                (directive_id,),
            ).fetchone()
        if row is None:
            return None
        keys = (
            "directive_id", "source_comment_id", "execution_id",
            "head_before", "head_after", "ack_status", "result_status",
            "processed_at", "updated_at", "last_body_sha256", "body_edited",
        )
        return dict(zip(keys, row))

    def list_finalised(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT directive_id, source_comment_id, execution_id, "
                "       ack_status, result_status, processed_at, updated_at "
                "FROM directive_processed WHERE result_status IS NOT NULL "
                "ORDER BY updated_at DESC"
            ).fetchall()
        keys = (
            "directive_id", "source_comment_id", "execution_id",
            "ack_status", "result_status", "processed_at", "updated_at",
        )
        return [dict(zip(keys, r)) for r in rows]

    def claim_pending(self) -> list[dict]:
        """Return directives that have been claimed but not yet finalised.

        Used by the recovery / restart code path to detect mid-flight claims
        that need surfacing.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT directive_id, source_comment_id, execution_id, "
                "       ack_status, processed_at "
                "FROM directive_processed WHERE result_status IS NULL "
                "ORDER BY processed_at ASC"
            ).fetchall()
        keys = (
            "directive_id", "source_comment_id", "execution_id",
            "ack_status", "processed_at",
        )
        return [dict(zip(keys, r)) for r in rows]

    # --- run history (small ring buffer for observability) -----------------

    def record_run_start(self, notes: str = "") -> int:
        with self._txn() as c:
            cur = c.execute(
                "INSERT INTO watcher_run (started_at, status, notes) "
                "VALUES (?, 'running', ?)",
                (int(time.time()), notes),
            )
            return int(cur.lastrowid)

    def record_run_finish(self, run_id: int, status: str, notes: str = "") -> None:
        with self._txn() as c:
            c.execute(
                "UPDATE watcher_run "
                "SET finished_at = ?, status = ?, notes = ? "
                "WHERE id = ?",
                (int(time.time()), status, notes, run_id),
            )

    def last_runs(self, limit: int = 5) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, started_at, finished_at, status, notes "
                "FROM watcher_run ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        keys = ("id", "started_at", "finished_at", "status", "notes")
        return [dict(zip(keys, r)) for r in rows]

    # --- internals ---------------------------------------------------------

    @staticmethod
    def _mint_execution_id(directive_id: str, source_comment_id: int) -> str:
        suffix = uuid.uuid4().hex[:8]
        return f"exec-{source_comment_id}-{suffix}"

    def close(self) -> None:
        with self._lock:
            self._conn.close()
