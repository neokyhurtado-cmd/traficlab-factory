"""Top-level CLI for the GitHub Directive Watcher.

The CLI is intentionally narrow: it accepts a config file, an interval,
and an evidence base directory. Activation (cron, systemd, no_agent) is
NOT performed here — that lives in the wrapper script per the WO.
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
from directive_watcher.retry import BackoffPolicy
from directive_watcher.scheduler import Scheduler, SchedulerConfig, watch_repos_from_config
from directive_watcher.sidecar_store import SidecarStore

LOG = logging.getLogger("directive_watcher.cli")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="directive_watcher",
        description="Phase 1 GitHub Directive Watcher (poll, claim, ACK/RESULT).",
    )
    p.add_argument("--config", required=True, help="Path to YAML allowlist config.")
    p.add_argument(
        "--interval-seconds", type=int, default=5 * 60,
        help="Polling interval. Default 300 (5 minutes).",
    )
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
        "--max-ticks", type=int, default=None,
        help="If set, exit after N ticks (useful for cron-driven runs).",
    )
    p.add_argument(
        "--once", action="store_true",
        help="Run a single tick and exit (no scheduler loop).",
    )
    p.add_argument(
        "--log-level", default="INFO",
        help="Python logging level.",
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


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    allowlist, repos = load_allowlist(args.config)
    if not repos:
        LOG.error("no allowlisted_repos in config — fail-closed; exiting")
        return 2

    store = SidecarStore(args.sidecar_db)
    gh = GHCLIClient()
    handler = WatcherHandler(
        store=store,
        gh=gh,
        allowlist=allowlist,
        evidence_root=args.evidence_root,
        backoff=BackoffPolicy(),
    )

    if args.once:
        summary = handler.tick(repos)
        sys.stdout.write(json.dumps(summary.as_dict(), indent=2) + "\n")
        return 0

    scheduler = Scheduler(
        config=SchedulerConfig(
            interval_seconds=args.interval_seconds,
            max_ticks=args.max_ticks,
            status_path=args.status_path,
        ),
        handler=handler,
        repos=repos,
    )
    scheduler.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
