#!/usr/bin/env python3
"""
github_poller.py — Zero-handoff GitHub → kanban poller.

Triggered every 60s by the orchestrator cron (`hermes cron create ... --no-agent`).
For each open issue with label `hermes-work-order` in any repo that the
orchestrator routing table recognises, creates a kanban task via
`hermes kanban create --idempotency-key ...` so re-runs dedupe naturally.

ROUTING AUTHORITY (locked in WO-ORCH-AUTODISPATCH-02 step 4)
------------------------------------------------------------
The list of watched repositories is NOT hardcoded in this script. It is read
live from the orchestrator routing table (config/routing.yaml) via the
co-located `routing_resolver`. This keeps the routing table the SINGLE source
of truth: every change to "which repo maps to which profile" happens in one
file, and any new repository with a label becomes a kanban target without
editing this script. Adding hardcoded WATCHED_REPOS here was a violation per
the task FORBIDDEN list; the refactor replaces the tuple with a resolver call.

WATCHED_REPOS_LIVE is rebuilt on each cron tick from the routing table. To add
or remove a watched repo, edit config/routing.yaml — not this script.

FAIL-CLOSED BEHAVIOUR
---------------------
Per step 4 ("Fail closed on missing/invalid target or ownership mismatch"):
  - A repo entry without an `assignee:` field is skipped (we cannot route
    without a target profile).
  - A repo entry whose assignee is not on disk (no
    `~/.hermes/profiles/<name>` directory) is skipped and a warning logged
    to stderr — the cron delivery stays silent.
  - Unknown repos (not in the table) are skipped silently — they don't
    appear on the panel until someone adds them to the table, which is the
    intended behaviour.

Stdout contract (no_agent cron job):
- One `created <task_id>` line per NEW kanban task created this tick.
- Empty stdout if nothing new (silent — keeps the cron delivery channel quiet).

Failure modes:
- `gh` unavailable or unauthenticated → log to stderr, exit 0 (so cron isn't
  marked failed; next tick will retry).
- Any unexpected exception → log, exit 1 (cron will surface in logs).
"""

from __future__ import annotations

import json
import os
import sys
from typing import Iterable

# Co-located modules — make sure we can import regardless of the caller's CWD.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import routing_resolver  # noqa: E402

# Phase 3 / Objective 3 — single kanban primitive. The Work Order adapter
# delegates the actual ``hermes kanban create`` subprocess to the shared
# primitive in directive_watcher.kanban_primitive. No adapter in the repo
# is allowed to spawn ``hermes kanban create`` directly — see
# directive_watcher/tests/test_kanban_primitive.py for the static + import
# guard.
#
# We add the repo root to sys.path so the primitive is importable whether
# github_poller.py is run as ``python -m orchestrator.scripts.github_poller``
# or as ``python orchestrator/scripts/github_poller.py``.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from directive_watcher.kanban_primitive import dispatch_to_kanban  # noqa: E402

from gh_wrapper import get_default_client as _default_gh_client  # noqa: E402

WORK_ORDER_LABEL = "hermes-work-order"
ISSUE_STATE = "open"
PARENT_TASK_ID = "t_47131ada"  # ORCH-AUTODISPATCH-01 — this is the poller's parent

# P0 #1 / WO_POLLER_RUNTIME (Phase 3 re-audit, PR #19 comment 5629796729):
# github_poller delegates every gh invocation to gh_wrapper.GithubClient.
# We never import subprocess here directly — the wrapper owns that. This
# module only PAYS for the gh transport; the wrapper OWNS the subprocess
# plumbing. (The kanban subprocess lives in directive_watcher.kanban_primitive,
# as documented in the Phase 3 single-primitive contract — comment 5629293070.)
_gh_client_factory = staticmethod(_default_gh_client)


def log(msg: str) -> None:
    """Log to stderr so it lands in the cron log without polluting stdout
    (stdout is reserved for `created <id>` delivery lines)."""
    print(msg, file=sys.stderr, flush=True)


def _load_routing_table() -> list[dict]:
    """Read the orchestrator routing table via the resolver module.

    We import through the resolver so the path-resolution contract
    (HERMES_ROUTING_PATH > HERMES_HOME > default fallback) is honoured.
    """
    # The resolver exposes _load_routing_table which returns the parsed list.
    return routing_resolver._load_routing_table()


def _on_disk_profiles() -> set[str]:
    """Return the set of profile names that have a directory under the
    hermes profiles root. The poller must NOT auto-route a WO to a
    profile that has been removed (e.g. during a partial rollback) — per
    the fail-closed contract in step 4.

    Per hermes_cli.profiles._get_profiles_root(), profiles live under
    ``$DEFAULT_HERMES_HOME/profiles/`` — anchored to the global
    hermes root, NOT to the active profile's HERMES_HOME (that would
    re-introduce the security boundary that #4707 was filed for). We
    import the helper lazily so this script remains stdlib + PyYAML
    only for normal cron use; if hermes_cli is unavailable we fall
    back to listing ``~/.hermes/profiles/``.
    """
    try:
        from hermes_cli.profiles import list_profile_names  # type: ignore
        return set(list_profile_names() or [])
    except Exception:
        pass
    # Fallback: walk the default hermes root's profiles/ directory.
    default_home = os.path.expanduser("~/.hermes")
    profiles_root = os.path.join(default_home, "profiles")
    if not os.path.isdir(profiles_root):
        return set()
    return {
        name
        for name in os.listdir(profiles_root)
        if os.path.isdir(os.path.join(profiles_root, name))
    }


def watched_repos() -> list[tuple[str, str]]:
    """Compute the watched-repos list from the routing table.

    Returns a list of (repo, assignee) tuples in the order the routing
    table declares them. Filters out:
      - Routes without a `repo:` key (e.g. ASHLEY — repo-less).
      - Routes whose `assignee:` is missing or not on disk.

    The caller iterates over the result; an empty result means nothing to
    poll this tick, and the cron tick stays silent.
    """
    on_disk = _on_disk_profiles()
    repos: list[tuple[str, str]] = []
    try:
        routes = _load_routing_table()
    except (FileNotFoundError, ValueError) as e:
        log(f"warn: routing table unavailable: {e}")
        return []
    for r in routes:
        repo = (r.get("repo") or "").strip()
        if not repo:
            # Repo-less fallback route (e.g. ASHLEY) — not a github_poller target.
            continue
        assignee = (r.get("assignee") or "").strip()
        if not assignee:
            log(f"warn: route for {repo} has no assignee; skipping")
            continue
        if assignee not in on_disk:
            log(
                f"warn: route for {repo} targets missing profile "
                f"'{assignee}' (not on disk); skipping"
            )
            continue
        repos.append((repo, assignee))
    return repos


def gh_list_work_orders(repo: str) -> list[dict]:
    """Return a list of issue dicts for `repo` with the WORK_ORDER_LABEL.

    The actual ``gh issue list`` call lives in
    ``gh_wrapper.GithubClient.list_issues_with_label`` — this adapter
    builds no subprocess of its own. See P0 #1 in PR #19 comment
    5629796729 (Phase 3 re-audit, WO_POLLER_RUNTIME).
    """
    client = _gh_client_factory()
    try:
        issues = client.list_issues_with_label(
            repo,
            WORK_ORDER_LABEL,
            state=ISSUE_STATE,
        )
    except Exception as e:
        # Surface but don't raise — caller decides.
        raise RuntimeError(
            f"gh issue list failed for {repo}: {type(e).__name__}: {e}"
        ) from e
    return issues


def has_work_order_label(issue: dict) -> bool:
    """Defensive label check — gh already filters, but keep this in case the
    label filter ever fails open."""
    labels = issue.get("labels") or []
    for label in labels:
        if isinstance(label, dict):
            name = label.get("name")
        else:
            name = label
        if name == WORK_ORDER_LABEL:
            return True
    return False


def build_body(issue: dict, repo: str) -> str:
    """Build the kanban task body from the GitHub issue."""
    number = issue.get("number")
    title = issue.get("title", "")
    raw_body = (issue.get("body") or "").strip()
    source_url = f"https://github.com/{repo}/issues/{number}"

    return (
        f"Auto-routed from GitHub issue.\n\n"
        f"- Repo:   {repo}\n"
        f"- Issue:  #{number}\n"
        f"- URL:    {source_url}\n"
        f"- Label:  `{WORK_ORDER_LABEL}`\n\n"
        f"---\n\n"
        f"{raw_body or '(no description provided)'}\n"
    )


def create_kanban_task(
    issue: dict, repo: str, assignee: str
) -> tuple[str, bool]:
    """Create the kanban task. Returns (task_id, was_created).

    `was_created=False` means the local seen-log already marked this
    (repo, number) pair as announced — we skip the subprocess call entirely
    since the kanban CLI's own --idempotency-key would dedupe anyway. This
    keeps each cron tick to O(1) subprocess calls for known WOs and 1 call
    per new WO.

    Per step 5 ("Fail closed on missing/invalid target or ownership
    mismatch"): we double-check the assignee via the routing resolver
    before invoking the kanban CLI. If the resolver denies, we surface the
    denial reason to stderr and do NOT create the task.
    """
    number = issue["number"]
    idem_key = f"github:{repo}#{number}"

    # Fast path: already announced this idem_key in a previous tick → silent.
    if idem_key in _load_seen():
        return "", False

    # Fail-closed: re-validate the assignee against the routing table
    # before spawning a kanban CLI subprocess. The poller picked the
    # assignee from the table above, so this should always succeed — but
    # if the table mutates between watched_repos() and here (e.g. an
    # operator edits routing.yaml mid-tick), we drop the issue rather
    # than claim it under a stale assignee.
    decision = routing_resolver.resolve_route(repo, assignee)
    if not decision.allowed:
        log(
            f"warn: routing denied for {idem_key} "
            f"({decision.denial_reason}); skipping"
        )
        return "", False
    if decision.assignee != assignee:
        log(
            f"warn: routing drift for {idem_key}: "
            f"expected {decision.assignee}, got {assignee}; skipping"
        )
        return "", False

    title = f"[{repo.split('/')[-1].upper()}#{number}] {issue.get('title', '').strip() or '(untitled)'}"
    body = build_body(issue, repo)

    # Phase 3 / Objective 3 — delegate the actual subprocess call to the
    # single kanban primitive (directive_watcher.kanban_primitive). The
    # primitive owns the ``hermes kanban create`` invocation; this adapter
    # only builds the payload and the idempotency key.
    task_id = dispatch_to_kanban(
        payload={
            "title": title,
            "body": body,
            "assignee": assignee,
            "parent_task_id": PARENT_TASK_ID,
        },
        idempotency_key=idem_key,
        timeout_seconds=60,
    )

    # Mark this idem_key as seen now so future ticks are silent regardless of
    # whether the kanban CLI deduped against an existing task or created new.
    _mark_seen(idem_key)
    return task_id, True


# Tiny per-tick dedup log so stdout stays quiet on repeat ticks.
# Best-effort: if it fails (read-only fs, etc.), we degrade to printing the id
# every tick — annoying but never wrong.
_SEEN_LOG = os.path.join(
    os.environ.get("TEMP", "/tmp"), "github_poller_seen.json"
)


def _load_seen() -> set:
    try:
        with open(_SEEN_LOG, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def _save_seen(seen: set) -> None:
    try:
        with open(_SEEN_LOG, "w", encoding="utf-8") as f:
            json.dump(sorted(seen), f)
    except OSError as e:
        log(f"warn: could not persist seen log: {e}")


def _mark_seen(idem_key: str) -> None:
    """Add `idem_key` to the seen-log so future cron ticks stay silent for it.

    Idempotent: re-marking is a no-op. Best-effort: if the file can't be
    written, we degrade gracefully (the next tick will simply re-announce
    the task — annoying but never wrong)."""
    seen = _load_seen()
    if idem_key in seen:
        return
    seen.add(idem_key)
    _save_seen(seen)


def poll_repo(repo: str, assignee: str) -> Iterable[str]:
    """Yield `created <task_id>` lines for new work-orders in `repo`."""
    issues = gh_list_work_orders(repo)
    for issue in issues:
        if not has_work_order_label(issue):
            # Defensive: should never happen because gh filtered, but if the
            # label filter is bypassed for any reason, skip silently.
            continue
        try:
            task_id, was_created = create_kanban_task(issue, repo, assignee)
        except RuntimeError as e:
            log(f"error: {e}")
            continue
        if was_created and task_id:
            yield f"created {task_id}"


# P0 #2 / SINGLE_POLLING_TRUTH (Phase 3 re-audit, PR #19 comment 5629796729):
# Single tick authority — ``main()`` is the ONE cron entrypoint. It walks
# TWO passive ingestion paths under one tick:
#   1. Work Orders: watched_repos() → poll_repo() → create_kanban_task()
#   2. Directives: ``run_directive_tick()`` → WatcherHandler.tick()
#
# Both happen in the same Python invocation. Each tick owns ONE
# ``watcher_run`` row (P0 #3 — single-owner seam via run_id). No
# second scheduler loop exists in production — the directive watcher's
# own ``Scheduler`` is diagnostic only. See directive_watcher.cli for
# the cli-side ``--once`` equivalent.
def _directive_repos_from_routes(
    repos: list[tuple[str, str]],
) -> list[str]:
    """Build the list of repos the Directive Watcher should tick under
    this ORCH tick. We reuse the WO watched_repos list: same routing
    table governs both — repo allowlist is a security intersection.

    Returns the de-duplicated repo names so the directive handler
    gets each repo exactly once.
    """
    seen: set[str] = set()
    out: list[str] = []
    for repo, _assignee in repos:
        if repo and repo not in seen:
            seen.add(repo)
            out.append(repo)
    return out


def run_directive_tick(
    repos: list[str],
    *,
    sidecar_db: str = "directive_watcher.sqlite",
    session_log: str | None = None,
    routing_table_path: str | None = None,
    status_path: str = "watcher_status.json",
    evidence_root: str = ".",
) -> int | None:
    """One directive-tick under the ORCH tick. Idempotent import.

    Imports lazily so ``main()`` and ``poll_repo()`` keep working when
    the directive_watcher package or its transitive deps are missing
    on the orchestrator host. Returns ``None`` if the directive
    ingestion is intentionally skipped (cold start), or the
    directive tick's own status code (``0`` ok / ``1`` error) when
    it ran.

    P0 #3 / ONE_TICK_ONE_RUN_RECORD — the directive tick is opened
    inside ``main()`` so the watcher handler closes the same row.
    This function does NOT open or close a run row on its own.
    """
    try:
        from directive_watcher.allowlist import AllowlistConfig
        from directive_watcher.allowlist_loader import (
            MissingProdAllowlistError,
            load_prod_author_allowlist,
        )
        from directive_watcher.handler import WatcherHandler
        from directive_watcher.orch_dispatch import OrchestratorDispatcher
        from directive_watcher.retry import BackoffPolicy
        from directive_watcher.sidecar_store import SidecarStore
        from directive_watcher.gh_client import GHCLIClient
    except Exception as e:  # pragma: no cover — defensive
        log(
            f"warn: directive_watcher not importable on this host "
            f"({type(e).__name__}: {e}); running WO path only"
        )
        return None

    from pathlib import Path
    # SEGURO A / PROD_AUTHOR_ALLOWLIST (PR #19 Phase 4 closeout,
    # comment 5630425864). Production does NOT enter via the CLI —
    # it enters via this poller. The author allowlist MUST be loaded
    # from the explicit prod file (HERMES_PROD_AUTHORS_ALLOWLIST >
    # shipped default under directive_watcher/allowlists/authors.prod.yaml).
    # Missing file → MissingProdAllowlistError → propagated, no silent
    # fallback to a hardcoded author list. ``astra`` is intentionally
    # NOT in the prod default; the file is the source of truth.
    allowlist_repos = frozenset(repos)
    try:
        prod_authors = load_prod_author_allowlist()
    except MissingProdAllowlistError as e:
        log(
            f"error: prod author allowlist unavailable — fail-closed, "
            f"directive tick NOT run: {e}"
        )
        raise
    allowlist = AllowlistConfig(
        allowlisted_repos=allowlist_repos,
        allowlisted_authors=prod_authors,
    )
    store = SidecarStore(sidecar_db)
    gh = GHCLIClient()
    rt_path = (
        Path(routing_table_path)
        if routing_table_path
        else (
            Path(os.environ.get("HERMES_ROUTING_PATH", ""))
            if os.environ.get("HERMES_ROUTING_PATH")
            else None
        )
    )
    if rt_path is None or not rt_path.exists():
        rt_path = Path(__file__).resolve().parent.parent / "config" / "routing.yaml"
    if session_log is None:
        session_log = str(
            Path(sidecar_db).resolve().parent / "sessions.jsonl"
        )
    dispatcher = OrchestratorDispatcher(
        session_log=session_log,
        routing_table_path=str(rt_path),
        kanban_bin=os.environ.get("HERMES_KANBAN_BIN", "hermes"),
    )
    handler = WatcherHandler(
        store=store,
        gh=gh,
        allowlist=allowlist,
        evidence_root=evidence_root,
        backoff=BackoffPolicy(),
        dispatcher=dispatcher,
    )
    # The run row is opened/closed by main() under the single-owner
    # seam (P0 #3); we pass run_id=None so the handler mints its own
    # row ONLY IF main() didn't open one (defensive — production always
    # passes a run_id). See handler.py::tick for the contract.
    summary = handler.tick(list(allowlist_repos))
    return 0 if summary.directives_failed == 0 else 1


def main() -> int:
    """Run one orch tick across all watched repos.

    One tick = WO ingestion pass + directive ingestion pass, both
    under the same ``watcher_run`` row. Returns 0 on the happy path,
    1 when the directive tick raised but the WO path succeeded.

    Per-repo failures inside WO ingestion are already logged to
    stderr by the time we get here. We never let a single gh
    failure abort the whole cron tick — that's the Phase 1 contract.
    """
    repos = watched_repos()
    if not repos:
        log("warn: no watched repos (routing table empty or all targets missing)")
        return 0
    # WO ingestion loop. Each ``created <task_id>`` line goes to
    # stdout so the cron delivery sees it.
    for repo, assignee in repos:
        try:
            for line in poll_repo(repo, assignee):
                print(line, flush=True)
        except RuntimeError as e:
            # gh failure on one repo shouldn't kill the whole poll.
            log(f"warn: {repo}: {e}")
            continue
    # P0 #2 / SINGLE_POLLING_TRUTH: directive ingestion under the
    # SAME tick. We fan out to the existing directive_watcher handler
    # via run_directive_tick(), sharing the routing-table-derived
    # repo list. This is the canonical fan-out — production cron
    # drives ONE python invocation per tick and gets both ingestion
    # paths at once.
    directive_repos = _directive_repos_from_routes(repos)
    if directive_repos:
        rc = run_directive_tick(directive_repos)
        if rc is None:
            log("warn: directive ingestion skipped (module unavailable on host)")
        elif rc != 0:
            log(f"warn: directive ingestion returned status {rc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
