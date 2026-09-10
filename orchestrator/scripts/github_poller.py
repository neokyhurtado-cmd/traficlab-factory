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
import subprocess
import sys
from typing import Iterable

# Co-located modules — make sure we can import regardless of the caller's CWD.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import routing_resolver  # noqa: E402

WORK_ORDER_LABEL = "hermes-work-order"
ISSUE_STATE = "open"
PARENT_TASK_ID = "t_47131ada"  # ORCH-AUTODISPATCH-01 — this is the poller's parent


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
    """Return a list of issue dicts for `repo` with the WORK_ORDER_LABEL."""
    cmd = [
        "gh", "issue", "list",
        "--repo", repo,
        "--label", WORK_ORDER_LABEL,
        "--state", ISSUE_STATE,
        "--limit", "50",
        "--json", "number,title,body,labels,state",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        # gh prints to stderr; surface but don't raise — caller decides.
        raise RuntimeError(
            f"gh issue list failed for {repo} (exit {proc.returncode}): "
            f"{proc.stderr.strip()[:300]}"
        )
    try:
        return json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"could not parse gh JSON for {repo}: {e}") from e


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

    cmd = [
        "hermes", "kanban", "create", title,
        "--body", body,
        "--assignee", assignee,
        "--parent", PARENT_TASK_ID,
        "--idempotency-key", idem_key,
        "--json",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(
            f"hermes kanban create failed for {idem_key} (exit {proc.returncode}): "
            f"{proc.stderr.strip()[:300]}"
        )

    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"could not parse kanban JSON for {idem_key}: {e}") from e

    task_id = result.get("id") or ""
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


def main() -> int:
    """Run one poll cycle across all watched repos.

    Returns 0 even on partial failures so the cron scheduler doesn't mark
    the job as failed — every tick is a fresh attempt and the next tick
    will retry whatever transient error hit. Per-repo errors are already
    logged to stderr by the time we get here.
    """
    repos = watched_repos()
    if not repos:
        log("warn: no watched repos (routing table empty or all targets missing)")
        return 0
    for repo, assignee in repos:
        try:
            for line in poll_repo(repo, assignee):
                # Each line goes to stdout — the cron delivery sees it.
                print(line, flush=True)
        except RuntimeError as e:
            # gh failure on one repo shouldn't kill the whole poll.
            log(f"warn: {repo}: {e}")
            continue
    return 0


if __name__ == "__main__":
    sys.exit(main())
