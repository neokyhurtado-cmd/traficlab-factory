"""Allowlist + protected-boundary enforcement.

The watcher is fail-closed: every directive must satisfy BOTH conditions:

  1. The repository is in ``config.allowlisted_repos``.
  2. The comment author is in ``config.allowlisted_authors``.

Additionally, a directive that requests a protected action (merge to
protected/main, canonical DB write, release, public exposure, secrets
mutation, destructive FS) MUST carry an explicit ``REQUIRES_HUMAN_GO_REAL = YES``
AND present a verifiable HUMAN_GO_REAL evidence token (this ticket only
validates the gate is presented — David owns the actual token issuance).

Never execute arbitrary shell text. Never infer merge/release authorization
from a permissive ``ACTION``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from directive_watcher.directive_parser import Directive


# Actions that the watcher can dispatch directly. They are all bounded,
# reversible, repository-scoped operations.
SAFE_ACTIONS = frozenset({
    "CONTINUE",
    "REAUDIT_FIX",
    "INVESTIGATE",
    "TEST",
    "BUILD",
    "OPEN_PR",
})

# Actions that would normally be protected. We keep this list short on
# purpose — the canonical contract is: director can wake, but cannot
# manufacture authorization for any of these without an explicit HUMAN_GO_REAL.
PROTECTED_ACTIONS = frozenset()  # none of the SAFE_ACTIONS are protected by
                                  # themselves; protection is a separate check
                                  # via the protected_boundary() helper below.


@dataclass(frozen=True)
class AllowlistConfig:
    """Static allowlists read from the watcher's config file.

    Membership is exact-match (case-insensitive on author, case-sensitive on
    repo because GitHub repo names are). No wildcards, no globs — the rule
    from #18 is "fail closed", so a misspelled repo or author must NOT match.
    """

    allowlisted_repos: frozenset[str] = field(default_factory=frozenset)
    allowlisted_authors: frozenset[str] = field(default_factory=frozenset)

    def repo_allowed(self, repo: str) -> bool:
        return repo.strip() in self.allowlisted_repos

    def author_allowed(self, author: str) -> bool:
        return author.strip().lower() in {
            a.strip().lower() for a in self.allowlisted_authors
        }


@dataclass(frozen=True)
class ProtectedBoundaryRequest:
    """A request to perform a protected operation.

    The watcher never performs these directly — it surfaces them to the
    Director, which presents the gate. This module only validates that the
    director has the *context* required to evaluate the gate.
    """

    kind: str  # MERGE_PROTECTED | DB_WRITE | SUINI_WRITE | SECRETS_MUTATE |
               # RELEASE_DEPLOY | PUBLIC_BIND | DESTRUCTIVE_FS
    repository: str
    evidence_token: str  # non-empty when HUMAN_GO_REAL evidence is presented


PROTECTED_BOUNDARY_KINDS = frozenset({
    "MERGE_PROTECTED",
    "DB_WRITE",
    "SUINI_WRITE",
    "SECRETS_MUTATE",
    "RELEASE_DEPLOY",
    "PUBLIC_BIND",
    "DESTRUCTIVE_FS",
})


class GateError(Exception):
    """Raised when a protected-boundary request is malformed or insufficient."""


def repo_in_allowlist(directive: Directive, allowlist: AllowlistConfig) -> bool:
    """True iff the directive's repository is explicitly allowlisted.

    Fail-closed: an unknown repo never silently executes.
    """
    return allowlist.repo_allowed(directive.repository)


def author_in_allowlist(author: str, allowlist: AllowlistConfig) -> bool:
    """True iff the comment author is explicitly allowlisted.

    Fail-closed: an unknown author never silently executes.
    """
    return allowlist.author_allowed(author)


def evaluate_protected_boundary(
    directive: Directive,
    request: ProtectedBoundaryRequest | None,
) -> "ProtectedBoundaryVerdict":
    """Evaluate whether a protected-boundary request may be presented to
    the Director.

    The director is *allowed to wake* on any directive. The director is
    only *allowed to execute* a protected request when:

      - the directive itself has ``REQUIRES_HUMAN_GO_REAL = YES``, AND
      - a non-empty ``ProtectedBoundaryRequest`` is presented, AND
      - the request kind is recognised, AND
      - the request carries a non-empty evidence token.

    The actual performance of the protected action is OUT OF SCOPE for
    this ticket — even when the gate is presented, the watcher surfaces a
    ``HUMAN_GO_REAL_REQUIRED`` result so David can execute it.
    """

    if request is None:
        return ProtectedBoundaryVerdict(
            wake_allowed=True,
            execution_allowed=False,
            reason="no protected-boundary request presented",
        )
    if request.kind not in PROTECTED_BOUNDARY_KINDS:
        raise GateError(f"unknown protected-boundary kind: {request.kind!r}")
    if not request.evidence_token.strip():
        raise GateError("protected-boundary request missing evidence_token")
    if not directive.requires_human_go_real:
        return ProtectedBoundaryVerdict(
            wake_allowed=True,
            execution_allowed=False,
            reason=(
                "directive did not declare REQUIRES_HUMAN_GO_REAL = YES; "
                "wake allowed, execution denied"
            ),
        )
    return ProtectedBoundaryVerdict(
        wake_allowed=True,
        execution_allowed=False,  # never auto-execute; David owns the gate
        reason="HUMAN_GO_REAL gate presented; execution deferred to David",
    )


@dataclass(frozen=True)
class ProtectedBoundaryVerdict:
    wake_allowed: bool
    execution_allowed: bool  # always False in this ticket
    reason: str
