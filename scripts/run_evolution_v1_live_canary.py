"""EVOLUTION_V1_LIVE_CANARY — real chained session A → session B.

Per directive `evolution-v1-role-whitelist-fix-20260914-01` (issue #27
comment 5659883818), the live canary MUST prove:

  1. Session A writes a checkpoint with project/task/HEAD/authority/blocker
     /next_safe_action, then exits.
  2. Session B starts with NO chat history, NO David briefing, NO in-process
     state from A. B recovers everything from the durable checkpoint.
  3. B queries the LIVE GitHub HEAD via real git plumbing (not a stub).
  4. STALE case — a checkpoint pinned to an OLD HEAD while GitHub has
     advanced → B reports STALE + reconciliation_required + allowed_to_continue=False.
  5. ACTOR_UNVERIFIED case — a tampered review (wrong COMMIT_SHA) is rejected
     and cannot influence the 4-role consult decision.
  6. 4 canonical roles → AUTO_GO via synthesize().

This script is the live canary. It writes a real SQLite checkpoint,
opens a fresh process (subprocess) to simulate session B with no
in-process state from A, and exercises every chain link. Output is
deterministic and machine-parseable.

Usage:
    python scripts/run_evolution_v1_live_canary.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
CANARY_DIR = REPO_ROOT / "evidence" / "evolution_v1_live_canary"


def _run(cmd, **kwargs):
    return subprocess.run(
        cmd,
        shell=isinstance(cmd, str),
        capture_output=True,
        text=True,
        **kwargs,
    )


def _git_head() -> str:
    """Real live HEAD via git plumbing — no cache."""
    r = _run(["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT))
    if r.returncode != 0:
        raise RuntimeError(f"git rev-parse failed: {r.stderr}")
    return r.stdout.strip()


def _git_short_sha(sha: str) -> str:
    r = _run(["git", "rev-parse", "--short", sha], cwd=str(REPO_ROOT))
    return r.stdout.strip() if r.returncode == 0 else sha[:7]


def _log(canary_dir: Path, event: str, payload: dict) -> None:
    canary_dir.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"event": event, "ts": time.time(), **payload}, sort_keys=True)
    with (canary_dir / "canary.log").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _step(canary_dir: Path, label: str, ok: bool, **payload) -> bool:
    _log(canary_dir, label, {"ok": ok, **payload})
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {label}: {json.dumps(payload, sort_keys=True)}")
    return ok


def _session_a_writes_checkpoint(checkpoint_db: Path, head: str) -> dict:
    """Session A — write a checkpoint, then exit (no return state).

    Returns the task_id so session B can recover it.
    """
    script = textwrap.dedent(f"""
        import sys, json
        from pathlib import Path
        sys.path.insert(0, r"{REPO_ROOT}")
        from agent_body.checkpoint_store import (
            CheckpointStore, Checkpoint, AuthoritativePointer
        )
        db = Path(r"{checkpoint_db}")
        if db.exists():
            db.unlink()
        store = CheckpointStore(db)
        cp = Checkpoint(
            task_id="t_evolution_v1_live_canary",
            objective="Resume #27 evolution closeout from durable sidecar.",
            authoritative_pointers=[
                AuthoritativePointer("repo", "neokyhurtado-cmd/traficlab-factory"),
                AuthoritativePointer("issue", "#27"),
                AuthoritativePointer("commit", "{head}"),
                AuthoritativePointer("branch", "main"),
            ],
            last_verified_head="{head}",
            evidence_already_checked=[5658210225, 5659485468, 5659883818],
            blockers=[],
            next_safe_action="post_evolution_v1_fixed_to_issue_27",
            state="ACTIVE",
        )
        store.write(cp)
        # Session A exits with NOTHING in memory — only the durable file.
        print(json.dumps({{
            "wrote": True,
            "head": "{head}",
            "db": str(db),
            "task_id": cp.task_id,
        }}))
    """)
    r = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"session A failed: {r.stderr}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def _session_b_recovers(checkpoint_db: Path, task_id: str) -> dict:
    """Session B — fresh process, no chat, no in-memory state.

    Reads the durable checkpoint and recovers the bootstrap shape.
    """
    script = textwrap.dedent(f"""
        import sys, json
        from pathlib import Path
        sys.path.insert(0, r"{REPO_ROOT}")
        from agent_body.checkpoint_store import CheckpointStore, CheckpointStore, HeadResolver
        db = Path(r"{checkpoint_db}")
        store = CheckpointStore(db)
        cp = store.read("{task_id}")
        if cp is None:
            print(json.dumps({{"recovered": False}}))
            sys.exit(2)
        bootstrap = store.derive_bootstrap(cp)
        # Live freshness check — call resolver with REAL git rev-parse.
        def real_head():
            import subprocess
            return subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=r"{REPO_ROOT}",
                capture_output=True, text=True,
            ).stdout.strip()
        resolver = HeadResolver(real_head)
        verdict = store.check_freshness("{task_id}", resolver.resolve(), resolver)
        print(json.dumps({{
            "recovered": True,
            "task_id": cp.task_id,
            "head": cp.last_verified_head,
            "state": cp.state,
            "next_safe_action": cp.next_safe_action,
            "bootstrap": bootstrap,
            "freshness": {{
                "state": verdict.state,
                "reconciliation_required": verdict.reconciliation_required,
                "allowed_to_continue": verdict.allowed_to_continue,
                    "old_head": verdict.old_head,
                    "new_head": verdict.new_head,
                }},
            }}, sort_keys=True))
    """)
    r = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"session B recovery failed: {r.stderr}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def _session_b_stale_check(checkpoint_db: Path, task_id: str, fake_old_head: str) -> dict:
    """STALE: write a checkpoint pinned to fake_old_head, then check."""
    script = textwrap.dedent(f"""
        import subprocess  # noqa: F401  (needed by inline call)
        import sys, json
        from pathlib import Path
        sys.path.insert(0, r"{REPO_ROOT}")
        from agent_body.checkpoint_store import CheckpointStore, Checkpoint, AuthoritativePointer, HeadResolver
        db = Path(r"{checkpoint_db}")
        store = CheckpointStore(db)
        # Force a stale head by writing a new checkpoint with an OLD head.
        store.write(Checkpoint(
            task_id="{task_id}",
            objective="stale test",
            authoritative_pointers=[
                AuthoritativePointer("repo", "neokyhurtado-cmd/traficlab-factory"),
                AuthoritativePointer("issue", "#27"),
                AuthoritativePointer("commit", "{fake_old_head}"),
                AuthoritativePointer("branch", "main"),
            ],
            last_verified_head="{fake_old_head}",
            evidence_already_checked=[],
            blockers=[],
            next_safe_action="reconcile",
            state="STALE",
        ))
        # Resolve LIVE head.
        live_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=r"{REPO_ROOT}",
            capture_output=True, text=True,
        ).stdout.strip()
        verdict = store.check_freshness("{task_id}", live_head, HeadResolver(lambda: live_head))
        print(json.dumps({{
            "old_head": verdict.old_head,
            "new_head": verdict.new_head,
            "state": verdict.state,
            "reconciliation_required": verdict.reconciliation_required,
            "allowed_to_continue": verdict.allowed_to_continue,
        }}, sort_keys=True))
    """)
    r = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"STALE check failed: {r.stderr}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def _session_b_consult_with_tampered_review() -> dict:
    """Run a 4-role consult where ONE review has a tampered COMMIT_SHA."""
    script = textwrap.dedent(f"""
        import sys, json
        sys.path.insert(0, r"{REPO_ROOT}")
        from agent_body.internal_consult_synth import synthesize
        import subprocess
        live_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=r"{REPO_ROOT}",
            capture_output=True, text=True,
        ).stdout.strip()
        bundle = {{
            "QUERY_ID": "evolution_v1_live_canary_20260914",
            "REPOSITORY": "neokyhurtado-cmd/traficlab-factory",
            "ISSUE_OR_PR": "#27",
            "COMMIT_SHA": live_head,
            "REVERSIBLE": True,
            "CRITICAL_GATE": False,
            "HUMAN_GATE": False,
        }}
        def review(role, decision="GO", risk="LOW", sha=None):
            return {{
                "role": role,
                "decision": decision,
                "risk": risk,
                "confidence": 0.9,
                "counterexample": None,
                "evidence": ["agent_body/tests/"],
                "query_id": bundle["QUERY_ID"],
                "repository": bundle["REPOSITORY"],
                "issue_or_pr": bundle["ISSUE_OR_PR"],
                "commit_sha": sha or bundle["COMMIT_SHA"],
            }}
        # 4 canonical reviews; RED_TEAM is tampered (wrong SHA).
        reviews = [
            review("ARCHITECT"),
            review("EVIDENCE"),
            review("RED_TEAM", sha="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"),
            review("TEST_ORACLE"),
        ]
        decision = synthesize(bundle, reviews=reviews)
        print(json.dumps(decision, default=str, sort_keys=True))
    """)
    r = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"consult failed: {r.stderr}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def _session_b_consult_2canonical_plus_tampered() -> dict:
    """2 canonical roles + 1 tampered → quorum 2 < min_quorum 3 → SECOND_ROUND."""
    script = textwrap.dedent(f"""
        import sys, json
        sys.path.insert(0, r"{REPO_ROOT}")
        from agent_body.internal_consult_synth import synthesize
        import subprocess
        live_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=r"{REPO_ROOT}",
            capture_output=True, text=True,
        ).stdout.strip()
        bundle = {{
            "QUERY_ID": "evolution_v1_live_canary_20260914",
            "REPOSITORY": "neokyhurtado-cmd/traficlab-factory",
            "ISSUE_OR_PR": "#27",
            "COMMIT_SHA": live_head,
            "REVERSIBLE": True,
            "CRITICAL_GATE": False,
            "HUMAN_GATE": False,
        }}
        def review(role, sha=None):
            return {{
                "role": role,
                "decision": "GO",
                "risk": "LOW",
                "confidence": 0.9,
                "counterexample": None,
                "evidence": ["agent_body/tests/"],
                "query_id": bundle["QUERY_ID"],
                "repository": bundle["REPOSITORY"],
                "issue_or_pr": bundle["ISSUE_OR_PR"],
                "commit_sha": sha or bundle["COMMIT_SHA"],
            }}
        reviews = [
            review("ARCHITECT"),
            review("EVIDENCE"),
            review("RED_TEAM", sha="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"),
        ]
        decision = synthesize(bundle, reviews=reviews)
        print(json.dumps(decision, default=str, sort_keys=True))
    """)
    r = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"2+1 consult failed: {r.stderr}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def _session_b_consult_4_canonical() -> dict:
    """4 canonical roles, no counterexample → AUTO_GO expected."""
    script = textwrap.dedent(f"""
        import sys, json
        sys.path.insert(0, r"{REPO_ROOT}")
        from agent_body.internal_consult_synth import synthesize
        import subprocess
        live_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=r"{REPO_ROOT}",
            capture_output=True, text=True,
        ).stdout.strip()
        bundle = {{
            "QUERY_ID": "evolution_v1_live_canary_20260914",
            "REPOSITORY": "neokyhurtado-cmd/traficlab-factory",
            "ISSUE_OR_PR": "#27",
            "COMMIT_SHA": live_head,
            "REVERSIBLE": True,
            "CRITICAL_GATE": False,
            "HUMAN_GATE": False,
        }}
        def review(role):
            return {{
                "role": role,
                "decision": "GO",
                "risk": "LOW",
                "confidence": 0.9,
                "counterexample": None,
                "evidence": ["agent_body/tests/"],
                "query_id": bundle["QUERY_ID"],
                "repository": bundle["REPOSITORY"],
                "issue_or_pr": bundle["ISSUE_OR_PR"],
                "commit_sha": bundle["COMMIT_SHA"],
            }}
        reviews = [review(r) for r in ("ARCHITECT", "EVIDENCE", "RED_TEAM", "TEST_ORACLE")]
        decision = synthesize(bundle, reviews=reviews)
        print(json.dumps(decision, default=str, sort_keys=True))
    """)
    r = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"4-role consult failed: {r.stderr}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def main() -> int:
    print(f"Repo: {REPO_ROOT}")
    print(f"Canary evidence dir: {CANARY_DIR}")
    if CANARY_DIR.exists():
        shutil.rmtree(CANARY_DIR)
    CANARY_DIR.mkdir(parents=True, exist_ok=True)

    live_head = _git_head()
    print(f"Live HEAD: {_git_short_sha(live_head)} ({live_head})")
    all_ok = True

    with tempfile.TemporaryDirectory() as td:
        cp_db = Path(td) / "session_a.sqlite"
        cp_db_b = Path(td) / "session_b.sqlite"

        # ---- SESSION A: writes checkpoint ----
        try:
            session_a = _session_a_writes_checkpoint(cp_db, live_head)
            all_ok &= _step(CANARY_DIR, "session_a_writes_checkpoint",
                            ok=True,
                            wrote=session_a["wrote"],
                            task_id=session_a["task_id"],
                            head=session_a["head"],
                            db=session_a["db"])
        except Exception as exc:
            all_ok &= _step(CANARY_DIR, "session_a_writes_checkpoint", ok=False, error=str(exc))
            return 1

        # Copy the durable file to a new location so session B truly
        # cannot see session A's in-memory state (separate process + file).
        shutil.copy2(cp_db, cp_db_b)
        task_id = session_a["task_id"]

        # ---- SESSION B: fresh process recovers ----
        try:
            session_b = _session_b_recovers(cp_db_b, task_id)
            all_ok &= _step(
                CANARY_DIR, "session_b_recovers_from_durable_checkpoint",
                ok=session_b["recovered"],
                bootstrap_keys=sorted(session_b.get("bootstrap", {}).keys()),
                head=session_b.get("head"),
                state=session_b.get("state"),
                freshness_state=session_b.get("freshness", {}).get("state"),
                allowed_to_continue=session_b.get("freshness", {}).get("allowed_to_continue"),
            )
        except Exception as exc:
            all_ok &= _step(CANARY_DIR, "session_b_recovers_from_durable_checkpoint",
                            ok=False, error=str(exc))
            return 1

        # ---- STALE check: pin checkpoint to an old HEAD, verify fail-closed ----
        try:
            stale = _session_b_stale_check(cp_db_b, task_id, "8e2d9c9ae3e73c70ef03f718773fb8773724753e")
            all_ok &= _step(
                CANARY_DIR, "stale_check_returns_freshness_state_stale",
                ok=(stale["state"] == "STALE"
                    and stale["reconciliation_required"] is True
                    and stale["allowed_to_continue"] is False),
                old_head=stale["old_head"][:10],
                new_head=stale["new_head"][:10],
                state=stale["state"],
                reconciliation_required=stale["reconciliation_required"],
                allowed_to_continue=stale["allowed_to_continue"],
            )
        except Exception as exc:
            all_ok &= _step(CANARY_DIR, "stale_check_returns_freshness_state_stale",
                            ok=False, error=str(exc))
            return 1

        # ---- ACTOR_UNVERIFIED: tampered review cannot influence the decision ----
        # 4 canonical roles submitted, RED_TEAM has wrong COMMIT_SHA.
        # Expected: RED_TEAM is surfaced as actor_unverified, the 3 remaining
        # valid roles (ARCHITECT, EVIDENCE, TEST_ORACLE) form quorum=3 =
        # min_quorum → AUTO_GO. The crucial invariant is that the tampered
        # role NEVER appears in review_roles (the valid-vote set).
        try:
            tampered = _session_b_consult_with_tampered_review()
            all_ok &= _step(
                CANARY_DIR, "tampered_review_surfaced_as_actor_unverified",
                ok=("RED_TEAM" in tampered["actor_unverified"]
                    and "RED_TEAM" not in tampered["review_roles"]),
                action=tampered["action"],
                quorum_size=tampered["quorum_size"],
                actor_unverified=tampered["actor_unverified"],
                review_roles=sorted(tampered["review_roles"]),
                note="3 canonical valid votes (quorum=3 == min_quorum) → AUTO_GO is correct; tampered role excluded from vote set",
            )
        except Exception as exc:
            all_ok &= _step(CANARY_DIR, "tampered_review_surfaced_as_actor_unverified",
                            ok=False, error=str(exc))
            return 1

        # ---- Boundary: ONLY 2 canonical + 1 tampered → must NOT reach AUTO_GO ----
        # This is the headline sabotage the role-whitelist fix protects
        # against: with min_quorum=3, 2 canonical alone must never produce
        # AUTO_GO regardless of who else is in the mix.
        try:
            boundary = _session_b_consult_2canonical_plus_tampered()
            all_ok &= _step(
                CANARY_DIR, "two_canonical_plus_tampered_cannot_reach_auto_go",
                ok=(boundary["action"] != "AUTO_GO"
                    and boundary["quorum_size"] == 2
                    and "RED_TEAM" in boundary["actor_unverified"]),
                action=boundary["action"],
                quorum_size=boundary["quorum_size"],
                review_roles=sorted(boundary["review_roles"]),
                actor_unverified=boundary["actor_unverified"],
            )
        except Exception as exc:
            all_ok &= _step(CANARY_DIR, "two_canonical_plus_tampered_cannot_reach_auto_go",
                            ok=False, error=str(exc))
            return 1

        # ---- 4 canonical roles → AUTO_GO ----
        try:
            clean = _session_b_consult_4_canonical()
            all_ok &= _step(
                CANARY_DIR, "four_canonical_roles_yield_auto_go",
                ok=(clean["action"] == "AUTO_GO"
                    and clean["quorum_size"] == 4
                    and clean["actor_unverified"] == []),
                action=clean["action"],
                quorum_size=clean["quorum_size"],
                review_roles=sorted(clean["review_roles"]),
                max_risk=clean["max_risk"],
            )
        except Exception as exc:
            all_ok &= _step(CANARY_DIR, "four_canonical_roles_yield_auto_go",
                            ok=False, error=str(exc))
            return 1

    # ---- Final summary ----
    summary = {
        "all_ok": all_ok,
        "live_head": live_head,
        "live_head_short": _git_short_sha(live_head),
        "evidence_dir": str(CANARY_DIR),
    }
    (CANARY_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    _log(CANARY_DIR, "summary", summary)

    print("\n=== EVOLUTION_V1_LIVE_CANARY ===")
    print(json.dumps(summary, indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())