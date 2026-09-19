"""Top-level CLI for the GitHub Directive Watcher.

The CLI is intentionally narrow: it accepts a config file, an interval,
and an evidence base directory. Activation (cron, systemd, no_agent) is
NOT performed here — that lives in the wrapper script per the WO.

Phase 3 / Objective 1 — ENTRYPOINT_REAL_DISPATCH
-------------------------------------------------
Per the Phase 3 directive (comment 5629246987) + the steered rephrase
(comment 5629293070), the production CLI must wire the
``OrchestratorDispatcher`` into the ``WatcherHandler`` so the dispatch
path produces real session binds (DISPATCHED), not a silent no-op
(BLOCKED_EXTERNAL_REAL with no session_id). The previous version built
the handler without ``dispatcher=`` — which made the production path
the "doorbell but no one opens" failure the re-audit flagged.

Additionally, ``--once`` writes the same ``watcher_status.json`` that
the scheduler loop writes. Same snapshot, same source of truth — the
cron-driven path no longer skips the War Room status surface.

P0 #3 / ONE_TICK_ONE_RUN_RECORD (PR #19 comment 5629796729)
-----------------------------------------------------------
The cli opens the run row, hands ``run_id`` to ``handler.tick()``, and
closes it. The handler does NOT call ``record_run_start`` itself when
``run_id`` is passed in. Single owner → single ``watcher_run`` row per
logical tick. The duplicate-row bug (cli + handler both opening the
row) is gone.

P0 #2 / SINGLE_POLLING_TRUTH (PR #19 comment 5629796729)
---------------------------------------------------------
The cron-driven production entrypoint is
``orchestrator/scripts/github_poller.py::main`` (the existing
orchestrator tick). It runs both the WO ingestion AND the directive
ingestion under one tick.

The CLI in this module has NO production scheduling loop. ``--once``
runs a single tick and exits; that is the only cron-wrapped entry
the operator needs. The legacy ``Scheduler.run_forever()`` was
removed as a production-reachable scheduling authority — the Phase 3
re-audit (comment 5629796729) explicitly forbidden "two
independently runnable polling authorities". The ``Scheduler`` class
itself stays in ``directive_watcher.scheduler`` (reusable status
helpers + diagnostic loop support) but the CLI no longer wires it.

If a future operator wants to run the watcher inline on a workstation
in a loop, they construct the ``Scheduler`` class directly from
Python (tests do this; see ``test_scheduler_cli.py``). The CLI does
not expose that path because a copy-pasted cron row pointing here
must NOT silently start a second ticking authority.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from directive_watcher.allowlist import AllowlistConfig
from directive_watcher.gh_client import GHCLIClient
from directive_watcher.handler import WatcherHandler
from directive_watcher.orch_dispatch import OrchestratorDispatcher
from directive_watcher.retry import BackoffPolicy
from directive_watcher.scheduler import build_status  # reused for status shape
from directive_watcher.sidecar_store import SidecarStore

LOG = logging.getLogger("directive_watcher.cli")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="directive_watcher",
        description="Phase 1 GitHub Directive Watcher — single-tick diagnostic CLI.",
    )
    p.add_argument("--config", required=True, help="Path to YAML allowlist config.")
    p.add_argument(
        "--sidecar-db", default="directive_watcher.sqlite",
        help="Path to the durable sidecar SQLite file.",
    )
    p.add_argument(
        "--evidence-root", default=".",
        help="Base directory under which evidence/visual/<execution_id>/ is created.",
    )
    p.add_argument(
        "--status-path", default="watcher_status.json",
        help="Where to write the machine-readable status JSON.",
    )
    p.add_argument(
        "--routing-table", default=None,
        help=(
            "Path to the orchestrator routing table (YAML). "
            "Defaults to HERMES_ROUTING_PATH > HERMES_HOME/config/routing.yaml > "
            "the repo's orchestrator/config/routing.yaml. The dispatcher uses "
            "this to resolve assignee per repository."
        ),
    )
    p.add_argument(
        "--session-log", default=None,
        help=(
            "Path to the JSONL session registry sidecar. "
            "Default: <sidecar-db-dir>/sessions.jsonl."
        ),
    )
    p.add_argument(
        "--once", action="store_true", required=True,
        help=(
            "Run a single tick and exit. This flag is REQUIRED — the CLI "
            "has no production-loop mode (P0 #2 / SINGLE_POLLING_TRUTH). "
            "The orchestrator cron drives github_poller.main, which fans "
            "out to WO + Directive ingestion under one tick."
        ),
    )
    p.add_argument(
    "--log-level", default="INFO",
    help="Python logging level.",
    )
    p.add_argument(
    "--env", default="prod", choices=("prod", "test"),
    help=(
        "Environment selector. prod=load the production author "
        "allowlist from --author-allowlist (fail-closed if missing); "
        "test=use --config as the combined fixture (test/dev only). "
        "Default: prod — fail-closed by default."
    ),
    )
    p.add_argument(
    "--author-allowlist", default=None,
    help=(
        "Path to the PRODUCTION author allowlist YAML. Required "
        "when --env=prod. The file MUST exist; missing file → "
        "fail-closed exit code != 0. Only consulted when --env=prod."
    ),
    )
    return p.parse_args(argv)


def load_allowlist(config_path: str) -> tuple[AllowlistConfig, list[str]]:
    import yaml

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    repos = cfg.get("allowlisted_repos") or []
    authors = cfg.get("allowlisted_authors") or []
    if not isinstance(repos, list) or not isinstance(authors, list):
        raise ValueError("allowlisted_repos and allowlisted_authors must be lists")
    return (
        AllowlistConfig(
            allowlisted_repos=frozenset(str(r).strip() for r in repos if str(r).strip()),
            allowlisted_authors=frozenset(str(a).strip() for a in authors if str(a).strip()),
        ),
        [str(r).strip() for r in repos if str(r).strip()],
    )


def _resolve_session_log(sidecar_db: str, override: str | None) -> Path:
    """Default the JSONL session log to live next to the SQLite sidecar
    unless the caller provided an explicit path."""
    if override:
        return Path(override)
    return Path(sidecar_db).resolve().parent / "sessions.jsonl"


def _resolve_routing_table(override: str | None) -> Path:
    """Pick the orchestrator routing table path. Mirrors the resolver's
    HERMES_ROUTING_PATH > HERMES_HOME/config > repo fallback so the
    dispatcher and the CLI agree on the source of truth."""
    if override:
        return Path(override)
    env = os.environ.get("HERMES_ROUTING_PATH")
    if env:
        return Path(env)
    hermes_home = os.environ.get("HERMES_HOME")
    if hermes_home:
        candidate = Path(hermes_home) / "config" / "routing.yaml"
        if candidate.exists():
            return candidate
    # Repo-local fallback — same shape the resolver uses by default.
    repo_root = Path(__file__).resolve().parent.parent
    return repo_root / "orchestrator" / "config" / "routing.yaml"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if args.env == "prod":
        # Production path: the author allowlist MUST be loaded via the
        # shared loader (SEGURO A, PR #19 Phase 4 closeout). The CLI and
        # ``orchestrator/scripts/github_poller.run_directive_tick`` both
        # call ``load_prod_author_allowlist`` — same function, same fail-
        # closed contract. ``--config`` only carries the repos in prod.
        # Missing prod file → MissingProdAllowlistError → fail-closed
        # exit code 3, never a hardcoded fallback.
        try:
            from directive_watcher.allowlist_loader import (
                MissingProdAllowlistError,
                load_prod_author_allowlist,
            )
        except Exception as e:  # pragma: no cover — defensive
            LOG.error(
                "allowlist_loader not importable on this host (%s: %s); "
                "fail-closed",
                type(e).__name__,
                e,
            )
            return 3
        try:
            prod_authors = load_prod_author_allowlist(args.author_allowlist)
        except MissingProdAllowlistError as e:
            LOG.error(
                "author allowlist file missing — fail-closed: %s",
                e,
            )
            return 3
        # Repos come from --config (which is the test/fixture-style
        # combined file); the prod author allowlist overrides authors.
        repos_config, repos = load_allowlist(args.config)
        allowlist = AllowlistConfig(
            allowlisted_repos=repos_config.allowlisted_repos,
            allowlisted_authors=prod_authors,
        )
        if not repos:
            LOG.error("no allowlisted_repos in config — fail-closed; exiting")
            return 2
    else:
        # Test/dev path: --config carries both repos and authors.
        allowlist, repos = load_allowlist(args.config)
        if not repos:
            LOG.error("no allowlisted_repos in config — fail-closed; exiting")
            return 2

    store = SidecarStore(args.sidecar_db)
    gh = GHCLIClient()

    # Phase 3 / Objective 1 — wire the real dispatch seam. The
    # OrchestratorDispatcher resolves the assignee via the orchestrator
    # routing table and invokes the single kanban primitive. Without
    # this, every production tick finalises BLOCKED_EXTERNAL_REAL with
    # no session bind — the "doorbell but no one opens" failure.
    routing_table_path = _resolve_routing_table(args.routing_table)
    session_log = _resolve_session_log(args.sidecar_db, args.session_log)
    dispatcher = OrchestratorDispatcher(
        session_log=session_log,
        routing_table_path=routing_table_path,
        kanban_bin=os.environ.get("HERMES_KANBAN_BIN", "hermes"),
    )

    handler = WatcherHandler(
        store=store,
        gh=gh,
        allowlist=allowlist,
        evidence_root=args.evidence_root,
        backoff=BackoffPolicy(),
        dispatcher=dispatcher,
    )

    # P0 #3 / ONE_TICK_ONE_RUN_RECORD (PR #19 comment 5629796729):
    # cli opens the run row, hands run_id to handler.tick(), and
    # closes it. The handler does NOT call record_run_start itself
    # when run_id is passed in — single owner, single row per tick.
    last_run_status: str | None = None
    last_run_finished_at: int | None = None
    last_tick = None
    last_result: tuple[str, str] | None = None
    run_id = store.record_run_start(notes=f"once:repos={len(repos)}")
    try:
        last_tick = handler.tick(repos, run_id=run_id)
        store.record_run_finish(run_id, status="ok")
        last_run_status = "ok"
    except Exception as e:  # noqa: BLE001
        LOG.exception("--once tick failed: %s", e)
        store.record_run_finish(run_id, status="error", notes=str(e)[:200])
        last_run_status = "error"
    last_run_finished_at = int(__import__("time").time())
    finalised = store.list_finalised()
    if finalised:
        f = finalised[0]
        last_result = (f["directive_id"], f["result_status"])
    status = build_status(
        store=store,
        last_tick=last_tick,
        last_result=last_result,
        last_run_status=last_run_status,
        last_run_finished_at=last_run_finished_at,
    )
    from directive_watcher.status import write_status
    write_status(args.status_path, status)
    # Stdout still gets the structured tick summary so cron delivery
    # is unaffected — we ADD the status file, we don't replace the
    # stdout contract.
    if last_tick is not None:
        sys.stdout.write(json.dumps(last_tick.as_dict(), indent=2) + "\n")
    return 0 if last_run_status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
