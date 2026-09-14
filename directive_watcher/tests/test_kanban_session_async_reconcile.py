"""Regression tests for PR #30 asynchronous session observation.

The important counterexample is temporal, not merely structural:

    tick N     -> directive is dispatched, session=DISPATCHED
    later      -> worker writes kanban completed event
    tick N + 1 -> no new directive is required; reconciliation makes DONE

The original PR tests seeded ``completed`` before the dispatch tick, which did
not prove this production lifecycle. These tests do.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest import mock

from directive_watcher.directive_parser import parse_directive
from directive_watcher.kanban_session_sync import reconcile_open_sessions
from directive_watcher.orch_dispatch import (
    DispatchRequest,
    OrchestratorDispatcher,
    SESSION_STATE_DISPATCHED,
    SESSION_STATE_DONE,
)


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
"""


def _routing_table(tmp_path: Path) -> Path:
    path = tmp_path / "routing.yaml"
    path.write_text(
        "routes:\n"
        "  - repo: neokyhurtado-cmd/traficlab-factory\n"
        "    product: ORCHESTRATION\n"
        "    assignee: hermes-director\n"
        "    capabilities: [write]\n"
        "    max_runtime_seconds: 3600\n",
        encoding="utf-8",
    )
    return path


def _directive(directive_id: str = "d-async-001"):
    return parse_directive(
        "[ASTRA_DIRECTIVE:v1]\n"
        "ACTION = CONTINUE\n"
        "REPOSITORY = neokyhurtado-cmd/traficlab-factory\n"
        "ISSUE = 27\n"
        "TARGET_BRANCH = AUTO_FROM_ISSUE_CONTEXT\n"
        "EXPECTED_HEAD = NONE\n"
        "SCOPE = async reconciliation regression\n"
        "AUTO_NEXT_SAFE_GATE = YES\n"
        "REQUIRES_HUMAN_GO_REAL = NO\n"
        f"DIRECTIVE_ID = {directive_id}\n"
    )


def _seed_completed_after_dispatch(
    db_path: Path,
    *,
    directive_id: str,
    task_id: str,
) -> None:
    with sqlite3.connect(str(db_path)) as conn:
        conn.executescript(KANBAN_SCHEMA)
        conn.execute(
            "INSERT INTO tasks (id, title, body, assignee, status, created_at, "
            "idempotency_key) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                task_id,
                "async",
                "body",
                "hermes-director",
                "completed",
                1_700_000_000,
                f"directive:{directive_id}",
            ),
        )
        conn.execute(
            "INSERT INTO task_events (task_id, run_id, kind, payload, created_at) "
            "VALUES (?, NULL, ?, ?, ?)",
            (
                task_id,
                "completed",
                json.dumps(
                    {
                        "outcome": "success",
                        "tests_summary": "async 1/1 passed",
                        "evidence_uri": "/evidence/async/run.json",
                    }
                ),
                1_700_000_001,
            ),
        )
        conn.commit()


def test_later_tick_reconciles_session_without_new_directive(tmp_path: Path):
    """The worker may finish after dispatch; the next observer tick must see it."""
    session_log = tmp_path / "sessions.jsonl"
    dispatcher = OrchestratorDispatcher(
        session_log=session_log,
        routing_table_path=_routing_table(tmp_path),
    )

    # Tick N: dispatch succeeds while no kanban event DB is available yet.
    fake_kanban = '{"id": "t_async_001", "created_at": 1700000000}'
    with mock.patch(
        "directive_watcher.kanban_primitive.subprocess.run",
        return_value=mock.Mock(returncode=0, stdout=fake_kanban, stderr=""),
    ):
        result = dispatcher.dispatch(
            DispatchRequest(
                directive=_directive(),
                source_comment_id=101,
                execution_id="exec-async-001",
            )
        )

    assert dispatcher.get_session(result.session_id).state == SESSION_STATE_DISPATCHED

    # Between ticks: the downstream worker finishes and writes kanban evidence.
    kanban_db = tmp_path / "kanban.db"
    _seed_completed_after_dispatch(
        kanban_db,
        directive_id="d-async-001",
        task_id="t_async_001",
    )

    # Tick N+1: no new directive/dispatch call. Periodic reconciliation alone
    # advances the durable SessionRecord.
    first = reconcile_open_sessions(
        dispatcher=dispatcher,
        kanban_db_path=kanban_db,
        session_log=session_log,
    )
    assert first == {"scanned": 1, "updated": 1, "errors": 0}

    session = dispatcher.get_session(result.session_id)
    assert session.state == SESSION_STATE_DONE
    assert session.tests_summary == "async 1/1 passed"
    assert session.evidence_uri == "/evidence/async/run.json"

    # Tick N+2: terminal session is skipped, proving no regression/duplicate write.
    second = reconcile_open_sessions(
        dispatcher=dispatcher,
        kanban_db_path=kanban_db,
        session_log=session_log,
    )
    assert second == {"scanned": 0, "updated": 0, "errors": 0}


def test_reconcile_without_observation_config_is_noop(tmp_path: Path):
    dispatcher = OrchestratorDispatcher(
        session_log=tmp_path / "sessions.jsonl",
        routing_table_path=_routing_table(tmp_path),
    )
    assert reconcile_open_sessions(
        dispatcher=dispatcher,
        kanban_db_path=None,
        session_log=None,
    ) == {"scanned": 0, "updated": 0, "errors": 0}


def test_canonical_orchestrator_tick_contains_reconcile_hook():
    """Guard the production wiring, not only the helper implementation."""
    repo_root = Path(__file__).resolve().parents[2]
    poller = repo_root / "orchestrator" / "scripts" / "github_poller.py"
    source = poller.read_text(encoding="utf-8")
    assert "from directive_watcher.kanban_session_sync import reconcile_open_sessions" in source
    assert "reconcile = reconcile_open_sessions(" in source
    assert "session_log=session_log" in source
