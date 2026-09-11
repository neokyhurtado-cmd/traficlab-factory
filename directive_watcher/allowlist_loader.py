"""Production author allowlist loader (SEGURO A, PR #19 Phase 4 closeout).

The Phase 3 closeout wired the CLI (``directive_watcher.cli --env=prod``)
to read the production author allowlist from an explicit file. But
production does NOT enter via the CLI: it enters via the cron-driven
``orchestrator/scripts/github_poller.py → run_directive_tick()``. The
Phase 4 re-audit (PR #19 comment 5630425864) found that this path was
hardcoding ``frozenset({"astra", "neokyhurtado-cmd"})`` — the CLI and
the poller were two different source-of-truths for the prod allowlist,
and the poller's source was wrong (and included ``astra``, which the
Phase 3 closeout explicitly removed from prod).

This module is the SINGLE loader for the production author allowlist.
Both ``directive_watcher.cli`` and ``github_poller.run_directive_tick``
call into it. The contract is:

  - The path is taken from ``HERMES_PROD_AUTHORS_ALLOWLIST`` (explicit
    operator choice) OR a shipped default path under the repo
    (``directive_watcher/allowlists/authors.prod.yaml``).
  - If the file is missing OR its ``allowlisted_authors`` list is empty
    OR malformed, ``MissingProdAllowlistError`` is raised. The caller
    MUST propagate (CLI returns 3; poller raises).
  - The list is YAML, case-insensitive on author logins, whitespace-
    tolerant (defensive).
  - No ``astra`` is in the default prod file; the loader does NOT
    special-case author names — the file is the source of truth. If
    an operator adds ``astra`` to the file, that's their choice;
    removing it is a policy decision recorded in
    ``allowlists/authors.prod.yaml.example``.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import FrozenSet


class MissingProdAllowlistError(Exception):
    """Raised when the production author allowlist is missing, malformed,
    or empty. The watcher MUST propagate this — never silently fall back
    to a hardcoded author list.

    The message is intentionally verbose: an operator triaging a
    fail-closed poller exit code must be able to diagnose the cause
    from the message alone, without reading source.
    """


# Default location shipped with the repo. The example file is the
# operator-facing template (with comments); the loader expects the
# production file at the path WITHOUT the .example suffix. If the
# operator has not provisioned the prod file, the loader MUST fail
# closed — that's the whole point of this seam.
_DEFAULT_PROD_AUTHORS_PATH = (
    Path(__file__).resolve().parent / "allowlists" / "authors.prod.yaml"
)


def resolve_default_prod_authors_path() -> Path:
    """Return the shipped default prod allowlist path. Public so tests
    can monkeypatch it deterministically (env-based defaulting would be
    flaky across CI hosts)."""
    return _DEFAULT_PROD_AUTHORS_PATH


def _path_from_env_or_default() -> Path:
    """Pick the prod allowlist path. Precedence:
    1. ``HERMES_PROD_AUTHORS_ALLOWLIST`` env var (operator choice).
    2. Shipped default under ``directive_watcher/allowlists/``.
    """
    env = os.environ.get("HERMES_PROD_AUTHORS_ALLOWLIST", "").strip()
    if env:
        return Path(env)
    return _DEFAULT_PROD_AUTHORS_PATH


def load_prod_author_allowlist(path: str | os.PathLike | None = None) -> FrozenSet[str]:
    """Load the production author allowlist from an explicit path.

    When ``path`` is None, the loader reads from
    ``HERMES_PROD_AUTHORS_ALLOWLIST`` or the shipped default.

    Returns a ``frozenset`` of canonical lowercase author logins.

    Raises ``MissingProdAllowlistError`` if:
      - the file does not exist,
      - the file is not readable,
      - the file is missing the ``allowlisted_authors`` key,
      - the ``allowlisted_authors`` value is not a non-empty list of
        non-empty strings.

    The loader NEVER falls back to a hardcoded default — that's the
    bug the Phase 4 re-audit closed.
    """
    if path is None:
        chosen = _path_from_env_or_default()
    else:
        chosen = Path(path)

    if not chosen.is_file():
        raise MissingProdAllowlistError(
            f"prod author allowlist file missing — fail-closed: {chosen}"
        )

    try:
        text = chosen.read_text(encoding="utf-8")
    except OSError as e:
        raise MissingProdAllowlistError(
            f"prod author allowlist file unreadable — fail-closed: "
            f"{chosen} ({type(e).__name__}: {e})"
        ) from e

    # Local import — keep the loader usable even if PyYAML isn't
    # installed for some pathological test environment (the rest of
    # the watcher requires PyYAML; the loader just degrades gracefully).
    import yaml  # type: ignore

    try:
        doc = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:  # type: ignore[attr-defined]
        raise MissingProdAllowlistError(
            f"prod author allowlist file malformed — fail-closed: "
            f"{chosen} ({type(e).__name__}: {e})"
        ) from e

    if not isinstance(doc, dict):
        raise MissingProdAllowlistError(
            f"prod author allowlist file top-level must be a mapping — "
            f"fail-closed: {chosen}"
        )

    authors_raw = doc.get("allowlisted_authors")
    if not isinstance(authors_raw, list):
        raise MissingProdAllowlistError(
            f"prod author allowlist file missing or wrong-shape "
            f"allowlisted_authors — fail-closed: {chosen}"
        )
    cleaned = [str(a).strip().lower() for a in authors_raw if str(a).strip()]
    if not cleaned:
        raise MissingProdAllowlistError(
            f"prod author allowlist file has empty allowlisted_authors — "
            f"fail-closed: {chosen}"
        )

    return frozenset(cleaned)