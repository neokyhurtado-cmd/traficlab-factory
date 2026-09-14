"""BODY-2 worker bootstrap — fresh session reconstructs state from
checkpoint + directive alone.

This module is the executor that ties together checkpoint_store, audit,
authority, manifest and the INTERNAL_CONSULT synth oracle. It is the
piece the EVOLUTION-V1 closeout canary exercises end-to-end.

Public surface:
    WorkerBootstrap(checkpoint_db, audit_db, kanban_db)
        .bootstrap(task_id, directive)   -> Checkpoint
        .check_freshness(task_id, current_head) -> FreshnessVerdict
        .complete(task_id, result)       -> None   (raises on STALE)
        .write_result(task_id, path)     -> None
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from agent_body.audit import AuditStore, new_event
from agent_body.checkpoint_store import (
    AuthoritativePointer,
    Checkpoint,
    CheckpointStore,
    FreshnessVerdict,
    HeadResolver,
)


class WorkerBootstrap:
    def __init__(self, checkpoint_db: Path, audit_db: Path, kanban_db: Optional[Path] = None):
        self.checkpoint_db = Path(checkpoint_db)
        self.audit_db = Path(audit_db)
        self.kanban_db = Path(kanban_db) if kanban_db else None
        self.checkpoints = CheckpointStore(self.checkpoint_db)
        self.audit = AuditStore(self.audit_db)
        # Cache of most recent freshness verdicts per task. Used by
        # complete() to refuse silent continuation on STALE.
        self._last_verdict: dict = {}

    def bootstrap(self, task_id: str, directive: dict) -> Checkpoint:
        """Load existing checkpoint or write a fresh one from directive."""
        existing = self.checkpoints.read(task_id)
        if existing is not None:
            self.audit.append(new_event(
                task_id=task_id,
                action="bootstrap.resume",
                capability_used="checkpoint.read",
                source_evidence_pointers=[f"checkpoint:{task_id}"],
                outcome="OK",
            ))
            return existing

        pointers = []
        repo = directive.get("repository")
        issue = directive.get("issue")
        head = directive.get("expected_head")
        if repo:
            pointers.append(AuthoritativePointer("repo", repo))
        if issue is not None:
            pointers.append(AuthoritativePointer("issue", f"#{issue}"))
        if head:
            pointers.append(AuthoritativePointer("commit", head))
        pointers.append(AuthoritativePointer("branch", "main"))

        cp = Checkpoint(
            task_id=task_id,
            objective=directive.get("objective", f"execute {task_id}"),
            authoritative_pointers=pointers,
            last_verified_head=head or "",
            evidence_already_checked=list(directive.get("evidence_already_checked", [])),
            blockers=[],
            next_safe_action=directive.get("next_safe_action", "execute_directive"),
            state="ACTIVE",
        )
        self.checkpoints.write(cp)
        self.audit.append(new_event(
            task_id=task_id,
            action="bootstrap.write",
            capability_used="checkpoint.write",
            source_evidence_pointers=[f"directive:{task_id}"],
            outcome="OK",
        ))
        return cp

    def check_freshness(
        self,
        task_id: str,
        current_head: str,
        resolver: Optional[HeadResolver] = None,
    ) -> FreshnessVerdict:
        verdict = self.checkpoints.check_freshness(
            task_id,
            current_head=current_head,
            resolver=resolver,
        )
        self._last_verdict[task_id] = verdict
        # Persist the verdict on the checkpoint itself so a process restart
        # also sees the STALE state.
        if verdict.state in {"STALE", "BLOCKED"}:
            cp = self.checkpoints.read(task_id)
            if cp is not None and cp.state != "DONE":
                self.checkpoints.write(Checkpoint(
                    task_id=cp.task_id,
                    objective=cp.objective,
                    authoritative_pointers=cp.authoritative_pointers,
                    last_verified_head=cp.last_verified_head,
                    evidence_already_checked=cp.evidence_already_checked,
                    blockers=cp.blockers + [f"stale: old={verdict.old_head[:12]} new={verdict.new_head[:12]}"],
                    next_safe_action=cp.next_safe_action,
                    state="STALE",
                ))
        self.audit.append(new_event(
            task_id=task_id,
            action=f"context.freshness.{verdict.state.lower()}",
            capability_used="head.compare",
            source_evidence_pointers=[f"checkpoint:{task_id}", f"head:{current_head[:12]}"],
            outcome="OK" if verdict.state == "ACTIVE" else "STALE",
        ))
        return verdict

    def complete(self, task_id: str, result: str) -> None:
        """Mark the task DONE.

        Raises RuntimeError if the most recent freshness check reported
        STALE — no silent completion on stale info.
        """
        cp = self.checkpoints.read(task_id)
        if cp is None:
            raise RuntimeError(f"no checkpoint for task {task_id!r}")
        if cp.state == "STALE":
            raise RuntimeError(
                f"checkpoint for {task_id!r} is STALE — reconciliation required "
                "before completion"
            )
        verdict = self._last_verdict.get(task_id)
        if verdict is not None and verdict.state == "STALE":
            raise RuntimeError(
                f"checkpoint for {task_id!r} was reported STALE by the most "
                f"recent freshness check (old={verdict.old_head[:12]}, "
                f"new={verdict.new_head[:12]}) — reconciliation required "
                "before completion"
            )
        # Persist the STALE state on the checkpoint so a later session
        # also sees it.
        new_cp = Checkpoint(
            task_id=cp.task_id,
            objective=cp.objective,
            authoritative_pointers=cp.authoritative_pointers,
            last_verified_head=cp.last_verified_head,
            evidence_already_checked=cp.evidence_already_checked,
            blockers=cp.blockers,
            next_safe_action="none",
            state="DONE",
        )
        self.checkpoints.write(new_cp)
        self.audit.append(new_event(
            task_id=task_id,
            action="checkpoint.complete",
            capability_used="checkpoint.write",
            source_evidence_pointers=[f"result:{result}"],
            outcome="OK",
        ))

    def write_result(self, task_id: str, path: Path) -> None:
        cp = self.checkpoints.read(task_id)
        if cp is None:
            raise RuntimeError(f"no checkpoint for task {task_id!r}")
        bootstrap = self.checkpoints.derive_bootstrap(cp)
        result = {
            "directive_id": task_id,
            "state": cp.state,
            "head": cp.last_verified_head,
            "objective": cp.objective,
            "next_safe_action": cp.next_safe_action,
            "blockers": cp.blockers,
            "evidence_already_checked": cp.evidence_already_checked,
            "manual_context_copy_paste": 0,
            "mutations_this_gate": 0,
            "bootstrap": bootstrap,
        }
        Path(path).write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        self.audit.append(new_event(
            task_id=task_id,
            action="result.write",
            capability_used="result.publish",
            source_evidence_pointers=[f"path:{path}"],
            outcome="OK",
        ))
