"""Read-only evidence sources for the TrafficLab Control read models.

Design contract (suini#54 follow-up, t_3bc6e5ce):

- **Every field the panel shows is a `Fact`**: a value plus where it came from,
  when it was captured, and an explicit availability state. There is no path in
  this module that returns a bare value with no provenance, because the WO is
  explicit: *"Use real available GitHub/control-plane evidence or clearly
  labeled snapshots; never manufacture statuses."*

- **Read-only, always.** SQLite is opened with `file:...?mode=ro` (URI mode) so a
  bug here can never write the kanban board. Git and GitHub are reached through
  read-only subcommands only (see `_GIT_READONLY` / `_GH_READONLY`). There is no
  write path in this file at all.

- **Product ownership boundary.** This module reads IA-VISION and SUINI *status*
  (remote SHA, visor liveness). It never reads their working trees, never writes
  their repos, DBs, runtimes or schemas.

- **Missing evidence is a first-class state, not an error to paper over.** When a
  source is unreachable the Fact is `NOT_AVAILABLE_YET` with a human-readable
  reason, and the UI renders that reason. We never substitute a plausible value.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# --- availability states -----------------------------------------------------
# Deliberately small. Anything that is not demonstrably true right now is either
# STALE (we had it, it aged out) or NOT_AVAILABLE_YET (we never had it).
VERIFIED = "VERIFIED"
STALE = "STALE"
NOT_AVAILABLE_YET = "NOT_AVAILABLE_YET"

# Subprocess allow-lists. A source may only invoke these verbs. This is a
# defence-in-depth guard so that a future edit cannot smuggle a mutating verb
# (push/commit/merge/checkout, or `gh pr merge`) into an evidence reader.
_GIT_READONLY = frozenset(
    {"rev-parse", "log", "status", "branch", "describe", "config", "remote"}
)
_GH_READONLY = frozenset({"api"})

DEFAULT_TIMEOUT = 6.0


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Fact:
    """A single evidence-bearing value.

    `state` is the honesty contract: the UI must render NOT_AVAILABLE_YET
    visibly rather than showing an empty box that reads as "fine".
    """

    value: Any
    source: str
    state: str = VERIFIED
    captured_at: str = field(default_factory=utcnow_iso)
    reason: str = ""
    ttl_seconds: int = 60

    @classmethod
    def missing(cls, source: str, reason: str) -> "Fact":
        return cls(value=None, source=source, state=NOT_AVAILABLE_YET, reason=reason)

    @property
    def available(self) -> bool:
        return self.state == VERIFIED and self.value is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "source": self.source,
            "state": self.state,
            "captured_at": self.captured_at,
            "reason": self.reason,
            "ttl_seconds": self.ttl_seconds,
        }


# --- tiny TTL cache ----------------------------------------------------------
# Subprocess calls (git, gh) are the slow part of a panel refresh. A short TTL
# keeps the mobile view responsive without ever serving something the user would
# read as "live" when it is minutes old — the age is carried in `captured_at`.

_CACHE: dict[str, tuple[float, Any]] = {}


def cached(key: str, ttl: float, producer: Callable[[], Any]) -> Any:
    now = time.monotonic()
    hit = _CACHE.get(key)
    if hit is not None and (now - hit[0]) < ttl:
        return hit[1]
    value = producer()
    _CACHE[key] = (now, value)
    return value


def cache_clear() -> None:
    _CACHE.clear()


# --- subprocess helpers ------------------------------------------------------


def _run(argv: list[str], cwd: str | None = None, timeout: float = DEFAULT_TIMEOUT):
    """Run a read-only command. Returns (ok, stdout, err_reason)."""
    exe = shutil.which(argv[0])
    if not exe:
        return False, "", f"{argv[0]} not found on PATH"
    try:
        proc = subprocess.run(
            [exe, *argv[1:]],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return False, "", f"{argv[0]} timed out after {timeout}s"
    except OSError as exc:  # pragma: no cover - platform dependent
        return False, "", f"{argv[0]} failed to start: {exc}"
    if proc.returncode != 0:
        return False, proc.stdout, (proc.stderr or proc.stdout or "").strip()[:300]
    return True, proc.stdout, ""


def git(args: list[str], cwd: str, timeout: float = DEFAULT_TIMEOUT):
    if not args or args[0] not in _GIT_READONLY:
        raise ValueError(f"git verb not in read-only allow-list: {args[:1]}")
    return _run(["git", *args], cwd=cwd, timeout=timeout)


def gh(args: list[str], timeout: float = DEFAULT_TIMEOUT):
    if not args or args[0] not in _GH_READONLY:
        raise ValueError(f"gh verb not in read-only allow-list: {args[:1]}")
    return _run(["gh", *args], timeout=timeout)


# --- kanban (control-plane truth) -------------------------------------------

def kanban_db_path() -> Path:
    env = os.environ.get("CONTROL_KANBAN_DB")
    if env:
        return Path(env)
    return (
        Path.home()
        / "AppData"
        / "Local"
        / "hermes"
        / "kanban"
        / "boards"
        / "traficlabpro"
        / "kanban.db"
    )


def _kanban_conn() -> sqlite3.Connection:
    """Open the kanban board strictly read-only.

    `mode=ro` makes SQLite refuse any write at the driver level, so this panel
    can observe the factory without ever being able to perturb it.
    """
    path = kanban_db_path()
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=3.0)
    conn.row_factory = sqlite3.Row
    return conn


def _kanban_query(sql: str, params: tuple = ()) -> tuple[bool, list[dict], str]:
    path = kanban_db_path()
    if not path.exists():
        return False, [], f"kanban DB not found at {path}"
    try:
        conn = _kanban_conn()
    except sqlite3.Error as exc:
        return False, [], f"kanban DB unreadable: {exc}"
    try:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        return True, rows, ""
    except sqlite3.Error as exc:
        return False, [], f"kanban query failed: {exc}"
    finally:
        conn.close()


def _epoch_to_iso(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def active_tasks() -> Fact:
    """Tasks the factory is working on right now (running / ready / review)."""
    src = f"kanban.db:tasks @ {kanban_db_path()}"
    ok, rows, err = _kanban_query(
        "SELECT id, title, assignee, status, created_at, started_at, "
        "       current_run_id, workspace_path, block_kind "
        "FROM tasks WHERE status IN ('running','ready','review') "
        "ORDER BY (status='running') DESC, created_at DESC LIMIT 10"
    )
    if not ok:
        return Fact.missing(src, err)
    for r in rows:
        r["created_at_iso"] = _epoch_to_iso(r.get("created_at"))
        r["started_at_iso"] = _epoch_to_iso(r.get("started_at"))
    return Fact(value=rows, source=src)


def blocked_tasks() -> Fact:
    """Tasks stopped waiting on a human decision — the Human-Go queue's core."""
    src = f"kanban.db:tasks @ {kanban_db_path()}"
    ok, rows, err = _kanban_query(
        "SELECT id, title, assignee, status, block_kind, last_failure_error, "
        "       created_at, completed_at "
        "FROM tasks WHERE status='blocked' ORDER BY created_at DESC LIMIT 25"
    )
    if not ok:
        return Fact.missing(src, err)
    for r in rows:
        r["created_at_iso"] = _epoch_to_iso(r.get("created_at"))
    return Fact(value=rows, source=src)


def task_status_counts() -> Fact:
    src = f"kanban.db:tasks @ {kanban_db_path()}"
    ok, rows, err = _kanban_query(
        "SELECT status, COUNT(*) AS n FROM tasks GROUP BY status ORDER BY n DESC"
    )
    if not ok:
        return Fact.missing(src, err)
    return Fact(value={r["status"]: r["n"] for r in rows}, source=src)


def recent_events(limit: int = 40) -> Fact:
    """Raw factory lifecycle events, newest first — the Evidence Timeline spine."""
    src = f"kanban.db:task_events @ {kanban_db_path()}"
    ok, rows, err = _kanban_query(
        "SELECT e.id, e.task_id, e.run_id, e.kind, e.payload, e.created_at, "
        "       t.title AS task_title, t.assignee "
        "FROM task_events e LEFT JOIN tasks t ON t.id = e.task_id "
        "ORDER BY e.id DESC LIMIT ?",
        (int(limit),),
    )
    if not ok:
        return Fact.missing(src, err)
    for r in rows:
        r["created_at_iso"] = _epoch_to_iso(r.get("created_at"))
    return Fact(value=rows, source=src)


def latest_run_summary(task_id: str) -> Fact:
    src = f"kanban.db:task_runs @ {kanban_db_path()}"
    ok, rows, err = _kanban_query(
        "SELECT id, task_id, profile, status, outcome, summary, started_at, "
        "       ended_at, last_heartbeat_at, worker_pid "
        "FROM task_runs WHERE task_id=? ORDER BY id DESC LIMIT 1",
        (task_id,),
    )
    if not ok:
        return Fact.missing(src, err)
    if not rows:
        return Fact.missing(src, f"no runs recorded for {task_id}")
    row = rows[0]
    row["started_at_iso"] = _epoch_to_iso(row.get("started_at"))
    row["last_heartbeat_at_iso"] = _epoch_to_iso(row.get("last_heartbeat_at"))
    return Fact(value=row, source=src)


# --- git (local repo truth) --------------------------------------------------

def repo_root() -> Path:
    env = os.environ.get("CONTROL_REPO_ROOT")
    if env:
        return Path(env)
    # control/bff/sources.py -> control/bff -> control -> <repo root>
    return Path(__file__).resolve().parent.parent.parent


def git_snapshot() -> Fact:
    """Branch, HEAD SHA, dirty-file count and subject for the control repo."""
    root = repo_root()
    src = f"git @ {root}"
    if not (root / ".git").exists():
        return Fact.missing(src, f"no .git at {root}")

    ok, head, err = git(["rev-parse", "HEAD"], cwd=str(root))
    if not ok:
        return Fact.missing(src, err or "git rev-parse HEAD failed")
    ok_b, branch, _ = git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=str(root))
    ok_s, dirty, _ = git(["status", "--porcelain"], cwd=str(root))
    ok_l, subject, _ = git(["log", "-1", "--pretty=%s"], cwd=str(root))
    ok_d, when, _ = git(["log", "-1", "--pretty=%cI"], cwd=str(root))

    dirty_files = [ln[3:] for ln in dirty.splitlines() if ln.strip()] if ok_s else []
    return Fact(
        value={
            "repo_root": str(root),
            "branch": branch.strip() if ok_b else "",
            "head_sha": head.strip(),
            "head_sha_short": head.strip()[:12],
            "head_subject": subject.strip() if ok_l else "",
            "head_committed_at": when.strip() if ok_d else "",
            "dirty_file_count": len(dirty_files),
            "dirty_files": dirty_files[:20],
            "clean": len(dirty_files) == 0,
        },
        source=src,
        ttl_seconds=30,
    )


# --- github (remote truth) ---------------------------------------------------
# Uses the `gh` CLI, which holds its own credential in the OS keyring. The BFF
# therefore never loads, stores, or forwards a GitHub token, and the browser
# never sees one — it only ever receives the parsed read model.

CONTROL_REPO = os.environ.get("CONTROL_GH_REPO", "neokyhurtado-cmd/traficlab-factory")
IA_VISION_REPO = os.environ.get("CONTROL_GH_IA_REPO", "neokyhurtado-cmd/IA-VISION")
SUINI_REPO = os.environ.get("CONTROL_GH_SUINI_REPO", "neokyhurtado-cmd/suini")


def _gh_json(path: str, jq: str | None = None, ttl: float = 60.0):
    key = f"gh:{path}:{jq or ''}"

    def _produce():
        args = ["api", path]
        if jq:
            args += ["--jq", jq]
        ok, out, err = gh(args)
        return ok, out, err

    return cached(key, ttl, _produce)


def open_pull_requests() -> Fact:
    src = f"gh api repos/{CONTROL_REPO}/pulls?state=open"
    # NOTE: the *list* endpoint does not compute `mergeable_state` — GitHub only
    # fills that on the single-PR endpoint. Asking for it here would return null
    # for every PR and the panel would render a misleading "unknown mergeability"
    # badge, so we don't request it at all. Draft status IS available and is the
    # signal that actually matters for a merge gate.
    ok, out, err = _gh_json(
        f"repos/{CONTROL_REPO}/pulls?state=open&per_page=20",
        ".[] | {number,title,state,draft,"
        "head:.head.ref,head_sha:.head.sha,base:.base.ref,"
        "user:.user.login,updated_at,url:.html_url}",
    )
    if not ok:
        return Fact.missing(src, err or "gh api failed (not installed / not authenticated)")
    items = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return Fact(value=items, source=src, ttl_seconds=60)


def remote_head(repo: str) -> Fact:
    src = f"gh api repos/{repo}/commits/main"
    ok, out, err = _gh_json(f"repos/{repo}/commits/main", ".sha", ttl=120.0)
    if not ok:
        return Fact.missing(src, err or "gh api failed (not installed / not authenticated)")
    sha = out.strip()
    if not sha:
        return Fact.missing(src, "empty sha from gh")
    return Fact(value=sha, source=src, ttl_seconds=120)


def ci_status(sha_fact: Fact) -> Fact:
    """Combined CI state for a SHA.

    GitHub returns `state == "pending"` both for "a check is running" and for
    "no checks are configured at all". Those mean very different things to a
    human reading a panel, so we split them: zero statuses becomes an explicit
    NOT_AVAILABLE_YET ("no CI configured") rather than a misleading amber dot.
    """
    if not sha_fact.available:
        return Fact.missing("gh api commits/status", "no SHA to query CI for")
    sha = str(sha_fact.value)
    src = f"gh api repos/{CONTROL_REPO}/commits/{sha[:12]}/status"
    ok, out, err = _gh_json(
        f"repos/{CONTROL_REPO}/commits/{sha}/status",
        "{state:.state,total:(.statuses|length)}",
        ttl=60.0,
    )
    if not ok:
        return Fact.missing(src, err or "gh api failed")
    try:
        data = json.loads(out.strip() or "{}")
    except json.JSONDecodeError:
        return Fact.missing(src, "unparseable gh response")
    if int(data.get("total") or 0) == 0:
        return Fact.missing(src, "no CI checks configured for this repo/SHA")
    return Fact(value=data, source=src, ttl_seconds=60)


# --- runtime probes ----------------------------------------------------------

def probe_tcp(url: str, timeout: float = 0.4) -> bool:
    import socket
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False
