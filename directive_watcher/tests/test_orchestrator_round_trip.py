"""End-to-end round-trip test for the kanban → sessions.jsonl sync seam.

This is the AUTONOMY-V2 integration test: a real ``WatcherHandler.tick()``
delivers a directive all the way through dispatch + kanban-event
observation, and the resulting ``SessionRecord`` must reflect the
kanban's terminal state.

Setup
-----
  1. A ``SidecarStore`` with a pre-seeded fresh-start watermark.
  2. A ``FakeGitHubClient`` carrying one ASTRA directive comment.
  3. A ``WatcherHandler`` wired to an ``OrchestratorDispatcher`` whose
     kanban subprocess is mocked to return ``t_e2e_round``.
  4. A synthetic kanban DB (sqlite3) carrying the task_events that the
     downstream worker would have produced for ``directive:d-e2e-round``.

The test then calls ``handler.tick([...])`` and asserts that the
``SessionRecord`` ends in ``state=DONE`` with the expected
``tests_summary`` and ``evidence_uri`` — i.e. the handler closed the
observation gap on its own, with no second hand-rolled call.

Why this matters
----------------
The unit tests in ``test_kanban_session_sync.py`` cover the sync
function in isolation. This module proves the seam is actually wired
into the handler tick path. If the handler's import or the call site
ever drifts, the unit tests still pass but THIS test fails — that's
the signal we want.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest import mock

import pytest

from directive_watcher.allowlist import AllowlistConfig
from directive_watcher.gh_client import FakeGitHubClient, RemoteComment
from directive_watcher.handler import WatcherHandler
from directive_watcher.kanban_session_sync import ENV_KANBAN_DB, ENV_SESSION_LOG
from directive_watcher.orch_dispatch import (
    SESSION_STATE_DISPATCHED,
    SESSION_STATE_DONE,
    OrchestratorDispatcher,
)
from directive_watcher.retry import BackoffPolicy
from directive_watcher.sidecar_store import SidecarStore


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


def _make_comment(cid: int, body: str, author: str = "astra") -> RemoteComment:
    return RemoteComment(
        id=cid,
        author=author,
        body=body,
        url=f"https://github.com/r/o/issues/18#issuecomment-{cid}",
        issue_number=18,
    )


def _directive_body(directive_id: str) -> str:
    return (
        "[ASTRA_DIRECTIVE:v1]\n"
        "ACTION = CONTINUE\n"
        "REPOSITORY = neokyhurtado-cmd/traficlab-factory\n"
        "ISSUE = 18\n"
        "TARGET_BRANCH = AUTO_FROM_ISSUE_CONTEXT\n"
        "EXPECTED_HEAD = NONE\n"
        "SCOPE = round-trip\n"
        "AUTO_NEXT_SAFE_GATE = YES\n"
        "REQUIRES_HUMAN_GO_REAL = NO\n"
        f"DIRECTIVE_ID = {directive_id}\n"
    )


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


def _seed_kanban_db(
    db_path: Path, *, directive_id: str, task_id: str,
    payload: dict,
) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        conn.executescript(KANBAN_SCHEMA)
        conn.execute(
            "INSERT INTO tasks (id, title, body, assignee, status, "
            "created_at, idempotency_key) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (task_id, "t", "b", "hermes-director", "completed",
             1_700_000_000, f"directive:{directive_id}"),
        )
        conn.execute(
            "INSERT INTO task_events (task_id, run_id, kind, payload, "
            "created_at) VALUES (?, NULL, ?, ?, ?)",
            (task_id, "completed", json.dumps(payload),
             1_700_000_001),
        )
        conn.commit()


def _build_round_trip_env(
    tmp_path: Path, routing_table: Path,
) -> tuple[dict, Path, Path]:
    """Build (env_dict, kanban_db, session_log).

    We use the dispatcher-mocked kanban subprocess AND seed a fake
    kanban DB so the post-dispatch sync finds a terminal event.
    """
    store = SidecarStore(tmp_path / "sidecar.db")
    store.set_watermark(repo="neokyhurtado-cmd/traficlab-factory", value=0)
    gh = FakeGitHubClient()
    gh.set_branch_head(
        "neokyhurtado-cmd/traficlab-factory", "main",
        "1111111111111111111111111111111111111111",
    )
    allowlist = AllowlistConfig(
        allowlisted_repos=frozenset({"neokyhurtado-cmd/traficlab-factory"}),
        allowlisted_authors=frozenset({"astra"}),
    )
    dispatcher = OrchestratorDispatcher(  # noqa: F821 — imported below
        session_log=str(tmp_path / "sessions.jsonl"),
        routing_table_path=str(routing_table),
    )
    handler = WatcherHandler(
        store=store,
        gh=gh,
        allowlist=allowlist,
        evidence_root=str(tmp_path),
        dispatcher=dispatcher,
        backoff=BackoffPolicy(initial_seconds=0.001, max_attempts=2),
    )
    env = {
        "store": store, "gh": gh, "allowlist": allowlist,
        "handler": handler, "dispatcher": dispatcher, "tmp_path": tmp_path,
    }
    kanban_db = tmp_path / "kanban.db"
    session_log = tmp_path / "sessions.jsonl"
    return env, kanban_db, session_log


# 1. Round-trip: handler tick sees the kanban event and DONE is set.
def test_handler_tick_advances_session_to_done_when_kanban_already_completed(
    tmp_path: Path, routing_table: Path,
    monkeypatch: pytest.MonkeyPatch,
):

    env, kanban_db, session_log = _build_round_trip_env(tmp_path, routing_table)
    handler = env["handler"]
    dispatcher = env["dispatcher"]
    gh = env["gh"]

    _seed_kanban_db(
        kanban_db,
        directive_id="d-e2e-round",
        task_id="t_e2e_round",
        payload={
            "outcome": "success",
            "tests_summary": "12/12 passed",
            "evidence_uri": "/evidence/d-e2e-round/run.json",
        },
    )

    # Opt-in env vars so the handler's wire-up actually consults the
    # kanban DB + JSONL sidecar.
    monkeypatch.setenv(ENV_KANBAN_DB, str(kanban_db))
    monkeypatch.setenv(ENV_SESSION_LOG, str(session_log))

    gh.add(_make_comment(201, _directive_body("d-e2e-round")))

    fake_kanban = '{"id": "t_e2e_round", "created_at": 1700000000}'
    with mock.patch(
        "directive_watcher.kanban_primitive.subprocess.run",
        return_value=mock.Mock(returncode=0, stdout=fake_kanban, stderr=""),
    ):
        summary = handler.tick(["neokyhurtado-cmd/traficlab-factory"])

    assert summary.directives_claimed == 1
    assert summary.directives_failed == 0

    sessions = dispatcher.list_sessions()
    assert len(sessions) == 1
    session = sessions[0]
    # The whole point of the PR: state must have advanced from DISPATCHED.
    assert session.state == SESSION_STATE_DONE
    assert session.tests_summary == "12/12 passed"
    assert session.evidence_uri == "/evidence/d-e2e-round/run.json"


# 2. Without opt-in env vars the handler still works and leaves the
#    session in DISPATCHED (no observation, but no breakage either).
def test_handler_tick_without_kanban_env_does_not_break(
    tmp_path: Path, routing_table: Path,
    monkeypatch: pytest.MonkeyPatch,
):

    env, kanban_db, session_log = _build_round_trip_env(tmp_path, routing_table)
    handler = env["handler"]
    dispatcher = env["dispatcher"]
    gh = env["gh"]

    _seed_kanban_db(
        kanban_db,
        directive_id="d-no-env",
        task_id="t_no_env",
        payload={"outcome": "success", "tests_summary": "won't-stick"},
    )

    # Explicitly clear the opt-in env vars so the sync is a no-op.
    monkeypatch.delenv(ENV_KANBAN_DB, raising=False)
    monkeypatch.delenv(ENV_SESSION_LOG, raising=False)

    gh.add(_make_comment(202, _directive_body("d-no-env")))

    fake_kanban = '{"id": "t_no_env", "created_at": 1700000000}'
    with mock.patch(
        "directive_watcher.kanban_primitive.subprocess.run",
        return_value=mock.Mock(returncode=0, stdout=fake_kanban, stderr=""),
    ):
        summary = handler.tick(["neokyhurtado-cmd/traficlab-factory"])

    assert summary.directives_claimed == 1
    sessions = dispatcher.list_sessions()
    assert len(sessions) == 1
    # Without opt-in, the sync is skipped → state stays DISPATCHED.
    assert sessions[0].state == SESSION_STATE_DISPATCHED
    assert sessions[0].tests_summary == "-"


# 3. With env vars but no matching kanban event, sync is a no-op too.
def test_handler_tick_with_env_but_no_kanban_event_keeps_dispatched(
    tmp_path: Path, routing_table: Path,
    monkeypatch: pytest.MonkeyPatch,
):

    env, kanban_db, session_log = _build_round_trip_env(tmp_path, routing_table)
    handler = env["handler"]
    dispatcher = env["dispatcher"]
    gh = env["gh"]

    # Empty kanban DB → schema but no rows.
    kanban_db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(kanban_db)) as conn:
        conn.executescript(KANBAN_SCHEMA)
        conn.commit()

    monkeypatch.setenv(ENV_KANBAN_DB, str(kanban_db))
    monkeypatch.setenv(ENV_SESSION_LOG, str(session_log))

    gh.add(_make_comment(203, _directive_body("d-empty-kanban")))

    fake_kanban = '{"id": "t_empty", "created_at": 1700000000}'
    with mock.patch(
        "directive_watcher.kanban_primitive.subprocess.run",
        return_value=mock.Mock(returncode=0, stdout=fake_kanban, stderr=""),
    ):
        summary = handler.tick(["neokyhurtado-cmd/traficlab-factory"])

    assert summary.directives_claimed == 1
    sessions = dispatcher.list_sessions()
    assert len(sessions) == 1
    assert sessions[0].state == SESSION_STATE_DISPATCHED
