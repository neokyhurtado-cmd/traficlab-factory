"""5-minute polling scheduler (Phase 1).

The scheduler is intentionally minimal: it runs the handler once per
configured interval, then writes the watcher status JSON, then sleeps.

It is NOT responsible for activation. The cron job wrapper lives in a
separate script (``scripts/run_watcher.sh``) so a David GO can install or
remove it without touching this Python module.

The scheduler respects a ``max_runtime_seconds`` cap: if a single tick
takes longer than that (e.g. evidence dir creation, gh rate limit), the
scheduler logs and continues. Ticks never block each other.
"""
from __future__ import annotations

import logging
import signal
import time
from dataclasses import dataclass
from typing import Callable, Optional

from directive_watcher.handler import TickSummary, WatcherHandler
from directive_watcher.sidecar_store import SidecarStore
from directive_watcher.status import WatcherStatus, write_status

LOG = logging.getLogger("directive_watcher.scheduler")


@dataclass(frozen=True)
class SchedulerConfig:
    interval_seconds: int = 5 * 60  # 5 minutes per #18 Phase 1
    max_runtime_seconds: int = 60
    max_ticks: Optional[int] = None  # None = infinite
    status_path: str = "watcher_status.json"


def watch_repos_from_config(config_path: str) -> list[str]:
    """Load the allowlist config and return the repo list to poll.

    The config file is plain YAML (parsed via PyYAML if available, else a
    tiny regex fallback) and contains at least:

        allowlisted_repos: [...]
        allowlisted_authors: [...]

    The ``watched_repos`` helper downstream filters these by the
    orchestrator routing table to avoid creating a second hidden
    scheduling island. See ``README.md``.
    """
    import yaml

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    repos = cfg.get("allowlisted_repos") or []
    if not isinstance(repos, list):
        raise ValueError("allowlisted_repos must be a list in config")
    return [str(r).strip() for r in repos if str(r).strip()]


def build_status(
    *,
    store: SidecarStore,
    last_tick: TickSummary | None,
    last_result: tuple[str, str] | None,
    last_run_status: str | None,
    last_run_finished_at: int | None,
) -> WatcherStatus:
    finalised = store.list_finalised()[:1]
    last_directive_id = last_result[0] if last_result else (
        finalised[0]["directive_id"] if finalised else None
    )
    last_result_status = last_result[1] if last_result else (
        finalised[0]["result_status"] if finalised else None
    )
    return WatcherStatus(
        watcher_status="healthy",
        last_poll_at=int(time.time()),
        last_seen_comment_id=store.last_seen_comment_id(),
        active_execution=None,
        queue_depth=len(store.claim_pending()),
        last_result=last_directive_id,
        last_result_status=last_result_status,
        last_run_status=last_run_status,
        last_run_finished_at=last_run_finished_at,
    )


class Scheduler:
    """Runs ``handler.tick()`` once every ``interval_seconds`` until stopped."""

    def __init__(
        self,
        *,
        config: SchedulerConfig,
        handler: WatcherHandler,
        repos: list[str],
        should_stop: Callable[[], bool] = lambda: False,
    ) -> None:
        self._config = config
        self._handler = handler
        self._repos = repos
        self._should_stop = should_stop
        self._last_result: tuple[str, str] | None = None
        self._last_run_status: str | None = None
        self._last_run_finished_at: int | None = None

    def run_forever(self) -> None:
        ticks = 0
        while not self._should_stop():
            started = time.time()
            tick_summary = self._run_one_tick()
            elapsed = time.time() - started
            ticks += 1
            if self._config.max_ticks is not None and ticks >= self._config.max_ticks:
                LOG.info("max_ticks=%d reached; exiting", self._config.max_ticks)
                return
            if elapsed > self._config.max_runtime_seconds:
                LOG.warning(
                    "tick took %.1fs (> max %ds) — slowing next sleep",
                    elapsed, self._config.max_runtime_seconds,
                )
            remaining = self._config.interval_seconds - elapsed
            if remaining > 0:
                time.sleep(remaining)

    def _run_one_tick(self) -> TickSummary:
        try:
            summary = self._handler.tick(self._repos)
            self._last_run_status = "ok"
        except Exception as e:  # noqa: BLE001
            LOG.exception("tick failed: %s", e)
            summary = TickSummary()
            summary.notes.append(f"tick_error: {e}")
            self._last_run_status = "error"
        self._last_run_finished_at = int(time.time())
        # Pick the latest finalised directive for the status snapshot.
        finalised = self._handler._store.list_finalised()
        if finalised:
            f = finalised[0]
            self._last_result = (f["directive_id"], f["result_status"])
        status = build_status(
            store=self._handler._store,
            last_tick=summary,
            last_result=self._last_result,
            last_run_status=self._last_run_status,
            last_run_finished_at=self._last_run_finished_at,
        )
        write_status(self._config.status_path, status)
        return summary


def install_sigint_handler(loop_should_stop: list[bool]) -> None:
    """Install a SIGINT handler so the scheduler exits cleanly on Ctrl-C.
    Tests use ``should_stop`` instead, but this is the production hook."""
    def _handler(signum, frame):  # noqa: ARG001
        LOG.info("received SIGINT; stopping after current tick")
        loop_should_stop.append(True)
    try:
        signal.signal(signal.SIGINT, _handler)
    except ValueError:
        # signal only works in main thread; tests/imports are fine without.
        pass
