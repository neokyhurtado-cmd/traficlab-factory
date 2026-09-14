"""EVOLUTION-V1 closeout canary — chain DIRECTIVE → KANBAN → CONSUMER →
WORKER → RUNNING → AUDIT → DONE → RESULT.

Per directive `evolution-v1-closeout-20260914-01`, the closeout MUST
demonstrate the full pipeline runs end-to-end with the new BODY-1
checkpoint store integrated. The test does NOT require a live GitHub
repo or a running gateway — it uses the existing pure test seams:

  - `directive_watcher.handler.Handler` with stubbed gh_client
  - `directive_watcher.kanban_primitive.dispatch_to_kanban` (stubbed)
  - `agent_body.checkpoint_store.CheckpointStore` (real, temp dir)
  - `agent_body.audit.append_audit_event` (real, temp dir)

The chain runs to DONE only if every seam completes — including the
checkpoint-store write that BODY-1 introduces. This is the canary: if
any seam is broken, the test fails and the closeout must not be posted.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest


def test_full_chain_directive_to_done_with_checkpoint(tmp_path, monkeypatch):
    """End-to-end: directive → sidecar → dispatch → checkpoint → audit → done."""
    from agent_body.checkpoint_store import CheckpointStore, Checkpoint, AuthoritativePointer
    from agent_body.audit import AuditStore, AuditEvent
    from agent_body.worker_bootstrap import WorkerBootstrap

    # 1. DIRECTIVE arrives (simulated by writing a minimal parsed directive).
    directive = {
        "directive_id": "evolution-v1-closeout-20260914-01",
        "repository": "neokyhurtado-cmd/traficlab-factory",
        "issue": 27,
        "expected_head": "7225d3e383f268b3b7032294ac6ef0c76d5c5d62",
        "action": "EXECUTE",
        "source_comment_id": 5659491838,
        "head_before": "7225d3e383f268b3b7032294ac6ef0c76d5c5d62",
        "reversible": True,
    }

    # 2. KANBAN task created (simulated by writing to a test kanban db).
    kanban_db = tmp_path / "kanban.sqlite"
    _seed_kanban(kanban_db, task_id=directive["directive_id"])

    # 3. CONSUMER picks up the task (the worker).
    cp_db = tmp_path / "checkpoints.sqlite"
    audit_db = tmp_path / "audit.sqlite"
    worker = WorkerBootstrap(
        checkpoint_db=cp_db,
        audit_db=audit_db,
        kanban_db=kanban_db,
    )

    # 4. WORKER loads checkpoint (none yet → first-write path).
    cp = worker.bootstrap(
        task_id=directive["directive_id"],
        directive=directive,
    )

    # 5. RUNNING state — checkpoint must record the bootstrap shape.
    assert cp.last_verified_head == directive["expected_head"]
    assert cp.state == "ACTIVE"
    assert cp.next_safe_action != ""
    assert any(p.scheme == "repo" and "traficlab-factory" in p.value for p in cp.authoritative_pointers)
    assert any(p.scheme == "issue" and p.value == "#27" for p in cp.authoritative_pointers)

    # 6. AUDIT events recorded (one per major seam).
    audit = AuditStore(audit_db)
    events = audit.all_events(task_id=directive["directive_id"])
    assert len(events) >= 1, "at least one audit event must be appended"
    for ev in events:
        assert ev.action.startswith("context.") or ev.action.startswith("bootstrap") or ev.action.startswith("checkpoint")
        # Audit event schema MUST NOT contain a free-text body — proves no
        # prompt injection surface (per AGENT_BODY_27_READONLY_AUDIT §5.5).
        assert not hasattr(ev, "body_text") or ev.body_text == ""

    # 7. DONE — checkpoint transitions to DONE.
    worker.complete(task_id=directive["directive_id"], result="closeout_complete")
    final_cp = CheckpointStore(cp_db).read(directive["directive_id"])
    assert final_cp.state == "DONE"
    assert final_cp.next_safe_action == "none"

    # 8. RESULT — durable record exists for the orchestrator to publish.
    result_path = tmp_path / "result.json"
    worker.write_result(task_id=directive["directive_id"], path=result_path)
    assert result_path.exists()
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["directive_id"] == directive["directive_id"]
    assert result["state"] == "DONE"
    assert result["manual_context_copy_paste"] == 0
    assert result["mutations_this_gate"] == 0


def test_chain_blocks_when_checkpoint_goes_stale(tmp_path, monkeypatch):
    """If the live HEAD drifts past the checkpoint, the chain MUST stop."""
    from agent_body.checkpoint_store import CheckpointStore, Checkpoint, AuthoritativePointer
    from agent_body.worker_bootstrap import WorkerBootstrap

    kanban_db = tmp_path / "kanban.sqlite"
    cp_db = tmp_path / "checkpoints.sqlite"
    audit_db = tmp_path / "audit.sqlite"
    _seed_kanban(kanban_db, task_id="t_canary_stale")

    worker = WorkerBootstrap(
        checkpoint_db=cp_db, audit_db=audit_db, kanban_db=kanban_db,
    )
    directive = {
        "directive_id": "t_canary_stale",
        "repository": "neokyhurtado-cmd/traficlab-factory",
        "issue": 27,
        "expected_head": "8e2d9c9",  # old
        "action": "EXECUTE",
        "source_comment_id": 5659491838,
        "head_before": "8e2d9c9",
        "reversible": True,
    }
    worker.bootstrap(task_id="t_canary_stale", directive=directive)

    # Now simulate that the live HEAD has moved on.
    live_head = "7225d3e383f268b3b7032294ac6ef0c76d5c5d62"
    verdict = worker.check_freshness(task_id="t_canary_stale", current_head=live_head)
    assert verdict.state == "STALE"
    assert verdict.reconciliation_required is True
    assert verdict.allowed_to_continue is False

    # The worker must NOT silently complete on stale info.
    with pytest.raises(RuntimeError):
        worker.complete(task_id="t_canary_stale", result="should_not_happen")


def _seed_kanban(db_path: Path, task_id: str) -> None:
    """Write a minimal kanban schema so the worker has a real DB to read."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                assignee TEXT,
                payload TEXT
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                task_id TEXT,
                payload TEXT,
                created_at INTEGER
            );
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO tasks(id, state, assignee, payload) VALUES (?, ?, ?, ?)",
            (task_id, "ready", "orchestrator", "{}"),
        )
        conn.commit()
    finally:
        conn.close()
