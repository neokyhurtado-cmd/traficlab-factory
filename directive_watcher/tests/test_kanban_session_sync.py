"""Tests for the kanban → sessions.jsonl sync module (AUTONOMY-V2).

The orchestrator dispatcher (orch_dispatch.py) mints a SessionRecord with
state=DISPATCHED when it wakes a session, but it never observes the
downstream kanban progress events. As a result, sessions stay stuck at
DISPATCHED forever even when the task has finished.

This module tests the seam that closes the gap:

  1. ``_find_directive_id_for_session`` looks up the directive_id for a
     given session_id in the JSONL sidecar.
  2. ``_find_kanban_event_for_directive`` finds the latest terminal
     task_event (completed/failed/spawned) for a directive in the kanban
     DB by joining on tasks.idempotency_key.
  3. ``sync_session_from_kanban_event`` mutates the SessionRecord through
     ``OrchestratorDispatcher.update_session`` to reflect the kanban
     state.

All tests use a fake kanban DB (sqlite3 in tmp_path) — we never touch the
production ``HERMES_HOME/kanban.db`` here. The kanban DB schema is
re-implemented from the hermes-agent ``kanban_db.py`` contract; we do NOT
import hermes_cli.kanban_db (separation between repos).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest import mock

import pytest

from directive_watcher.directive_parser import parse_directive
from directive_watcher.kanban_session_sync import (
    _find_directive_id_for_session,
    _find_kanban_event_for_directive,
    sync_session_from_kanban_event,
)
from directive_watcher.orch_dispatch import (
    DispatchRequest,
    OrchestratorDispatcher,
    SESSION_STATE_DISPATCHED,
    SESSION_STATE_DONE,
    SESSION_STATE_FAILED,
    SESSION_STATE_RUNNING,
)


# ---------- helpers ---------------------------------------------------------


@pytest.fixture
def routing_table(tmp_path: Path) -> Path:
    p = tmp_path / "routing.yaml"
    p.write_text(
        "routes:\n"
        "  - repo: neokyhurtado-cmd/traficlab-factory\n"
        "    product: ORCHESTRATION\n"
        "    assignee: hermes-director\n"
        "    capabilities: [write]\n"
        "    max_runtime_seconds: 3600\n",
        encoding="utf-8",
    )
    return p


def _directive_body(directive_id: str = "d-sync-001") -> str:
    return (
        "[ASTRA_DIRECTIVE:v1]\n"
        "ACTION = CONTINUE\n"
        "REPOSITORY = neokyhurtado-cmd/traficlab-factory\n"
        "ISSUE = 18\n"
        "TARGET_BRANCH = AUTO_FROM_ISSUE_CONTEXT\n"
        "EXPECTED_HEAD = NONE\n"
        "SCOPE = test scope\n"
        "AUTO_NEXT_SAFE_GATE = YES\n"
        "REQUIRES_HUMAN_GO_REAL = NO\n"
        f"DIRECTIVE_ID = {directive_id}\n"
    )


def _make_dispatcher(tmp_path: Path, routing_table: Path) -> OrchestratorDispatcher:
    return OrchestratorDispatcher(
        session_log=str(tmp_path / "sessions.jsonl"),
        routing_table_path=str(routing_table),
    )


# Mirrors the hermes_cli.kanban_db schema (idempotency_key lives in tasks,
# event kinds live in task_events). We re-implement it here so tests stay
# hermetic and don't import hermes_cli.
KANBAN_SCHEMA = """
CREATE TABLE tasks (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    body            TEXT,
    assignee        TEXT,
    status          TEXT NOT NULL,
    created_at      INTEGER NOT NULL,
    idempotency_key TEXT
);
CREATE TABLE task_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id    TEXT NOT NULL,
    run_id     INTEGER,
    kind       TEXT NOT NULL,
    payload    TEXT,
    created_at INTEGER NOT NULL
);
CREATE TABLE task_attachments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL,
    filename    TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    content_type TEXT,
    size        INTEGER NOT NULL,
    uploaded_by TEXT,
    created_at  INTEGER NOT NULL
);
"""


def _seed_kanban_db(db_path: Path, *, directive_id: str, task_id: str,
                    events: list[tuple[str, dict]]) -> None:
    """Create a fake kanban DB with one task and a sequence of events.

    ``events`` is a list of (kind, payload) tuples written in order; each
    gets a monotonically increasing created_at so tests can assert ordering.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        conn.executescript(KANBAN_SCHEMA)
        conn.execute(
            "INSERT INTO tasks (id, title, body, assignee, status, "
            "created_at, idempotency_key) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (task_id, "t", "b", "hermes-director", "in_progress",
             1_700_000_000, f"directive:{directive_id}"),
        )
        for i, (kind, payload) in enumerate(events):
            conn.execute(
                "INSERT INTO task_events (task_id, run_id, kind, payload, "
                "created_at) VALUES (?, NULL, ?, ?, ?)",
                (task_id, kind, json.dumps(payload),
                 1_700_000_000 + i + 1),
            )
        conn.commit()


# ---------- _find_directive_id_for_session ----------------------------------


def test_find_directive_id_for_session_returns_id(tmp_path: Path,
                                                  routing_table: Path):
    dispatcher = _make_dispatcher(tmp_path, routing_table)
    d = parse_directive(_directive_body(directive_id="d-lookup-1"))

    fake_kanban = '{"id": "t_lookup", "created_at": 1}'
    with mock.patch(
        "directive_watcher.kanban_primitive.subprocess.run",
        return_value=mock.Mock(returncode=0, stdout=fake_kanban, stderr=""),
    ):
        result = dispatcher.dispatch(
            DispatchRequest(directive=d, source_comment_id=1,
                            execution_id="exec-lookup"),
        )

    directive_id = _find_directive_id_for_session(
        result.session_id,
        session_log=str(tmp_path / "sessions.jsonl"),
    )
    assert directive_id == "d-lookup-1"


def test_find_directive_id_for_session_missing(tmp_path: Path):
    assert _find_directive_id_for_session(
        "sess-does-not-exist",
        session_log=str(tmp_path / "sessions.jsonl"),
    ) is None


# ---------- _find_kanban_event_for_directive -------------------------------


def test_find_kanban_event_completed(tmp_path: Path):
    kanban_db = tmp_path / "kanban.db"
    _seed_kanban_db(
        kanban_db,
        directive_id="d-evt-1",
        task_id="t_evt_1",
        events=[
            ("spawned", {"worker_pid": 1234}),
            ("completed", {"outcome": "success",
                           "tests_summary": "12/12 passed",
                           "evidence_uri": "/ev/d-evt-1"}),
        ],
    )

    evt = _find_kanban_event_for_directive(
        "d-evt-1", kanban_db_path=str(kanban_db),
    )
    assert evt is not None
    assert evt["kind"] == "completed"
    assert evt["payload"]["tests_summary"] == "12/12 passed"


def test_find_kanban_event_failed(tmp_path: Path):
    kanban_db = tmp_path / "kanban.db"
    _seed_kanban_db(
        kanban_db,
        directive_id="d-evt-fail",
        task_id="t_evt_fail",
        events=[
            ("spawned", {"worker_pid": 1}),
            ("failed", {"outcome": "failed",
                        "error": "boom",
                        "evidence_uri": "/ev/d-evt-fail"}),
        ],
    )

    evt = _find_kanban_event_for_directive(
        "d-evt-fail", kanban_db_path=str(kanban_db),
    )
    assert evt is not None
    assert evt["kind"] == "failed"
    assert evt["payload"]["error"] == "boom"


def test_find_kanban_event_spawned_only(tmp_path: Path):
    kanban_db = tmp_path / "kanban.db"
    _seed_kanban_db(
        kanban_db,
        directive_id="d-evt-spawned",
        task_id="t_evt_spawned",
        events=[("spawned", {"worker_pid": 99})],
    )
    evt = _find_kanban_event_for_directive(
        "d-evt-spawned", kanban_db_path=str(kanban_db),
    )
    assert evt is not None
    assert evt["kind"] == "spawned"
    assert evt["payload"]["worker_pid"] == 99


def test_find_kanban_event_no_match(tmp_path: Path):
    kanban_db = tmp_path / "kanban.db"
    _seed_kanban_db(
        kanban_db,
        directive_id="d-evt-other",
        task_id="t_evt_other",
        events=[("completed", {"outcome": "success"})],
    )
    evt = _find_kanban_event_for_directive(
        "d-evt-nope", kanban_db_path=str(kanban_db),
    )
    assert evt is None


def test_find_kanban_event_picks_latest_terminal(tmp_path: Path):
    """If a directive has been re-run (spawned → failed → completed), the
    sync must use the LATEST terminal event."""
    kanban_db = tmp_path / "kanban.db"
    _seed_kanban_db(
        kanban_db,
        directive_id="d-evt-retry",
        task_id="t_evt_retry",
        events=[
            ("spawned", {"worker_pid": 1}),
            ("failed", {"outcome": "failed", "error": "transient"}),
            ("spawned", {"worker_pid": 2}),
            ("completed", {"outcome": "success",
                           "tests_summary": "OK"}),
        ],
    )
    evt = _find_kanban_event_for_directive(
        "d-evt-retry", kanban_db_path=str(kanban_db),
    )
    assert evt is not None
    assert evt["kind"] == "completed"


# ---------- sync_session_from_kanban_event ---------------------------------


def _seed_dispatcher_with_dispatched_session(tmp_path, routing_table,
                                             directive_id="d-sync-001"):
    dispatcher = _make_dispatcher(tmp_path, routing_table)
    d = parse_directive(_directive_body(directive_id=directive_id))
    fake_kanban = '{"id": "t_sync_001", "created_at": 1}'
    with mock.patch(
        "directive_watcher.kanban_primitive.subprocess.run",
        return_value=mock.Mock(returncode=0, stdout=fake_kanban, stderr=""),
    ):
        result = dispatcher.dispatch(
            DispatchRequest(directive=d, source_comment_id=1,
                            execution_id="exec-sync-001"),
        )
    return dispatcher, result.session_id


def test_dispatched_session_transitions_to_done_when_kanban_event_completed(
    tmp_path: Path, routing_table: Path,
):
    kanban_db = tmp_path / "kanban.db"
    _seed_kanban_db(
        kanban_db,
        directive_id="d-sync-001",
        task_id="t_sync_001",
        events=[
            ("spawned", {"worker_pid": 7}),
            ("completed", {"outcome": "success",
                           "tests_summary": "12/12 passed",
                           "evidence_uri": "/ev/d-sync-001/run.json"}),
        ],
    )
    dispatcher, session_id = _seed_dispatcher_with_dispatched_session(
        tmp_path, routing_table,
    )
    assert dispatcher.get_session(session_id).state == SESSION_STATE_DISPATCHED

    changed = sync_session_from_kanban_event(
        session_id=session_id,
        kanban_db_path=str(kanban_db),
        session_log=str(tmp_path / "sessions.jsonl"),
        dispatcher=dispatcher,
    )

    assert changed is True
    s = dispatcher.get_session(session_id)
    assert s.state == SESSION_STATE_DONE
    assert s.tests_summary == "12/12 passed"
    assert s.evidence_uri == "/ev/d-sync-001/run.json"


def test_dispatched_session_transitions_to_failed_when_kanban_event_failed(
    tmp_path: Path, routing_table: Path,
):
    kanban_db = tmp_path / "kanban.db"
    _seed_kanban_db(
        kanban_db,
        directive_id="d-sync-001",
        task_id="t_sync_001",
        events=[
            ("spawned", {"worker_pid": 7}),
            ("failed", {"outcome": "failed",
                        "error": "boom",
                        "evidence_uri": "/ev/d-sync-001/fail.json"}),
        ],
    )
    dispatcher, session_id = _seed_dispatcher_with_dispatched_session(
        tmp_path, routing_table,
    )

    changed = sync_session_from_kanban_event(
        session_id=session_id,
        kanban_db_path=str(kanban_db),
        session_log=str(tmp_path / "sessions.jsonl"),
        dispatcher=dispatcher,
    )

    assert changed is True
    s = dispatcher.get_session(session_id)
    assert s.state == SESSION_STATE_FAILED


def test_dispatched_session_no_update_when_kanban_event_unrelated(
    tmp_path: Path, routing_table: Path,
):
    """A kanban event for a DIFFERENT directive must not touch this session."""
    kanban_db = tmp_path / "kanban.db"
    _seed_kanban_db(
        kanban_db,
        directive_id="d-other-thing",
        task_id="t_other",
        events=[("completed", {"outcome": "success",
                               "tests_summary": "should-not-stick"})],
    )
    dispatcher, session_id = _seed_dispatcher_with_dispatched_session(
        tmp_path, routing_table, directive_id="d-sync-001",
    )

    changed = sync_session_from_kanban_event(
        session_id=session_id,
        kanban_db_path=str(kanban_db),
        session_log=str(tmp_path / "sessions.jsonl"),
        dispatcher=dispatcher,
    )

    assert changed is False
    s = dispatcher.get_session(session_id)
    assert s.state == SESSION_STATE_DISPATCHED
    assert s.tests_summary == "-"
    assert s.evidence_uri == ""


def test_sync_idempotent_running_multiple_times(tmp_path: Path,
                                                 routing_table: Path):
    """Running sync twice with the same kanban event must not corrupt the
    record or duplicate evidence."""
    kanban_db = tmp_path / "kanban.db"
    _seed_kanban_db(
        kanban_db,
        directive_id="d-sync-001",
        task_id="t_sync_001",
        events=[("completed", {"outcome": "success",
                                "tests_summary": "12/12 passed",
                                "evidence_uri": "/ev/d-sync-001/run.json"})],
    )
    dispatcher, session_id = _seed_dispatcher_with_dispatched_session(
        tmp_path, routing_table,
    )

    first = sync_session_from_kanban_event(
        session_id=session_id,
        kanban_db_path=str(kanban_db),
        session_log=str(tmp_path / "sessions.jsonl"),
        dispatcher=dispatcher,
    )
    second = sync_session_from_kanban_event(
        session_id=session_id,
        kanban_db_path=str(kanban_db),
        session_log=str(tmp_path / "sessions.jsonl"),
        dispatcher=dispatcher,
    )

    assert first is True
    # Second sync sees the session is already DONE — no-op.
    assert second is False
    s = dispatcher.get_session(session_id)
    assert s.state == SESSION_STATE_DONE
    assert s.tests_summary == "12/12 passed"


def test_sync_spawned_event_transitions_to_running(tmp_path: Path,
                                                    routing_table: Path):
    """A spawned event with worker_pid must advance DISPATCHED → RUNNING."""
    kanban_db = tmp_path / "kanban.db"
    _seed_kanban_db(
        kanban_db,
        directive_id="d-sync-001",
        task_id="t_sync_001",
        events=[("spawned", {"worker_pid": 4242})],
    )
    dispatcher, session_id = _seed_dispatcher_with_dispatched_session(
        tmp_path, routing_table,
    )

    changed = sync_session_from_kanban_event(
        session_id=session_id,
        kanban_db_path=str(kanban_db),
        session_log=str(tmp_path / "sessions.jsonl"),
        dispatcher=dispatcher,
    )

    assert changed is True
    s = dispatcher.get_session(session_id)
    assert s.state == SESSION_STATE_RUNNING


def test_sync_no_event_returns_false(tmp_path: Path, routing_table: Path):
    """Empty kanban DB → no event → sync returns False without raising."""
    kanban_db = tmp_path / "kanban.db"
    kanban_db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(kanban_db)) as conn:
        conn.executescript(KANBAN_SCHEMA)
        conn.commit()

    dispatcher, session_id = _seed_dispatcher_with_dispatched_session(
        tmp_path, routing_table,
    )

    changed = sync_session_from_kanban_event(
        session_id=session_id,
        kanban_db_path=str(kanban_db),
        session_log=str(tmp_path / "sessions.jsonl"),
        dispatcher=dispatcher,
    )
    assert changed is False
    assert dispatcher.get_session(session_id).state == SESSION_STATE_DISPATCHED
