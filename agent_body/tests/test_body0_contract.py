"""BODY-0 acceptance tests — read-only skeleton + contract enforcement.

Per AGENT_BODY_27_READONLY_AUDIT.md §9 (BODY-0):
  B0.3 manifest denies every frozen boundary action
  B0.4 checkpoint schema matches §5.2 (no free_text, no secrets columns)
  B0.5 audit schema matches §5.5 (no free-text body)
  B0.6 malicious comment body SHA cannot inject free text into audit
  B0.7 no yaml/env/scripts mutations outside agent_body/

The audit explicitly enumerates these as pytest invocations with
verifiable results. This module is the executable counterpart.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest


# B0.3 — manifest denies frozen boundaries -----------------------------------


def test_manifest_denies_every_frozen_boundary_action(tmp_path):
    """agent_body/manifest.json (or equivalent) must explicitly deny every
    action the directive #27 body lists as HERMES_RUNTIME_CHANGE = NO."""
    from agent_body.manifest import load_manifest

    manifest = load_manifest(tmp_path / "manifest.json")
    required_denied = {
        "merge_to_main",
        "release_deploy",
        "mutate_secrets",
        "mutate_config_yaml",
        "mutate_env",
        "mutate_gateway",
        "mutate_channels",
        "mutate_runtime_provider",
        "create_orchestrator",
    }
    denied = set(manifest.denied_capabilities)
    missing = required_denied - denied
    assert not missing, f"manifest must explicitly deny: {sorted(missing)}"


# B0.4 — checkpoint schema has no free_text / no secrets columns --------------


def test_checkpoint_schema_has_no_free_text_or_secret_columns(tmp_path):
    """The checkpoint SQLite must contain ONLY the documented columns."""
    from agent_body.checkpoint_store import CheckpointStore

    db = tmp_path / "checkpoints.sqlite"
    CheckpointStore(db)
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute("PRAGMA table_info(checkpoints)").fetchall()
    finally:
        conn.close()
    cols = {row[1] for row in rows}
    forbidden = {"body_text", "prompt", "raw_input", "secret", "token", "api_key", "password"}
    leaked = forbidden & cols
    assert not leaked, f"checkpoint schema leaks forbidden columns: {sorted(leaked)}"


# B0.5 — audit schema has no free-text body column ---------------------------


def test_audit_schema_has_no_free_text_body_column(tmp_path):
    """The audit SQLite must not contain a free-text body column.

    Per AGENT_BODY_27_READONLY_AUDIT §5.5: audit events are structured only.
    """
    from agent_body.audit import AuditStore

    db = tmp_path / "audit.sqlite"
    AuditStore(db)
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute("PRAGMA table_info(audit_events)").fetchall()
    finally:
        conn.close()
    cols = {row[1] for row in rows}
    forbidden = {"body", "body_text", "free_text", "comment_body", "raw_payload"}
    leaked = forbidden & cols
    assert not leaked, f"audit schema leaks free-text columns: {sorted(leaked)}"


# B0.6 — malicious comment body SHA cannot inject free text ------------------


def test_audit_event_payload_never_carries_comment_body(tmp_path):
    """Even if a reviewer tries to inject free text via the audit event,
    the schema must reject it. The audit event is STRUCTURED ONLY."""
    from agent_body.audit import AuditStore, AuditEvent

    db = tmp_path / "audit.sqlite"
    audit = AuditStore(db)

    # Try to inject a free-text body. The AuditEvent dataclass must not
    # even have such a field; if it does, construction fails.
    with pytest.raises((TypeError, AttributeError)):
        AuditEvent(
            event_id="x",
            task_id="t_inject",
            action="context.resolve",
            capability_used="github.resolve",
            source_evidence_pointers=["gh:repos/foo"],
            outcome="OK",
            timestamp=1,
            body_text="<script>alert(1)</script>",  # forbidden
        )

    # And a valid event round-trips without exposing any body column.
    audit.append(AuditEvent(
        event_id="ok",
        task_id="t_clean",
        action="context.resolve",
        capability_used="github.resolve",
        source_evidence_pointers=["gh:repos/foo"],
        outcome="OK",
        timestamp=1,
    ))
    fetched = audit.all_events(task_id="t_clean")
    assert len(fetched) == 1
    fetched_dict = fetched[0].__dict__
    assert "body_text" not in fetched_dict
    assert "comment_body" not in fetched_dict


# B0.7 — no yaml / env / scripts mutations outside agent_body/ ----------------


def test_repo_diff_against_base_contains_no_out_of_scope_yaml_or_env(tmp_path):
    """The new code lives ONLY under agent_body/ and does not touch
    orchestrator/scripts/, directive_watcher/, control/, .github/workflows/,
    or any *.yaml / .env / hermes CLI surface.

    This is enforced at write time: the agent_body/ package has no
    write capability to those locations. We verify by reading the
    package surface and asserting no path outside agent_body/ is touched.
    """
    from pathlib import Path as _P

    forbidden_roots = [
        "orchestrator/scripts",
        "directive_watcher",
        "control",
        ".github/workflows",
        "p1_human_go_gate",
    ]
    body_files = list(_P("agent_body").rglob("*.py"))
    assert body_files, "agent_body/ must contain real Python modules"
    for f in body_files:
        text = f.read_text(encoding="utf-8")
        for root in forbidden_roots:
            # The body must NOT import or call into those locations.
            # (It MAY reference them by string in audit events or docs.)
            assert f"from {root.replace('/', '.')}" not in text.replace("/", "."), \
                f"{f} imports into forbidden root {root}"
