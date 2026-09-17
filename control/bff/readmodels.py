"""Read models for Mission Control, Evidence Timeline and the Human-Go Inbox.

These compose `sources.Fact` objects into the shapes the panel renders. Three
rules hold everywhere in this module and the tests enforce them:

1. **Every rendered field carries provenance.** A model field is either a
   `Fact` dict (value + source + state + captured_at) or a plain scalar that is
   derived purely from Facts already present in the same payload.

2. **Absence is displayed, never faked.** If a source is down the field's state
   is `NOT_AVAILABLE_YET` with a reason string. No default value is invented to
   fill the hole. This is the WO's "or NOT_AVAILABLE_YET visible" requirement.

3. **No product mutation, ever.** These models read IA-VISION and SUINI status.
   They expose no field, and offer no endpoint, that writes to either product.

Schema: control-read-model/v1.1.0 (additive over v1.0.0 — v1.0.0 models are
untouched, so existing consumers keep working).
"""
from __future__ import annotations

import json
from typing import Any

from sources import (  # type: ignore[import-not-found]
    CONTROL_REPO,
    IA_VISION_REPO,
    NOT_AVAILABLE_YET,
    SUINI_REPO,
    Fact,
    active_tasks,
    blocked_tasks,
    ci_status,
    git_snapshot,
    latest_run_summary,
    open_pull_requests,
    probe_tcp,
    recent_events,
    remote_head,
    task_status_counts,
    utcnow_iso,
)

SCHEMA_VERSION = "control-read-model/v1.1.0"

# Events that mean "the factory needs a human", used by the Human-Go Inbox.
HUMAN_GO_EVENT_KINDS = frozenset({"blocked", "RECOVERY_REQUIRED", "gave_up", "crashed"})

# block_kind values that genuinely require David, versus ones the factory
# resolves on its own. `dependency` waits on another task and auto-resumes;
# `transient` may clear by itself. Only the other two need a human.
HUMAN_BLOCKING_KINDS = frozenset({"needs_input", "capability"})

# How each raw kanban event kind is presented in the timeline.
_EVENT_PRESENTATION: dict[str, tuple[str, str]] = {
    "created": ("neutral", "Tarea creada"),
    "claimed": ("neutral", "Worker reclamó la tarea"),
    "spawned": ("neutral", "Worker arrancó"),
    "heartbeat": ("muted", "Latido del worker"),
    "commented": ("neutral", "Comentario"),
    "attached": ("neutral", "Adjunto"),
    "promoted": ("neutral", "Promovida a ready"),
    "unblocked": ("good", "Desbloqueada"),
    "completed": ("good", "Completada"),
    "archived": ("muted", "Archivada"),
    "blocked": ("warn", "BLOQUEADA — requiere decisión"),
    "crashed": ("bad", "Worker cayó"),
    "gave_up": ("bad", "Reintentos agotados"),
    "reclaimed": ("warn", "Reclamada tras quedar colgada"),
    "RECOVERY_REQUIRED": ("bad", "Recuperación requerida"),
    "WO_ROUTING_DENIED": ("bad", "Routing denegado (cross-product)"),
    "ORCH_INBOUND_WO": ("neutral", "Work Order entrante"),
    "ORCH_NOTIFY_DELIVERED": ("good", "Notificación entregada"),
    "tip_scratch_workspace": ("muted", "Nota de workspace"),
}


def _present(kind: str) -> tuple[str, str]:
    return _EVENT_PRESENTATION.get(kind, ("neutral", kind))


def _short(text: str | None, limit: int = 160) -> str:
    if not text:
        return ""
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


# ---------------------------------------------------------------------------
# Mission Control
# ---------------------------------------------------------------------------

def mission_control() -> dict[str, Any]:
    """One screen answering: what is running, on what code, is it green, who owns it.

    Every block degrades independently. If GitHub is unreachable the git block
    still renders; if the kanban DB is missing the PR block still renders. A
    partial panel with honest holes beats an all-or-nothing error page.
    """
    git_fact = git_snapshot()
    prs_fact = open_pull_requests()
    tasks_fact = active_tasks()
    counts_fact = task_status_counts()

    head_fact: Fact
    if git_fact.available:
        head_fact = Fact(
            value=git_fact.value["head_sha"],
            source=git_fact.source,
            captured_at=git_fact.captured_at,
        )
    else:
        head_fact = Fact.missing(git_fact.source, git_fact.reason)
    ci_fact = ci_status(head_fact)

    # Current goal = the running task if there is one, else the newest ready one.
    goal: dict[str, Any] | None = None
    if tasks_fact.available and tasks_fact.value:
        rows = tasks_fact.value
        current = next((r for r in rows if r["status"] == "running"), rows[0])
        run_fact = latest_run_summary(current["id"])
        run = run_fact.value if run_fact.available else None
        goal = {
            "task_id": current["id"],
            "title": current["title"],
            "assignee": current.get("assignee") or "unassigned",
            "status": current["status"],
            "started_at": current.get("started_at_iso"),
            "created_at": current.get("created_at_iso"),
            "workspace": current.get("workspace_path") or "",
            "run": {
                "run_id": run.get("id") if run else None,
                "profile": run.get("profile") if run else None,
                "status": run.get("status") if run else None,
                "outcome": run.get("outcome") if run else None,
                "worker_pid": run.get("worker_pid") if run else None,
                "last_heartbeat_at": run.get("last_heartbeat_at_iso") if run else None,
                "summary": _short(run.get("summary")) if run else "",
            }
            if run
            else None,
            "run_provenance": run_fact.to_dict(),
        }

    queue = {"running": 0, "ready": 0, "review": 0, "blocked": 0, "done": 0}
    if counts_fact.available:
        for key in queue:
            queue[key] = int(counts_fact.value.get(key, 0))

    return {
        "schema_version": SCHEMA_VERSION,
        "type": "MissionControl",
        "captured_at": utcnow_iso(),
        "repo": CONTROL_REPO,
        "goal": goal,
        "goal_state": "ACTIVE" if goal else NOT_AVAILABLE_YET,
        "goal_absent_reason": ""
        if goal
        else (tasks_fact.reason or "no running/ready/review task on the board"),
        "queue": queue,
        "queue_provenance": counts_fact.to_dict(),
        "git": git_fact.to_dict(),
        "ci": ci_fact.to_dict(),
        "pull_requests": prs_fact.to_dict(),
        "tests": _tests_fact().to_dict(),
    }


def _tests_fact() -> Fact:
    """Last recorded local test result.

    The BFF does not run the suite on request — a web request must never be able
    to trigger a test run (that would be a remote execution primitive). Instead a
    test run writes `control/tests/last_run.json` and we surface that, clearly
    labelled with when it happened, so a stale result cannot masquerade as fresh.
    """
    from pathlib import Path

    marker = Path(__file__).resolve().parent.parent / "tests" / "last_run.json"
    src = f"file:{marker}"
    if not marker.exists():
        return Fact.missing(src, "no test run recorded yet (run control/tests/test_adversarial.py)")
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return Fact.missing(src, f"unreadable test marker: {exc}")
    return Fact(value=data, source=src, ttl_seconds=3600)


# ---------------------------------------------------------------------------
# Evidence Timeline
# ---------------------------------------------------------------------------

def evidence_timeline(limit: int = 40, include_heartbeats: bool = False) -> dict[str, Any]:
    """Chronological factory activity with provenance and freshness per item.

    Heartbeats are excluded by default: they are 30% of all rows and carry no
    decision-relevant information, so on a phone they would bury the events that
    actually matter. `include_heartbeats=1` brings them back for debugging.
    """
    fact = recent_events(limit=max(limit * 3, 60) if not include_heartbeats else limit)
    items: list[dict[str, Any]] = []
    if fact.available:
        for row in fact.value:
            kind = row.get("kind") or "unknown"
            if not include_heartbeats and kind == "heartbeat":
                continue
            tone, label = _present(kind)
            payload_summary = ""
            raw = row.get("payload")
            if raw:
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        interesting = {
                            k: v
                            for k, v in parsed.items()
                            if k in ("reason", "summary", "error", "outcome", "kind", "pid", "note")
                        }
                        payload_summary = _short(
                            json.dumps(interesting, ensure_ascii=False) if interesting else ""
                        )
                except json.JSONDecodeError:
                    payload_summary = _short(str(raw))
            items.append(
                {
                    "event_id": row.get("id"),
                    "sequence": row.get("id"),
                    "task_id": row.get("task_id"),
                    "task_title": _short(row.get("task_title"), 90),
                    "assignee": row.get("assignee") or "unassigned",
                    "kind": kind,
                    "label": label,
                    "tone": tone,
                    "created_at": row.get("created_at_iso"),
                    "detail": payload_summary,
                    "human_go": kind in HUMAN_GO_EVENT_KINDS,
                }
            )
            if len(items) >= limit:
                break

    return {
        "schema_version": SCHEMA_VERSION,
        "type": "EvidenceTimeline",
        "captured_at": utcnow_iso(),
        "state": fact.state,
        "reason": fact.reason,
        "source": fact.source,
        "count": len(items),
        "items": items,
    }


# ---------------------------------------------------------------------------
# Human-Go Inbox
# ---------------------------------------------------------------------------

def human_go_inbox() -> dict[str, Any]:
    """Everything genuinely waiting on David, and nothing that isn't.

    Two feeds merge here:
      * blocked kanban tasks whose `block_kind` needs a person; and
      * open PRs, because merge-to-main is `HUMAN_GO_REAL` by this WO and no
        agent may perform it.

    Tasks blocked as `dependency`/`transient` are listed separately as
    `auto_resolving` so the inbox does not cry wolf.
    """
    blocked_fact = blocked_tasks()
    prs_fact = open_pull_requests()

    needs_human: list[dict[str, Any]] = []
    auto_resolving: list[dict[str, Any]] = []

    if blocked_fact.available:
        for row in blocked_fact.value:
            kind = row.get("block_kind")
            entry = {
                "decision_id": f"task:{row['id']}",
                "kind": "TASK_BLOCKED",
                "task_id": row["id"],
                "title": _short(row.get("title"), 120),
                "assignee": row.get("assignee") or "unassigned",
                "block_kind": kind or "unspecified",
                "reason": _short(row.get("last_failure_error")) or "",
                "created_at": row.get("created_at_iso"),
                "action_hint": "Responder en el board (hermes kanban unblock) o comentar la tarea.",
            }
            if kind in HUMAN_BLOCKING_KINDS or kind is None:
                needs_human.append(entry)
            else:
                entry["action_hint"] = (
                    "Se resuelve sola: dependency reanuda al cerrar el padre; "
                    "transient reintenta."
                )
                auto_resolving.append(entry)

    if prs_fact.available:
        for pr in prs_fact.value:
            needs_human.append(
                {
                    "decision_id": f"pr:{pr.get('number')}",
                    "kind": "PR_MERGE_GATE",
                    "task_id": None,
                    "title": _short(f"PR #{pr.get('number')} — {pr.get('title')}", 140),
                    "assignee": pr.get("user") or "unknown",
                    "block_kind": "HUMAN_GO_REAL",
                    "reason": (
                        f"{pr.get('head')} → {pr.get('base')}"
                        + (" (draft)" if pr.get("draft") else "")
                        + ". Merge a main es HUMAN_GO_REAL: ningún agente lo ejecuta."
                    ),
                    "created_at": pr.get("updated_at"),
                    "url": pr.get("url"),
                    "action_hint": "Revisar el PR y mergear vos, o responder GO en el WO.",
                }
            )

    sources = [blocked_fact.to_dict(), prs_fact.to_dict()]
    degraded = [s for s in sources if s["state"] == NOT_AVAILABLE_YET]

    return {
        "schema_version": SCHEMA_VERSION,
        "type": "HumanGoInbox",
        "captured_at": utcnow_iso(),
        "pending_count": len(needs_human),
        "pending": needs_human,
        "auto_resolving": auto_resolving,
        "sources": sources,
        "state": NOT_AVAILABLE_YET if len(degraded) == len(sources) else "VERIFIED",
        "partial": bool(degraded) and len(degraded) < len(sources),
        "degraded_reasons": [s["reason"] for s in degraded if s["reason"]],
    }


# ---------------------------------------------------------------------------
# Product cards (IA-VISION / SUINI)
# ---------------------------------------------------------------------------

# Endpoints are declared, then *probed*. A card only claims a live target when
# the TCP connect succeeded in this request. Nothing here writes to either
# product; these are status readers only.
_PRODUCT_CARDS = [
    {
        "project_id": "ia-vision",
        "display_name": "IA-VISION",
        "repo": IA_VISION_REPO,
        "targets": [
            {"label": "Visor de conteo", "endpoint": "http://127.0.0.1:7921/", "kind": "visor"},
        ],
        "review_note": "Evidencia real: video, frames, overlays, tracks, conteos, velocidades, calibración.",
    },
    {
        "project_id": "suini",
        "display_name": "SUINI",
        "repo": SUINI_REPO,
        "targets": [
            {"label": "Panorama web_modeler", "endpoint": "http://127.0.0.1:8080/", "kind": "modeler"},
            {"label": "Motor de simulación", "endpoint": "http://127.0.0.1:8081/", "kind": "motor"},
        ],
        "review_note": (
            "Autoridad canónica del runtime la conserva SUINI. "
            "TrafficLab Control no es un segundo dueño de la simulación."
        ),
    },
]


def product_cards() -> dict[str, Any]:
    cards = []
    for spec in _PRODUCT_CARDS:
        head = remote_head(spec["repo"])
        targets = []
        for target in spec["targets"]:
            alive = probe_tcp(target["endpoint"])
            targets.append(
                {
                    "label": target["label"],
                    "kind": target["kind"],
                    "endpoint": target["endpoint"] if alive else "",
                    "declared_endpoint": target["endpoint"],
                    "state": "VERIFIED" if alive else NOT_AVAILABLE_YET,
                    "reason": ""
                    if alive
                    else f"nada escuchando en {target['endpoint']} (TCP connect rechazado)",
                    "probed_at": utcnow_iso(),
                }
            )
        any_live = any(t["state"] == "VERIFIED" for t in targets)
        cards.append(
            {
                "schema_version": SCHEMA_VERSION,
                "type": "ProductCard",
                "project_id": spec["project_id"],
                "display_name": spec["display_name"],
                "repo": spec["repo"],
                "remote_head": head.to_dict(),
                "targets": targets,
                "review_state": "VERIFIED" if any_live else NOT_AVAILABLE_YET,
                "review_note": spec["review_note"],
                "mutation_policy": "READ_ONLY — este panel nunca escribe código, DB, runtime ni schema del producto.",
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "ProductCardList",
        "captured_at": utcnow_iso(),
        "cards": cards,
    }
