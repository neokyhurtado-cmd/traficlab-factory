"""Sentinels for the [ASTRA_DIRECTIVE:v1] envelope (legacy compatibility).

The Phase 1 envelope introduced two sentinels as placeholder values
for fields that should be derived from the actual context (the repo
being polled, the comment's issue_number, the branch's current HEAD):

  - ``AUTO_FROM_ISSUE_CONTEXT`` — explicit sentinela name
  - ``NONE``                     — shorthand

The CONTEXT_BINDING_FAIL_CLOSED contracts (PR #19 closeout) formalise
the legacy behaviour: a sentinela means "resolve to the actual
context value before checking the binding".

This module is the SINGLE HOME for sentinela detection / resolution.
The handler uses ``resolve_expected_head()`` and ``resolve_branch()``
before invoking ``gh.get_branch_head``. The CLI uses ``is_sentinel``
when inspecting envelopes at parse time.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from directive_watcher.gh_client import GitHubClient


SENTINEL_AUTO_CTX = "AUTO_FROM_ISSUE_CONTEXT"
SENTINEL_NONE = "NONE"
_SENTINELS = frozenset({SENTINEL_AUTO_CTX, SENTINEL_NONE})

# Phase 1 envelope placeholder for the literal "no value" case.
# ``expected_head = ""`` (truly empty after strip) is NOT a sentinela —
# it is the strict fail-closed case (CONTEXT_BINDING_FAIL_CLOSED /
# HEAD_BINDING).


def is_sentinel(value: Optional[str]) -> bool:
    """True if ``value`` is the AUTO_FROM_ISSUE_CONTEXT / NONE sentinela.

    Case-insensitive on the value; ``None`` and empty strings are NOT
    sentinels (the empty case is its own fail-closed contract).
    """
    if not value:
        return False
    return value.strip().upper() in _SENTINELS


def resolve_branch_name(target_branch: str) -> str:
    """Resolve a sentinela ``TARGET_BRANCH`` to the repo's default branch.

    Production repo default is ``main``. Any literal value is returned
    unchanged.
    """
    if is_sentinel(target_branch):
        return "main"
    return target_branch


def resolve_expected_head(
    *,
    repo: str,
    target_branch: str,
    expected_head: Optional[str],
    gh: "GitHubClient",
) -> Optional[str]:
    """Resolve the legacy ``EXPECTED_HEAD`` sentinela to the actual HEAD.

    A sentinela (``AUTO_FROM_ISSUE_CONTEXT`` or ``NONE``) means "match
    whatever the current branch HEAD is" — we resolve it by querying
    ``gh.get_branch_head`` so the caller can compare against the
    resolved value (which always matches itself, by construction).

    A literal sha is returned unchanged so the caller can compare.

    Empty string returns ``None`` so the caller can surface its own
    fail-closed note ("EXPECTED_HEAD missing") — never a silent default.
    """
    if is_sentinel(expected_head):
        return gh.get_branch_head(repo, resolve_branch_name(target_branch))
    return expected_head