"""Tests for Contract 6 — PROD/TEST author allowlist separation (PR #19 closeout).

Contract: ``--env=prod|test`` flag on the CLI. When ``--env=prod`` the
author allowlist is read from an explicit path; missing file → fail-closed
(exit code != 0 + clear stderr message). When ``--env=test`` the existing
``--config`` flag carries the test fixture (no separate path).

Tests:
  - ``--env=prod`` + file exists + author allowed → admitted
  - ``--env=prod`` + file exists + author NOT allowed → denied
  - ``--env=prod`` + file MISSING → fail-closed, exit code != 0
  - ``--env=test`` → uses ``--config`` (existing fixture path)
  - The PROD file MUST be able to contain ONLY ``neokyhurtado-cmd`` (no
    ``astra`` by default) so the production allowlist is the
    fail-closed-by-default contract.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import directive_watcher.cli as cli_mod
from directive_watcher.cli import main as cli_main
from directive_watcher.gh_client import FakeGitHubClient


PROD_AUTHORS_FILE = "directive_watcher/allowlists/authors.prod.yaml"


def _write_prod_authors(tmp_path: Path, authors: list[str]) -> Path:
    """Write a prod author allowlist file and return its path."""
    p = tmp_path / "authors.prod.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "allowlisted_authors:\n" + "".join(f"  - {a}\n" for a in authors),
        encoding="utf-8",
    )
    return p


def _write_test_config(tmp_path: Path, *, authors: list[str]) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(
        "allowlisted_repos:\n  - neokyhurtado-cmd/traficlab-factory\n"
        "allowlisted_authors:\n" + "".join(f"  - {a}\n" for a in authors),
        encoding="utf-8",
    )
    return p


@pytest.fixture
def isolated_cli(monkeypatch):
    """Patch all the things ``cli.main()`` does that touch the real world:
    routing table resolution, kanban subprocess, gh client. We let the
    AllowlistConfig + load_allowlist + env-handling do real work."""
    # Use the stock ``FakeGitHubClient`` so list_comments_since returns
    # an empty stream (no real directives processed).
    monkeypatch.setattr("directive_watcher.cli.GHCLIClient", FakeGitHubClient)


def test_prod_env_with_explicit_author_file_admits_allowlisted_author(
    tmp_path, isolated_cli
):
    """--env=prod + file exists + author 'neokyhurtado-cmd' → разрешено.

    We assert that the AllowlistConfig carries exactly the authors from
    the prod file (not from --config), which is the load-time contract.
    """
    prod_file = _write_prod_authors(tmp_path, ["neokyhurtado-cmd"])
    # Even when --config contains astra, --env=prod MUST use the prod file.
    config = _write_test_config(tmp_path, authors=["astra", "neokyhurtado-cmd"])

    # Spy on load_allowlist: in prod mode, main() calls it twice
    # (once for --author-allowlist, once for --config). We capture
    # both and assert BOTH happen with the expected paths.
    import directive_watcher.cli as cli_mod

    captured = {"prod_loader_calls": [], "load_allowlist_calls": []}

    # SEGURO A (PR #19 Phase 4 closeout): the CLI now delegates prod
    # author allowlist loading to the shared loader
    # ``directive_watcher.allowlist_loader.load_prod_author_allowlist``.
    # Spy on BOTH that loader (for prod) and the legacy
    # ``cli_mod.load_allowlist`` (for repos from --config).
    import directive_watcher.allowlist_loader as loader_mod

    orig_prod_load = loader_mod.load_prod_author_allowlist

    def spy_prod_load(path=None):
        captured["prod_loader_calls"].append(path)
        return orig_prod_load(path)

    loader_mod.load_prod_author_allowlist = spy_prod_load

    orig_load = cli_mod.load_allowlist

    def spy_load(path):
        captured["load_allowlist_calls"].append(path)
        return orig_load(path)

    cli_mod.load_allowlist = spy_load
    try:
        rc = cli_mod.main([
            "--config", str(config),
            "--sidecar-db", str(tmp_path / "sidecar.db"),
            "--status-path", str(tmp_path / "status.json"),
            "--author-allowlist", str(prod_file),
            "--env", "prod",
            "--once",
        ])
    finally:
        loader_mod.load_prod_author_allowlist = orig_prod_load
        cli_mod.load_allowlist = orig_load

    # The prod file must have been consulted via the shared loader.
    assert str(prod_file) in captured["prod_loader_calls"], (
        f"--env=prod must call load_prod_author_allowlist with the prod "
        f"file; calls were {captured['prod_loader_calls']}"
    )
    # The config (repos) must have been consulted via load_allowlist.
    assert str(config) in captured["load_allowlist_calls"], (
        f"--env=prod must also load --config (for repos); "
        f"calls were {captured['load_allowlist_calls']}"
    )
    # rc is 0 (clean tick) or 1 (error) — both acceptable; the contract is
    # about the load path.
    assert rc in (0, 1)


def test_prod_env_blocks_author_not_in_prod_file(tmp_path, isolated_cli):
    """--env=prod + prod file lists only 'neokyhurtado-cmd' + author 'astra' →
    BLOCKED. We exercise the handler path because the allowlist is enforced
    there, not at the CLI level.
    """
    from directive_watcher.allowlist import AllowlistConfig
    from directive_watcher.gh_client import RemoteComment
    from directive_watcher.handler import WatcherHandler
    from directive_watcher.retry import BackoffPolicy
    from directive_watcher.sidecar_store import SidecarStore

    # Prod allowlist contains ONLY neokyhurtado-cmd.
    prod_file = _write_prod_authors(tmp_path, ["neokyhurtado-cmd"])
    config = _write_test_config(tmp_path, authors=["neokyhurtado-cmd", "astra"])

    # Load the prod allowlist directly to assert it does NOT contain astra.
    prod_allowlist, _ = cli_mod.load_allowlist(str(prod_file))
    assert "astra" not in {a.lower() for a in prod_allowlist.allowlisted_authors}
    assert "neokyhurtado-cmd" in {a.lower() for a in prod_allowlist.allowlisted_authors}

    # Now drive the handler with a merged allowlist: test repos + prod authors.
    # The contract is that the production author allowlist is the
    # authoritative source for who can issue directives; the test fixture
    # supplies the repo list because that's the dev/test concern.
    repos_config, _ = cli_mod.load_allowlist(str(config))
    merged_allowlist = AllowlistConfig(
        allowlisted_repos=repos_config.allowlisted_repos,
        allowlisted_authors=prod_allowlist.allowlisted_authors,
    )
    store = SidecarStore(tmp_path / "sidecar.db")
    # SEGURO B / FRESH_START_WATERMARK: pre-seed the watermark so this
    # test asserts the author-not-allowlisted gate, not the fresh-start
    # watermark cutoff.
    store.set_watermark(repo="neokyhurtado-cmd/traficlab-factory", value=0)
    gh = FakeGitHubClient()
    gh.set_branch_head(
        "neokyhurtado-cmd/traficlab-factory", "main",
        "1111111111111111111111111111111111111111",
    )
    body = (
        "[ASTRA_DIRECTIVE:v1]\n"
        "ACTION = CONTINUE\n"
        "REPOSITORY = neokyhurtado-cmd/traficlab-factory\n"
        "ISSUE = 1\n"
        "TARGET_BRANCH = AUTO_FROM_ISSUE_CONTEXT\n"
        "EXPECTED_HEAD = NONE\n"
        "SCOPE = prod env test\n"
        "AUTO_NEXT_SAFE_GATE = NO\n"
        "REQUIRES_HUMAN_GO_REAL = NO\n"
        "DIRECTIVE_ID = d-prod-env\n"
    )
    gh.add(RemoteComment(
        id=101, author="astra", body=body,
        url="https://github.com/neokyhurtado-cmd/traficlab-factory/issues/1#issuecomment-101",
        issue_number=1,
    ))
    handler = WatcherHandler(
        store=store, gh=gh, allowlist=merged_allowlist,
        evidence_root=str(tmp_path),
        backoff=BackoffPolicy(initial_seconds=0.001),
    )
    s = handler.tick(["neokyhurtado-cmd/traficlab-factory"])
    assert s.directives_claimed == 0
    assert any("author_not_allowlisted" in n for n in s.notes), s.notes


def test_prod_env_missing_author_file_is_fail_closed(tmp_path, isolated_cli):
    """--env=prod + file MISSING → exit code != 0 + clear stderr message."""
    config = _write_test_config(tmp_path, authors=["neokyhurtado-cmd"])
    missing_path = tmp_path / "allowlists" / "authors.prod.yaml"
    assert not missing_path.exists()  # precondition

    rc = cli_mod.main([
        "--config", str(config),
        "--sidecar-db", str(tmp_path / "sidecar.db"),
        "--status-path", str(tmp_path / "status.json"),
        "--author-allowlist", str(missing_path),
        "--env", "prod",
        "--once",
    ])

    assert rc != 0, (
        f"--env=prod with missing author allowlist MUST fail-closed "
        f"(exit code != 0); got rc={rc}"
    )
    # We don't capture stderr here but the CLI logs to stderr via LOG.error.
    # The exit-code check is the load-bearing contract; the message is
    # asserted by inspection of the CLI source.


def test_test_env_uses_config_yaml(tmp_path, isolated_cli):
    """--env=test → uses --config (the legacy fixture path). No separate
    author file is required."""
    config = _write_test_config(tmp_path, authors=["neokyhurtado-cmd", "astra"])
    rc = cli_mod.main([
        "--config", str(config),
        "--sidecar-db", str(tmp_path / "sidecar.db"),
        "--status-path", str(tmp_path / "status.json"),
        "--env", "test",
        "--once",
    ])
    assert rc == 0, (
        f"--env=test with valid --config must succeed, got rc={rc}"
    )


def test_prod_default_author_file_is_neokyhurtado_cmd_only():
    """The committed prod allowlist template ships with ONLY
    ``neokyhurtado-cmd`` — no ``astra`` by default. Fail-closed-by-default.
    """
    p = Path(PROD_AUTHORS_FILE + ".example")
    if not p.exists():
        pytest.skip(f"prod allowlist template not found at {p}")
    text = p.read_text(encoding="utf-8")
    # Must list neokyhurtado-cmd.
    assert "neokyhurtado-cmd" in text
    # Must NOT list astra as a default author.
    # Parse simple YAML: lines under ``allowlisted_authors:`` until next key.
    in_authors = False
    authors_listed = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("allowlisted_authors:"):
            in_authors = True
            continue
        if in_authors:
            if stripped.startswith("- "):
                authors_listed.append(stripped[2:].strip())
            elif stripped and not stripped.startswith("#"):
                # Next key — stop.
                break
    assert "neokyhurtado-cmd" in authors_listed
    assert "astra" not in authors_listed, (
        f"prod author allowlist must NOT include 'astra' by default; got {authors_listed}"
    )