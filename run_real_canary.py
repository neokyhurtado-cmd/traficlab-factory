"""REAL E2E canary runner for FACTORY-E2E-BRIDGE-01.

Drives the real WatcherHandler.tick() with FakeGitHubClient and observes
events as they arrive in C:\\dev\\TraficLabPro\\panorama-mission-control-main\\
99_SYSTEM\\live_brain\\runtime\\events.jsonl through the canonical
emit_event.py subprocess.

Run as:
    LIVE_BRAIN_BRIDGE_ENABLED=1 LIVE_BRAIN_REPO_DIR=... python run_real_canary.py

Exit code:
    0 = all canaries PASS
    1 = at least one canary FAILED

This script is the canonical replacement for test_e2e_bridge_canary.py
which has Windows tempfile cleanup race conditions that make it
unreliable inside pytest. The script form works reliably.
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

# CRITICAL: env must be set BEFORE importing directive_watcher modules.
os.environ.setdefault("LIVE_BRAIN_BRIDGE_ENABLED", "1")
os.environ.setdefault(
    "LIVE_BRAIN_REPO_DIR",
    r"C:\dev\TraficLabPro\panorama-mission-control-main",
)

REPO_ROOT = Path(
    r"C:/Users/david/repos/traficlab-factory/.worktrees/e2e-bridge-verify"
)
sys.path.insert(0, str(REPO_ROOT))

from directive_watcher.allowlist import AllowlistConfig
from directive_watcher.gh_client import FakeGitHubClient, RemoteComment
from directive_watcher.handler import WatcherHandler, ExecutionOutcome
from directive_watcher.retry import BackoffPolicy
from directive_watcher.sidecar_store import SidecarStore
from directive_watcher.orch_dispatch import OrchestratorDispatcher
from directive_watcher.kanban_session_sync import sync_session_from_kanban_event

TEST_REPO = "neokyhurtado-cmd/traficlab-factory"
TEST_AUTHOR = "astra"
EVENTS_FILE = Path(
    r"C:\dev\TraficLabPro\panorama-mission-control-main\99_SYSTEM\live_brain\runtime\events.jsonl"
)


def _make_env(td: Path):
    """Build a real handler env with the canonical routing.yaml."""
    store = SidecarStore(td / "sidecar.db")
    store.set_watermark(repo=TEST_REPO, value=0)
    gh = FakeGitHubClient()
    gh.set_branch_head(TEST_REPO, "main", "a" * 40)
    routing_src = REPO_ROOT / "orchestrator/config/routing.yaml"
    routing_dst = td / "routing.yaml"
    shutil.copy(str(routing_src), str(routing_dst))
    dispatcher = OrchestratorDispatcher(
        session_log=str(td / "sessions.jsonl"),
        routing_table_path=str(routing_dst),
        kanban_bin="nonexistent_kanban",
    )
    def fake_invoke(directive, assignee):
        return f"t_e2e_{int(time.time()*1000)%100000}"
    dispatcher._invoke_kanban = fake_invoke
    handler = WatcherHandler(
        store=store,
        gh=gh,
        allowlist=AllowlistConfig(
            allowlisted_repos=frozenset({TEST_REPO}),
            allowlisted_authors=frozenset({TEST_AUTHOR}),
        ),
        evidence_root=str(td),
        backoff=BackoffPolicy(initial_seconds=0.001, max_attempts=2),
        dispatcher=dispatcher,
    )
    return handler, gh, store, dispatcher


def _directive_body(directive_id: str) -> str:
    return (
        "[ASTRA_DIRECTIVE:v1]\n"
        "ACTION = CONTINUE\n"
        f"REPOSITORY = {TEST_REPO}\n"
        "ISSUE = 18\n"
        "TARGET_BRANCH = main\n"
        "EXPECTED_HEAD = NONE\n"
        "SCOPE = e2e bridge canary\n"
        "AUTO_NEXT_SAFE_GATE = YES\n"
        "REQUIRES_HUMAN_GO_REAL = NO\n"
        f"DIRECTIVE_ID = {directive_id}\n"
    )


def _wait_for_events(directive_id: str, size_before: int, timeout_s: float = 8.0) -> list:
    """Poll events.jsonl for events related to this directive."""
    deadline = time.time() + timeout_s
    matching = []
    while time.time() < deadline:
        time.sleep(0.3)
        if not EVENTS_FILE.exists():
            continue
        with open(EVENTS_FILE, "r", encoding="utf-8") as f:
            f.seek(size_before)
            new_events = [json.loads(l) for l in f if l.strip()]
        matching = [e for e in new_events
                    if directive_id in (e.get("subject") or "")
                    or directive_id in str(e.get("metrics") or {})]
        if matching:
            break
    return matching


def canary_happy_path() -> tuple[bool, str]:
    """REAL: durable claim -> task.created -> task.started (with kanban_task_id subject)."""
    td = Path(tempfile.mkdtemp(prefix="canary_happy_"))
    try:
        handler, gh, store, dispatcher = _make_env(td)
        directive_id = f"ASTRA-E2E-CANARY-HAPPY-{int(time.time())}"
        cid = int(time.time() * 1000) % 1000000
        comment = RemoteComment(
            id=cid, author=TEST_AUTHOR,
            body=_directive_body(directive_id),
            url=f"https://github.com/{TEST_REPO}/issues/18#issuecomment-{cid}",
            issue_number=18,
        )
        gh.add(comment)
        size_before = EVENTS_FILE.stat().st_size if EVENTS_FILE.exists() else 0
        summary = handler.tick([TEST_REPO])
        if summary.directives_claimed != 1:
            return False, f"expected 1 claim, got {summary.directives_claimed}"
        events = _wait_for_events(directive_id, size_before)
        types = [e["type"] for e in events]
        if "task.created" not in types:
            return False, f"no task.created in real flow. types={types}"
        # C3
        for e in events:
            if e["type"] == "task.completed":
                st = (e.get("status") or "").upper()
                if st == "DISPATCHED":
                    return False, f"C3 VIOLATION: task.completed with status=DISPATCHED"
        # C5
        started = [e for e in events if e["type"] == "task.started"]
        if not started:
            return False, "no task.started in real flow"
        subject = started[0]["subject"]
        if subject == directive_id:
            return False, f"subject is still directive_id, not kanban_task_id: {subject}"
        if not (subject.startswith("t_") or subject.startswith("t-")):
            return False, f"subject {subject} should look like a kanban_task_id"
        # C2
        metrics = started[0].get("metrics", {})
        for k in ("started_at", "worker_pid", "worker_runtime_id"):
            if k not in metrics:
                return False, f"task.started missing metric {k}"
        if metrics["worker_pid"] == "UNKNOWN":
            return False, "worker_pid is UNKNOWN, should be observable"
        return True, (
            f"OK: directive={directive_id} kanban_task_id={subject} "
            f"worker_pid={metrics['worker_pid']} types={types}"
        )
    finally:
        shutil.rmtree(td, ignore_errors=True)


def canary_dispatched_not_completed() -> tuple[bool, str]:
    """C3: handler returning status=DISPATCHED must NOT emit task.completed."""
    td = Path(tempfile.mkdtemp(prefix="canary_dispatched_"))
    try:
        handler, gh, store, dispatcher = _make_env(td)
        def dispatched_outcome(d, e):
            return ExecutionOutcome(
                status="DISPATCHED", head_after=None,
                tests="session_id=test_sess; kanban_task_id=test_t",
                evidence=e,
            )
        handler._execution_fn = dispatched_outcome
        directive_id = f"ASTRA-E2E-CANARY-DISPATCHED-{int(time.time())}"
        cid = (int(time.time() * 1000) + 1) % 1000000
        comment = RemoteComment(
            id=cid, author=TEST_AUTHOR,
            body=_directive_body(directive_id),
            url=f"https://github.com/{TEST_REPO}/issues/18#issuecomment-{cid}",
            issue_number=18,
        )
        gh.add(comment)
        size_before = EVENTS_FILE.stat().st_size if EVENTS_FILE.exists() else 0
        summary = handler.tick([TEST_REPO])
        if summary.directives_claimed != 1:
            return False, f"expected 1 claim, got {summary.directives_claimed}"
        events = _wait_for_events(directive_id, size_before)
        completed = [e for e in events if e["type"] == "task.completed"]
        for e in completed:
            st = (e.get("status") or "").upper()
            if st == "DISPATCHED":
                return False, f"C3 VIOLATION: task.completed with status=DISPATCHED"
        heartbeats = [e for e in events if e["type"] == "task.heartbeat"
                      and (e.get("status") or "").upper() == "DISPATCHED"]
        if not heartbeats:
            return False, "no task.heartbeat with DISPATCHED status"
        return True, f"OK: heartbeats={len(heartbeats)} (none map to completed)"
    finally:
        shutil.rmtree(td, ignore_errors=True)


def canary_reconciliation_done() -> tuple[bool, str]:
    """C4: reconciliation observes terminal DONE -> emits task.completed via on_terminal_observed."""
    td = Path(tempfile.mkdtemp(prefix="canary_reconcile_"))
    try:
        store = SidecarStore(td / "sidecar.db")
        dispatcher = OrchestratorDispatcher(
            session_log=str(td / "sessions.jsonl"),
            routing_table_path=str(REPO_ROOT / "orchestrator/config/routing.yaml"),
            kanban_bin="nonexistent_kanban",
        )
        from directive_watcher.orch_dispatch import SessionRecord
        directive_id = f"ASTRA-E2E-CANARY-RECONCILE-{int(time.time())}"
        session_id = "sess-reconcile-done"
        kanban_task_id = "t-reconcile-done"
        rec = SessionRecord(
            session_id=session_id, execution_id="exec-reconcile",
            directive_id=directive_id, repository=TEST_REPO,
            issue_number=18, target_branch="main",
            kanban_task_id=kanban_task_id, assignee="hermes",
            state="DISPATCHED", source_comment_id=0,
        )
        dispatcher._append(rec)
        # The dispatcher._append() wrote the session to session_log
        # already (to_json format). We do NOT overwrite it because
        # the session_log is the source of truth for the reconcile
        # lookup. Verify the session is searchable.
        from directive_watcher.kanban_session_sync import _find_directive_id_for_session
        log_path = td / "sessions.jsonl"
        looked_up = _find_directive_id_for_session(
            session_id, session_log=str(log_path),
        )
        if looked_up != directive_id:
            return False, (
                f"session_log lookup failed: wrote {directive_id}, "
                f"looked_up {looked_up}"
            )
        kanban_db = td / "kanban.db"
        conn = sqlite3.connect(str(kanban_db))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                idempotency_key TEXT NOT NULL,
                task_id TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                payload TEXT,
                created_at INTEGER NOT NULL
            )
        """)
        # Seed the task with idempotency_key='directive:<id>' so the
        # reconciliation join finds it.
        conn.execute(
            "INSERT INTO tasks (idempotency_key, task_id, created_at) VALUES (?, ?, ?)",
            (f"directive:{directive_id}", kanban_task_id, int(time.time())),
        )
        # task_events.task_id is the tasks.id (INTEGER), not task_id (TEXT).
        cur = conn.execute("SELECT id FROM tasks WHERE idempotency_key=?", (f"directive:{directive_id}",))
        tasks_id = cur.fetchone()[0]
        conn.execute(
            "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, ?, ?, ?)",
            (tasks_id, "completed",
             json.dumps({"tests_summary": "5/5 PASS", "evidence_uri": "/evidence/x"}),
             int(time.time())),
        )
        conn.commit()
        conn.close()
        size_before = EVENTS_FILE.stat().st_size if EVENTS_FILE.exists() else 0
        mutated = sync_session_from_kanban_event(
            session_id,
            kanban_db_path=str(kanban_db),
            session_log=str(log_path),
            dispatcher=dispatcher,
        )
        if not mutated:
            return False, "reconciliation did not mutate the session"
        events = _wait_for_events(directive_id, size_before)
        completed_via_recon = [
            e for e in events
            if e["type"] == "task.completed"
            and (e.get("metrics") or {}).get("observed_via")
            == "kanban_session_sync.reconcile_open_sessions"
        ]
        if not completed_via_recon:
            return False, (
                f"reconciliation did not emit task.completed. "
                f"events: {[(e['type'], e.get('source')) for e in events]}"
            )
        if completed_via_recon[0]["subject"] != kanban_task_id:
            return False, (
                f"subject should be kanban_task_id={kanban_task_id}, "
                f"got {completed_via_recon[0]['subject']}"
            )
        if completed_via_recon[0]["metrics"].get("tests_summary") != "5/5 PASS":
            return False, "tests_summary not propagated"
        return True, f"OK: reconciliation emitted task.completed for {kanban_task_id}"
    finally:
        shutil.rmtree(td, ignore_errors=True)


def canary_failed_replan() -> tuple[bool, str]:
    """FAIL_REPLAN: FAILED -> task.failed, never task.completed."""
    td = Path(tempfile.mkdtemp(prefix="canary_fail_"))
    try:
        from directive_watcher.orch_dispatch import SessionRecord
        store = SidecarStore(td / "sidecar.db")
        dispatcher = OrchestratorDispatcher(
            session_log=str(td / "sessions.jsonl"),
            routing_table_path=str(REPO_ROOT / "orchestrator/config/routing.yaml"),
            kanban_bin="nonexistent_kanban",
        )
        directive_id = f"ASTRA-E2E-CANARY-FAIL-{int(time.time())}"
        session_id = "sess-fail-canary"
        kanban_task_id = "t-fail-canary"
        rec = SessionRecord(
            session_id=session_id, execution_id="exec-fail",
            directive_id=directive_id, repository=TEST_REPO,
            issue_number=18, target_branch="main",
            kanban_task_id=kanban_task_id, assignee="hermes",
            state="DISPATCHED", source_comment_id=0,
        )
        dispatcher._append(rec)
        from directive_watcher.kanban_session_sync import _find_directive_id_for_session
        log_path = td / "sessions.jsonl"
        looked_up = _find_directive_id_for_session(
            session_id, session_log=str(log_path),
        )
        if looked_up != directive_id:
            return False, (
                f"session_log lookup failed: wrote {directive_id}, "
                f"looked_up {looked_up}"
            )
        kanban_db = td / "kanban.db"
        conn = sqlite3.connect(str(kanban_db))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                idempotency_key TEXT NOT NULL,
                task_id TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                payload TEXT,
                created_at INTEGER NOT NULL
            )
        """)
        conn.execute(
            "INSERT INTO tasks (idempotency_key, task_id, created_at) VALUES (?, ?, ?)",
            (f"directive:{directive_id}", kanban_task_id, int(time.time())),
        )
        cur = conn.execute("SELECT id FROM tasks WHERE idempotency_key=?", (f"directive:{directive_id}",))
        tasks_id = cur.fetchone()[0]
        conn.execute(
            "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, ?, ?, ?)",
            (tasks_id, "failed",
             json.dumps({"evidence_uri": "/evidence/fail"}),
             int(time.time())),
        )
        conn.commit()
        conn.close()
        size_before = EVENTS_FILE.stat().st_size if EVENTS_FILE.exists() else 0
        mutated = sync_session_from_kanban_event(
            session_id,
            kanban_db_path=str(kanban_db),
            session_log=str(log_path),
            dispatcher=dispatcher,
        )
        if not mutated:
            return False, "reconciliation did not mutate the session"
        events = _wait_for_events(directive_id, size_before)
        # FAILED must NOT show up as task.completed
        completed = [e for e in events if e["type"] == "task.completed"]
        if completed:
            return False, f"FAIL_REPLAN VIOLATION: failed -> task.completed: {completed}"
        failed = [e for e in events if e["type"] == "task.failed"]
        if not failed:
            return False, "no task.failed emitted for FAILED outcome"
        return True, f"OK: failed -> task.failed (no task.completed)"
    finally:
        shutil.rmtree(td, ignore_errors=True)


def main() -> int:
    print(f"LIVE_BRAIN_BRIDGE_ENABLED={os.environ.get('LIVE_BRAIN_BRIDGE_ENABLED')}")
    print(f"LIVE_BRAIN_REPO_DIR={os.environ.get('LIVE_BRAIN_REPO_DIR')}")
    print(f"EVENTS_FILE={EVENTS_FILE}")
    print(f"EVENTS_FILE size before canary: {EVENTS_FILE.stat().st_size if EVENTS_FILE.exists() else 0}")
    print()
    canaries = [
        ("happy_path", canary_happy_path),
        ("dispatched_not_completed", canary_dispatched_not_completed),
        ("reconciliation_done", canary_reconciliation_done),
        ("failed_replan", canary_failed_replan),
    ]
    passed = 0
    failed = 0
    for name, fn in canaries:
        print(f"=== CANARY: {name} ===")
        try:
            ok, msg = fn()
        except Exception as e:
            ok = False
            msg = f"EXCEPTION: {type(e).__name__}: {e}"
        if ok:
            passed += 1
            print(f"  PASS: {msg}")
        else:
            failed += 1
            print(f"  FAIL: {msg}")
        print()
    print(f"=== SUMMARY: {passed} passed, {failed} failed ===")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
