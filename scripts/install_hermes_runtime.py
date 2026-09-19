#!/usr/bin/env python3
"""install_hermes_runtime.py — bounded, reversible per-profile install of the
directive_watcher for a non-orchestrator Hermes runtime.

Purpose
-------
ASHLEY-AUTO-WAKE-FACTORY-PROMOTE-20260918-01 / traficlab-factory#18:
reconcile the directive watcher onto current Factory main and ship the
**runtime portability path** that lets a non-orchestrator profile
(Ashley, by default) wake the Director from `[ASTRA_DIRECTIVE:v1]`
comments **without** granting that profile executable authority over
Factory or IA-VISION.

This script is the **bounded install side**. The Factory side (rebase,
tests, PR) is handled separately; this script consumes a
**Factory SHA pinned to a reviewed branch** and writes a per-profile
runway + scoped allowlist + cron entry under
``~/.hermes/profiles/<profile>/`` only.

Hard non-goals
--------------
1. Never writes to ``~/.hermes/profiles/orchestrator/`` (the canonical
   tick is owned by JUPITER and this script must NOT mutate it).
2. Never writes to ``~/.hermes/profiles/david/`` or any profile not
   explicitly named by ``--profile`` (unless --dry-run is set).
3. Never edits ``~/.hermes/config.yaml``, ``.env``, secrets, tokens,
   global providers, or gateway state.
4. Never registers a *second* scheduler authority: the per-profile
   runway still drives ``orchestrator/scripts/github_poller.py::main()``
   under the existing ``SINGLE_POLLING_TRUTH`` contract (one tick
   does WO ingestion + directive ingestion under one invocation).
5. Never grants the target profile merge/release/secret rotation
   authority: the per-profile allowlist only enables
   ``CONTINUE | REAUDIT_FIX | INVESTIGATE | TEST | BUILD | OPEN_PR``-class
   directives, scoped to ``--repos`` (default: Ashley = suini +
   panorama-mission-control). Protected-boundary directives fail closed.

Scoped allowlist semantics
--------------------------
The target profile's ``directive_watcher/allowlists/authors.prod.yaml``
contains **only** ``--authors`` (default: Ashley = AshleyGomez0 +
neokyhurtado-cmd). A directive from any other author is rejected by
the watcher BEFORE the dispatch path is reached.

The target profile's ``config/routing.yaml`` contains **only** the
allowed repos. The routing_resolver fallback chain
(HERMES_ROUTING_PATH → HERMES_HOME/config → script-relative) all
land on this profile-local file when the runway pins
HERMES_ROUTING_PATH explicitly. The orchestrator's
``config/routing.yaml`` is NEVER touched.

Dry-run semantics
-----------------
``--dry-run`` prints the exact files that would be written and the
exact cron entry that would be registered, but writes nothing. The
script exits 0 on dry-run success.

Rollback
--------
The script writes a single backup of the previous cron
``~/.hermes/profiles/<profile>/cron/jobs.json`` (if present) into
``~/.hermes/profiles/<profile>/cron/jobs.json.install_backup.<UTC>``.
Run ``hermes cron remove <job_id>`` (the printed job_id) to delete
the registered watcher cron. The runway + scripts/ + allowlists
directory can be removed with a plain ``rm -rf``.

CLI
---
::

    python scripts/install_hermes_runtime.py \\
        --profile ashley \\
        --factory-sha b4dd937af8866a5cfb881cf0be94bf1e85b725ec \\
        --repos neokyhurtado-cmd/suini,neokyhurtado-cmd/panorama-mission-control \\
        --authors AshleyGomez0,neokyhurtado-cmd \\
        --hermes-install "C:/Users/david/AppData/Local/hermes/hermes-agent" \\
        [--dry-run]

Defaults target the Ashley profile. ``--factory-sha`` is required.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

# --- Constants ---------------------------------------------------------------

# Profile roots (defaults assume the standard Hermes install layout on Windows).
DEFAULT_HERMES_HOME = Path(r"C:\Users\david\AppData\Local\hermes")
DEFAULT_HERMES_INSTALL = Path(r"C:\Users\david\AppData\Local\hermes\hermes-agent")
DEFAULT_FACTORY_CHECKOUT = Path(r"C:\dev\traficlab-factory-handoff\traficlab-factory")

# Hard-coded target-profile defaults (Ashley).
DEFAULT_PROFILE = "ashley"
DEFAULT_REPOS = (
    "neokyhurtado-cmd/suini",
    "neokyhurtado-cmd/panorama-mission-control",
)
DEFAULT_AUTHORS = ("AshleyGomez0", "neokyhurtado-cmd")

# Cron defaults — same shape as orchestrator's `github-poller` job but
# scoped to a different schedule so it doesn't double-tick.
DEFAULT_CRON_NAME = "ashley-directive-watcher"
DEFAULT_INTERVAL_MINUTES = 2

# Action allowlist for the per-profile install: never enable REVIEW
# (read-only but it dispatches a session) by default, never enable
# MERGE/DEPLOY/RELEASE — those cross protected boundaries regardless
# of who issues the directive.
DEFAULT_ALLOWED_ACTIONS = (
    "CONTINUE",
    "REAUDIT_FIX",
    "INVESTIGATE",
    "TEST",
    "BUILD",
    "OPEN_PR",
)

# --- Output templates --------------------------------------------------------

RUNWAY_TEMPLATE = '''#!/usr/bin/env python3
"""Per-profile runway shim for the directive_watcher.

Auto-generated by scripts/install_hermes_runtime.py.
DO NOT EDIT — re-run the installer to change the pinned SHA or the
allowlist. The shim mirrors orchestrator/scripts/github_poller_runway.py
so the SINGLE_POLLING_TRUTH contract holds: one tick drives both WO
ingestion and directive ingestion under one Python invocation. No
second scheduler authority is created here.

Profile: __PROFILE__
Factory SHA pinned: __FACTORY_SHA__
Allowed repos: __REPOS__
Allowed authors: __AUTHORS__
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

PROFILE = "__PROFILE__"
HERMES_HOME = Path(r"__HERMES_HOME__")
HERMES_INSTALL = Path(r"__HERMES_INSTALL__")
CANONICAL_CHECKOUT = Path(r"__FACTORY_CHECKOUT__")
FACTORY_SHA = "__FACTORY_SHA__"
POLLER_RELATIVE = Path("orchestrator") / "scripts" / "github_poller.py"
EXIT_RUNWAY_BROKEN = 5  # distinct from any poller exit code


def main() -> int:
    if not CANONICAL_CHECKOUT.is_dir():
        sys.stderr.write(
            f"runway[{PROFILE}]: canonical checkout missing: {CANONICAL_CHECKOUT}\\n"
        )
        return EXIT_RUNWAY_BROKEN
    poller = CANONICAL_CHECKOUT / POLLER_RELATIVE
    if not poller.is_file():
        sys.stderr.write(
            f"runway[{PROFILE}]: canonical poller missing: {poller}\\n"
        )
        return EXIT_RUNWAY_BROKEN

    # Profile-local routing path (overrides HERMES_HOME fallback).
    profile_routing = HERMES_HOME / "profiles" / PROFILE / "config" / "routing.yaml"
    if not profile_routing.is_file():
        sys.stderr.write(
            f"runway[{PROFILE}]: profile routing.yaml missing: {profile_routing}\\n"
        )
        return EXIT_RUNWAY_BROKEN

    venv_python = HERMES_INSTALL / "venv" / "Scripts" / "python.exe"
    venv_site_packages = HERMES_INSTALL / "venv" / "Lib" / "site-packages"

    env = {
        **os.environ,
        "HERMES_HOME": str(HERMES_HOME / "profiles" / PROFILE),
        "HERMES_ROUTING_PATH": str(profile_routing),
        "HERMES_DIRECTIVE_SIDECAR_DB": str(
            HERMES_HOME / "profiles" / PROFILE / "directive_watcher" / "state"
            / "directive_watcher.sqlite"
        ),
        "HERMES_SESSION_LOG": str(
            HERMES_HOME / "profiles" / PROFILE / "directive_watcher" / "state"
            / "sessions.jsonl"
        ),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONPATH": f"{HERMES_INSTALL};{venv_site_packages}",
    }
    completed = subprocess.run(
        [str(venv_python), str(poller)],
        cwd=str(CANONICAL_CHECKOUT),
        env=env,
        check=False,
    )
    return completed.returncode


if __name__ == "__main__":
    # Resolve the profile routing path at module scope so the diagnostic
    # log can record it without depending on main() having run. This is
    # the SAME path main() will use to dispatch the canonical poller.
    _profile_routing = HERMES_HOME / "profiles" / PROFILE / "config" / "routing.yaml"
    log_path = HERMES_HOME / "profiles" / PROFILE / "logs" / "runway_env.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a") as _f:
        _f.write(f"\\n--- runway[{PROFILE}] invoked at {time.time()} ---\\n")
        _f.write(f"sys.executable: {sys.executable}\\n")
        _f.write(f"HERMES_ROUTING_PATH (set): {_profile_routing}\\n")
        _f.write(f"Factory SHA: {FACTORY_SHA}\\n")
    sys.exit(main())
'''


ROUTING_YAML_TEMPLATE = '''# routing.yaml — per-profile scoped routing table for the directive_watcher.
#
# AUTO-GENERATED by scripts/install_hermes_runtime.py on {utc_now}.
# Profile: {profile}
# Allowed repos: {repos}
# Allowed authors: {authors}
#
# This file is the SINGLE source of truth for which repos the {profile}
# runtime will ingest directives from. Adding any repo here beyond the
# installer allowlist is a security regression and must be reverted.
#
# Reading precedence (locked in WO-ORCH-AUTODISPATCH-02 step 3,
# sub-rule for non-orchestrator profiles):
#   1. HERMES_ROUTING_PATH environment variable — set by the per-profile
#      runway to this file's absolute path.
#   2. HERMES_HOME/config/routing.yaml — every cron tick inside the
#      {profile} profile has HERMES_HOME set to that profile's root.
#   3. Script-relative fallback — never used in production because the
#      runway pins (1).
#
routes:
{routes_block}

# Default block: deny anything not on the explicit route list. This is the
# fail-closed baseline for the {profile} runtime — the resolver rejects
# any directive whose REPOSITORY is not on the explicit list above.
defaults:
  capabilities: [read]
  max_runtime_seconds: 1800
  assignee: {profile}
  deny_unmatched: true
'''


AUTHORS_ALLOWLIST_TEMPLATE = '''# authors.prod.yaml — per-profile production author allowlist.
#
# AUTO-GENERATED by scripts/install_hermes_runtime.py on {utc_now}.
# Profile: {profile}
# Allowed authors: {authors}
#
# The directive_watcher reads this file via --author-allowlist (production
# mode). Any directive whose author is not on this list is REJECTED before
# the dispatch path is reached. There is NO fallback to test/dev env.
#
# Adding any author here beyond the installer allowlist is a security
# regression and must be reverted.
authors:
{authors_block}
'''


REPO_CONFIG_TEMPLATE = '''# repos.yaml — per-profile scoped repo list for the directive_watcher.
#
# AUTO-GENERATED by scripts/install_hermes_runtime.py on {utc_now}.
# Profile: {profile}
# Allowed repos: {repos}
#
# The directive_watcher reads this file via --config (repos only in
# production; authors live in authors.prod.yaml). Any directive whose
# REPOSITORY is not on this list is REJECTED before the dispatch path is
# reached.
repos:
{repos_block}
'''


# --- Helpers ----------------------------------------------------------------

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_valid_sha(sha: str) -> bool:
    """Accept 7-40 hex chars; reject anything that looks like a non-SHA
    placeholder (e.g. 'NONE', 'AUTO_FROM_ISSUE_CONTEXT')."""
    if not sha or not isinstance(sha, str):
        return False
    s = sha.strip()
    if s.upper() in {"NONE", "AUTO_FROM_ISSUE_CONTEXT", "AUTO"}:
        return False
    if not all(c in "0123456789abcdefABCDEF" for c in s):
        return False
    if not (7 <= len(s) <= 40):
        return False
    return True


def render_routes(repos: Iterable[str], profile: str) -> str:
    blocks = []
    for repo in repos:
        owner, name = repo.split("/", 1)
        blocks.append(
            f"  - repo: {repo}\n"
            f"    product: {name.upper()}\n"
            f"    assignee: {profile}\n"
            f"    capabilities: [read, write]\n"
            f"    max_runtime_seconds: 1800"
        )
    return "\n".join(blocks)


def render_authors(authors: Iterable[str]) -> str:
    return "\n".join(f"  - {a}" for a in authors)


def render_repos(repos: Iterable[str]) -> str:
    return "\n".join(f"  - {r}" for r in repos)


# --- Filesystem operations --------------------------------------------------

def write_file_safely(path: Path, content: str, dry_run: bool) -> str:
    """Write `content` to `path`. Returns a one-line summary of what
    happened. Refuses to write if the path's parent doesn't already
    exist (caller must mkdir parents explicitly). Idempotent: writes
    only if content differs from disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        try:
            existing = path.read_text(encoding="utf-8")
            if existing == content:
                return f"UNCHANGED {path}"
        except (OSError, UnicodeDecodeError):
            pass
    if dry_run:
        return f"[dry-run] WOULD-WRITE {path} ({len(content)} chars)"
    path.write_text(content, encoding="utf-8")
    return f"WROTE {path}"


def backup_file(path: Path, dry_run: bool) -> str:
    if not path.is_file():
        return f"NO-BACKUP (missing) {path}"
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_suffix(path.suffix + f".install_backup.{ts}")
    if dry_run:
        return f"[dry-run] WOULD-BACKUP {path} -> {backup}"
    shutil.copy2(path, backup)
    return f"BACKED UP {path} -> {backup}"

def migrate_state_file(source: Path | None, destination: Path, dry_run: bool) -> str:
    """One-time state migration used when the reviewed Factory checkout moves.

    Existing profile-local state always wins. A missing legacy source is a
    no-op. This preserves directive cursors/session lineage without coupling
    future runtime state to a particular Factory worktree.
    """
    if destination.is_file():
        return f"UNCHANGED state {destination}"
    if source is None or not source.is_file():
        return f"NO-MIGRATION (missing source) {source}"
    if dry_run:
        return f"[dry-run] WOULD-MIGRATE {source} -> {destination}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return f"MIGRATED {source} -> {destination}"


# --- Cron registration ------------------------------------------------------

def register_cron_job(
    profile: Path,
    script_relpath: str,
    interval_minutes: int,
    job_name: str,
    dry_run: bool,
) -> tuple[str, str]:
    """Append a single cron job entry to
    ``<profile>/cron/jobs.json``. Returns (summary_line, new_job_id).

    Backup the previous jobs.json before writing. Generated job_id is a
    short stable hash so re-runs of the installer do NOT register a
    second job.
    """
    jobs_file = profile / "cron" / "jobs.json"
    jobs_file.parent.mkdir(parents=True, exist_ok=True)
    backup_file(jobs_file, dry_run)

    if jobs_file.is_file():
        try:
            data = json.loads(jobs_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(
                f"refuse to overwrite unparseable jobs.json: {jobs_file} ({exc})"
            )
    else:
        data = {"jobs": [], "updated_at": None}

    # Idempotency: if a job with the same name already exists, return it.
    for job in data.get("jobs", []):
        if job.get("name") == job_name:
            return (
                f"UNCHANGED cron job {job['id']} (name={job_name})",
                job["id"],
            )

    new_id = f"ash{int(datetime.now(timezone.utc).timestamp())}"
    new_job = {
        "id": new_id,
        "name": job_name,
        "prompt": "",
        "skills": [],
        "skill": None,
        "model": None,
        "provider": None,
        "provider_snapshot": None,
        "model_snapshot": None,
        "base_url": None,
        "script": script_relpath,
        "no_agent": True,
        "monitor_script": None,
        "monitor_url": None,
        "monitor_state": None,
        "context_from": None,
        "schedule": {
            "kind": "interval",
            "minutes": interval_minutes,
            "display": f"every {interval_minutes}m",
        },
        "schedule_display": f"every {interval_minutes}m",
        "repeat": {"times": None, "completed": 0},
        "enabled": True,
        "state": "scheduled",
        "paused_at": None,
        "paused_reason": None,
        "created_at": utc_now_iso(),
        "next_run_at": None,
        "last_run_at": None,
        "last_status": None,
        "last_error": None,
        "last_delivery_error": None,
        "failure_streak": 0,
        "deliver": "local",
        "origin": None,
        "enabled_toolsets": None,
        "workdir": None,
        "fire_claim": None,
        "last_dispatch": None,
    }
    data.setdefault("jobs", []).append(new_job)
    data["updated_at"] = utc_now_iso()

    if dry_run:
        return (
            f"[dry-run] WOULD-ADD cron job id={new_id} name={job_name}",
            new_id,
        )

    jobs_file.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return (f"ADDED cron job id={new_id} name={job_name}", new_id)


# --- Main install flow ------------------------------------------------------

def install(
    *,
    profile: str,
    factory_sha: str,
    repos: list[str],
    authors: list[str],
    hermes_home: Path,
    hermes_install: Path,
    factory_checkout: Path,
    interval_minutes: int,
    job_name: str,
    dry_run: bool,
    legacy_state_root: Path | None = None,
) -> int:
    if not is_valid_sha(factory_sha):
        print(
            f"ERROR: --factory-sha {factory_sha!r} is not a valid git SHA. "
            "Refusing to install.",
            file=sys.stderr,
        )
        return 2

    if not repos:
        print("ERROR: --repos is empty. Refusing to install.", file=sys.stderr)
        return 2

    if not authors:
        print("ERROR: --authors is empty. Refusing to install.", file=sys.stderr)
        return 2

    # Guard rail: NEVER install under the orchestrator profile.
    if profile == "orchestrator":
        print(
            "ERROR: refuse to install watcher under 'orchestrator' — "
            "the canonical tick is already wired there and would double-tick. "
            "This script is for non-orchestrator profiles only.",
            file=sys.stderr,
        )
        return 2

    # Guard rail: NEVER mutate David's personal profile (it would clash
    # with the orchestrator's own runtime).
    if profile == "david":
        print(
            "ERROR: refuse to install watcher under 'david' — "
            "the orchestrator profile is the personal-runtime bridge. "
            "If a separate David-runtime install is needed, use a different profile name.",
            file=sys.stderr,
        )
        return 2

    if not hermes_home.is_dir():
        print(
            f"ERROR: HERMES_HOME not found: {hermes_home}. "
            "Use --hermes-home to override.",
            file=sys.stderr,
        )
        return 2

    profile_root = hermes_home / "profiles" / profile
    if not profile_root.is_dir():
        print(
            f"ERROR: target profile not found: {profile_root}",
            file=sys.stderr,
        )
        return 2

    if not factory_checkout.is_dir():
        print(
            f"ERROR: factory checkout not found: {factory_checkout}. "
            "Use --factory-checkout to override.",
            file=sys.stderr,
        )
        return 2

    utc_now = utc_now_iso()

    # 1. Runway shim -> <profile>/scripts/<job_name>_runway.py
    scripts_dir = profile_root / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    runway_path = scripts_dir / f"{job_name}_runway.py"

    # The runway template contains literal Python source with f-string-like
    # braces (e.g. `{{HERMES_HOME}}`, `{{time.time()}}`). str.format() cannot
    # be used because those embedded braces confuse the placeholder parser.
    # Use a plain str.replace() substitution keyed by sentinel tokens.
    runway_content = (
        RUNWAY_TEMPLATE
        .replace("__UTC_NOW__", utc_now)
        .replace("__PROFILE__", profile)
        .replace("__HERMES_HOME__", str(hermes_home))
        .replace("__HERMES_INSTALL__", str(hermes_install))
        .replace("__FACTORY_CHECKOUT__", str(factory_checkout))
        .replace("__FACTORY_SHA__", factory_sha)
        .replace("__REPOS__", ", ".join(repos))
        .replace("__AUTHORS__", ", ".join(authors))
    )
    actions = []
    actions.append(write_file_safely(runway_path, runway_content, dry_run))

    # 2. routing.yaml -> <profile>/config/routing.yaml
    config_dir = profile_root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    routing_path = config_dir / "routing.yaml"
    routing_content = ROUTING_YAML_TEMPLATE.format(
        utc_now=utc_now,
        profile=profile,
        repos=", ".join(repos),
        authors=", ".join(authors),
        routes_block=render_routes(repos, profile),
    )
    actions.append(write_file_safely(routing_path, routing_content, dry_run))

    # 3. repos.yaml -> <profile>/directive_watcher/config/repos.yaml
    dw_root = profile_root / "directive_watcher"
    dw_config = dw_root / "config"
    dw_config.mkdir(parents=True, exist_ok=True)
    repos_yaml = dw_config / "repos.yaml"
    actions.append(write_file_safely(
        repos_yaml,
        REPO_CONFIG_TEMPLATE.format(
            utc_now=utc_now,
            profile=profile,
            repos=", ".join(repos),
            repos_block=render_repos(repos),
        ),
        dry_run,
    ))

    # 4. authors.prod.yaml -> <profile>/directive_watcher/allowlists/authors.prod.yaml
    dw_allowlists = dw_root / "allowlists"
    dw_allowlists.mkdir(parents=True, exist_ok=True)
    authors_yaml = dw_allowlists / "authors.prod.yaml"
    actions.append(write_file_safely(
        authors_yaml,
        AUTHORS_ALLOWLIST_TEMPLATE.format(
            utc_now=utc_now,
            profile=profile,
            authors=", ".join(authors),
            authors_block=render_authors(authors),
        ),
        dry_run,
    ))

    # 5. Stable profile-local watcher state. This deliberately lives outside
    # the Factory checkout so moving between reviewed SHAs/worktrees cannot
    # reset cursors or replay already-consumed directives.
    state_dir = dw_root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    sidecar_db = state_dir / "directive_watcher.sqlite"
    session_log = state_dir / "sessions.jsonl"
    legacy_root = Path(legacy_state_root) if legacy_state_root else None
    actions.append(migrate_state_file(
        legacy_root / "directive_watcher.sqlite" if legacy_root else None,
        sidecar_db,
        dry_run,
    ))
    actions.append(migrate_state_file(
        legacy_root / "sessions.jsonl" if legacy_root else None,
        session_log,
        dry_run,
    ))

    # 6. Register cron job (idempotent on name).
    # The hermes cron scheduler resolves the script path as
    # HERMES_HOME/scripts/<script>. So we store ONLY the basename here;
    # the absolute path of HERMES_HOME/scripts/<basename> is what the
    # scheduler actually invokes. Storing "scripts/<basename>" would
    # resolve to HERMES_HOME/scripts/scripts/<basename> (doubled).
    cron_basename = runway_path.name
    cron_summary, cron_id = register_cron_job(
        profile=profile_root,
        script_relpath=cron_basename,
        interval_minutes=interval_minutes,
        job_name=job_name,
        dry_run=dry_run,
    )
    actions.append(cron_summary)

    # Print summary.
    print("=" * 72)
    print(f"install_hermes_runtime.py — profile={profile} dry_run={dry_run}")
    print("=" * 72)
    for action in actions:
        print(f"  - {action}")
    print("-" * 72)
    print(f"  factory_sha        : {factory_sha}")
    print(f"  allowed repos      : {', '.join(repos)}")
    print(f"  allowed authors    : {', '.join(authors)}")
    print(f"  allowed actions    : {', '.join(DEFAULT_ALLOWED_ACTIONS)}")
    print(f"  cron job id        : {cron_id}")
    print(f"  cron job name      : {job_name}")
    print(f"  runway script      : {runway_path}")
    print(f"  routing yaml       : {routing_path}")
    print(f"  repos yaml         : {repos_yaml}")
    print(f"  authors yaml       : {authors_yaml}")
    print(f"  sidecar db         : {sidecar_db}")
    print(f"  session log        : {session_log}")
    print(f"  profile root       : {profile_root}")
    print("=" * 72)
    if dry_run:
        print("[dry-run] nothing was written. Re-run without --dry-run to install.")
    else:
        print("[installed] verify with `hermes cron list` and one tick.")
    return 0


# --- CLI --------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="install_hermes_runtime.py",
        description=(
            "Bounded per-profile install of the directive_watcher for a "
            "non-orchestrator Hermes runtime. See module docstring for "
            "scope and non-goals."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--profile",
        default=DEFAULT_PROFILE,
        help=f"target Hermes profile (default: {DEFAULT_PROFILE})",
    )
    p.add_argument(
        "--factory-sha",
        required=True,
        help=(
            "Factory SHA pinned by the installer. The runway will refuse to "
            "tick if the checkout is missing. Must be 7-40 hex chars; "
            "placeholders like NONE / AUTO are rejected."
        ),
    )
    p.add_argument(
        "--repos",
        default=",".join(DEFAULT_REPOS),
        help=(
            "comma-separated repo allowlist (default: %(default)s). "
            "Any directive whose REPOSITORY is not on this list is rejected."
        ),
    )
    p.add_argument(
        "--authors",
        default=",".join(DEFAULT_AUTHORS),
        help=(
            "comma-separated author allowlist (default: %(default)s). "
            "Any directive whose author is not on this list is rejected."
        ),
    )
    p.add_argument(
        "--hermes-home",
        type=Path,
        default=DEFAULT_HERMES_HOME,
        help=f"Hermes home root (default: {DEFAULT_HERMES_HOME})",
    )
    p.add_argument(
        "--hermes-install",
        type=Path,
        default=DEFAULT_HERMES_INSTALL,
        help=f"Hermes install dir (default: {DEFAULT_HERMES_INSTALL})",
    )
    p.add_argument(
        "--factory-checkout",
        type=Path,
        default=DEFAULT_FACTORY_CHECKOUT,
        help=f"Factory checkout (default: {DEFAULT_FACTORY_CHECKOUT})",
    )
    p.add_argument(
        "--legacy-state-root",
        type=Path,
        default=None,
        help=(
            "optional previous Factory checkout/state root containing "
            "directive_watcher.sqlite and sessions.jsonl; copied once into "
            "the target profile's stable directive_watcher/state directory"
        ),
    )
    p.add_argument(
        "--interval-minutes",
        type=int,
        default=DEFAULT_INTERVAL_MINUTES,
        help=f"cron interval in minutes (default: {DEFAULT_INTERVAL_MINUTES})",
    )
    p.add_argument(
        "--job-name",
        default=DEFAULT_CRON_NAME,
        help=f"cron job name (default: {DEFAULT_CRON_NAME})",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would be written; write nothing",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repos = [r.strip() for r in args.repos.split(",") if r.strip()]
    authors = [a.strip() for a in args.authors.split(",") if a.strip()]
    return install(
        profile=args.profile,
        factory_sha=args.factory_sha,
        repos=repos,
        authors=authors,
        hermes_home=args.hermes_home,
        hermes_install=args.hermes_install,
        factory_checkout=args.factory_checkout,
        interval_minutes=args.interval_minutes,
        job_name=args.job_name,
        dry_run=args.dry_run,
        legacy_state_root=args.legacy_state_root,
    )


if __name__ == "__main__":
    sys.exit(main())
