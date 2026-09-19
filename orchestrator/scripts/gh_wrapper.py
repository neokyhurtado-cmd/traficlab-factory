"""
gh wrapper — the SINGLE place in the orchestrator that spawns ``gh``
to list issues, create task sources, etc.

Why this module exists (Phase 3 re-audit, PR #19 comment 5629796729,
P0 #1 / WO_POLLER_RUNTIME)
-------------------------------------------------------------------
The Phase 3 single-kanban-primitive refactor removed ``import
subprocess`` from ``github_poller.py`` but ``gh_list_work_orders()``
still called ``subprocess.run()`` directly. The test suite never
exercised the real ``gh_list_work_orders()`` / ``main()`` path — it
mocked ``kanban_primitive.subprocess.run`` — so the latent
``NameError: name 'subprocess' is not defined`` survived.

The fix: every ``gh`` invocation in this codebase now lives in
ONE module: this one. ``github_poller.py`` calls into it via
``GithubClient``; ``github_poller.py`` does not import ``subprocess``
at all.

This is the canonical gh-wrapper for the orchestrator poller.
The directive_watcher.gh_client module serves a similar purpose for
the directive watcher path (which has a richer GitHub API surface for
ACK/RESULT posting) — they are NOT the same module, by design,
because the domains are different (WO transport vs. Directive
transport). Multiple thin wrappers around the same ``gh`` binary
are allowed — they delegate to ``gh`` and nothing else.
"""
from __future__ import annotations

import json
import os
import subprocess
from typing import Optional


class GHError(RuntimeError):
    """Raised when ``gh`` returns a non-zero exit code (auth, repo
    not found, rate limit, malformed response, etc.)."""

    def __init__(self, message: str, *, exit_code: int = -1, stderr: str = ""):
        super().__init__(message)
        self.exit_code = exit_code
        self.stderr = stderr


class GithubClient:
    """Production gh wrapper used by ``github_poller``.

    The class is small on purpose: every method is one gh command.
    No method here ships ``hermes kanban create`` — that lives in
    ``directive_watcher.kanban_primitive`` (P0 #1 + the Phase 3
    single-primitive contract, see comment 5629293070).
    """

    def __init__(self, gh_bin: str = "gh", timeout: int = 60) -> None:
        self._gh = gh_bin
        self._timeout = timeout

    def list_issues_with_label(
        self,
        repo: str,
        label: str,
        *,
        state: str = "open",
        limit: int = 50,
        json_keys: str = "number,title,body,labels,state",
    ) -> list[dict]:
        """Return issue dicts from ``gh issue list`` matching the filter.

        Matches the production call shape ``github_poller.py`` used
        before Phase 3 split subprocess out of the adapter. Empty
        stdout (clean --json output) returns ``[]``.
        """
        cmd = [
            self._gh, "issue", "list",
            "--repo", repo,
            "--label", label,
            "--state", state,
            "--limit", str(limit),
            "--json", json_keys,
        ]
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=self._timeout
        )
        if proc.returncode != 0:
            raise GHError(
                f"gh issue list failed for {repo} (exit {proc.returncode}): "
                f"{(proc.stderr or '').strip()[:300]}",
                exit_code=proc.returncode,
                stderr=proc.stderr,
            )
        try:
            return json.loads(proc.stdout or "[]")
        except json.JSONDecodeError as e:
            raise GHError(
                f"could not parse gh issue list JSON for {repo}: {e}"
            ) from e


def get_default_client() -> GithubClient:
    """Helper used by ``github_poller`` to construct its client.

    Tests monkeypatch this function (or ``GithubClient`` itself) to
    inject a fake. Production code calls it with no arguments.
    """
    return GithubClient(gh_bin=os.environ.get("GH_BIN", "gh"))
