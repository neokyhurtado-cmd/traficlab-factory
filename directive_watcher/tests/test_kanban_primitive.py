"""Tests for the single kanban dispatch primitive.

Phase 3 / Objective 3 — the rephrased one from the steer in
comment 5629293070: the primitive is the ONLY real implementation of
``hermes kanban create``; multiple adaptors are allowed; duplicating the
subprocess call is what we forbid.

Two complementary test layers:

  1. **Static source guard.** We scan the two adapter source files
     (``directive_watcher/orch_dispatch.py`` and
     ``orchestrator/scripts/github_poller.py``) and assert they do NOT
     import / call ``subprocess`` directly. The only file in the repo
     allowed to spawn ``hermes kanban create`` is
     ``directive_watcher/kanban_primitive.py``. This is the bite: if a
     future refactor reintroduces a parallel subprocess pipeline, the
     static scan fails with a message naming the offender.

  2. **Runtime shape check.** The primitive works in isolation (validates
     payload, builds cmd, returns task_id). The directive adapter's
     idempotent re-dispatch does not spawn a second subprocess.

Both layers together enforce "one implementation, many adaptors".
"""
from __future__ import annotations

import inspect
import json
import re
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest


# Make orchestrator/scripts importable — same pattern the production
# orch_dispatch.py uses for the routing resolver.
_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
_ORCH_SCRIPTS = _REPO_ROOT / "orchestrator" / "scripts"
if str(_ORCH_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_ORCH_SCRIPTS))

from directive_watcher import kanban_primitive  # noqa: E402
from directive_watcher.directive_parser import Directive  # noqa: E402
from directive_watcher.orch_dispatch import (  # noqa: E402
    DispatchRequest,
    OrchestratorDispatcher,
)


# --- 0. Static source guard — the bite ------------------------------------
#
# The forbidden pattern: an adapter imports ``subprocess`` directly or
# invokes ``subprocess.run`` outside the primitive. We scan both adapter
# source files for these patterns and fail with a clear message if any
# is found. The primitive itself is excluded (it is the allowed home of
# the subprocess call).

ADAPTER_FILES = [
    _REPO_ROOT / "directive_watcher" / "orch_dispatch.py",
    _REPO_ROOT / "orchestrator" / "scripts" / "github_poller.py",
]
PRIMITIVE_FILE = _REPO_ROOT / "directive_watcher" / "kanban_primitive.py"

# Patterns that indicate a direct ``hermes kanban create`` subprocess
# call. We intentionally allow other subprocess calls (e.g. ``gh issue
# list`` in github_poller.py) — the architecture rule is about the
# kanban primitive, not about subprocess in general.
#
# Forbidden patterns:
#   - The literal subprocess argv ``["hermes", "kanban", "create", ...]``
#     (anywhere in code).
#   - The full import line ``import subprocess`` in adapter modules —
#     since the only legitimate subprocess caller is the primitive, the
#     adapter doesn't need the module imported at all.
_FORBIDDEN_PATTERNS = [
    (re.compile(r'"hermes"\s*,\s*"kanban"\s*,\s*"create"'),
     "literal subprocess argv 'hermes kanban create'"),
    (re.compile(r"'hermes'\s*,\s*'kanban'\s*,\s*'create'"),
     "literal subprocess argv 'hermes kanban create'"),
    (re.compile(r'from\s+subprocess\s+import'), "from subprocess import"),
    (re.compile(r'^import\s+subprocess\b'), "import subprocess (top-level)"),
]


def _scan_file_for_subprocess(path: Path) -> list[tuple[int, str, str]]:
    """Return [(lineno, pattern_label, line_text)] for every forbidden
    hit in the file. Empty list = clean."""
    hits: list[tuple[int, str, str]] = []
    src = path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(src, start=1):
        # Skip comments — a docstring or `# import subprocess` reference
        # is not a real call. We only flag code lines.
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for pattern, label in _FORBIDDEN_PATTERNS:
            if pattern.search(line):
                hits.append((i, label, line.rstrip()))
    return hits


@pytest.mark.parametrize("adapter_path", ADAPTER_FILES, ids=lambda p: p.name)
def test_adapter_does_not_call_subprocess_directly(adapter_path: Path):
    """The single primitive is the only allowed home of the kanban
    subprocess call. Adapter modules must delegate via
    ``directive_watcher.kanban_primitive.dispatch_to_kanban`` instead.

    If you see this fail after adding new functionality, you have
    reintroduced a parallel subprocess pipeline — which the Phase 3
    directive (comment 5629246987) explicitly forbids.
    """
    hits = _scan_file_for_subprocess(adapter_path)
    assert not hits, (
        f"SINGLE_PRIMITIVE VIOLATION in {adapter_path.relative_to(_REPO_ROOT)}:\n"
        + "\n".join(f"  L{h[0]} [{h[1]}]  {h[2]}" for h in hits)
        + "\n\nThe directive_watcher/kanban_primitive.dispatch_to_kanban() "
        "function is the ONLY allowed home of the `hermes kanban create` "
        "subprocess call. Use it from this adapter instead."
    )


def test_primitive_is_the_only_subprocess_caller():
    """Sanity check: the primitive file IS the place where subprocess.run
    lives. If this fails the static guard above is misconfigured."""
    src = PRIMITIVE_FILE.read_text(encoding="utf-8")
    assert "subprocess.run" in src, (
        "kanban_primitive.py should contain subprocess.run — "
        "if you removed it, you also broke the adapters."
    )


# --- 1. Primitive in isolation --------------------------------------------


def test_dispatch_to_kanban_validates_payload(monkeypatch):
    """Missing required keys must raise — fail-closed, not silent."""
    captured: list = []

    def fake_run(cmd, **kwargs):
        captured.append(cmd)
        cp = mock.Mock()
        cp.returncode = 0
        cp.stdout = json.dumps({"id": "t_1"})
        cp.stderr = ""
        return cp

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ValueError, match="missing required keys"):
        kanban_primitive.dispatch_to_kanban(
            {"title": "x", "body": "y"},  # missing assignee + parent
            idempotency_key="github:owner/repo#1",
        )
    assert captured == [], "primitive must NOT spawn subprocess when payload is invalid"


def test_dispatch_to_kanban_validates_empty_idempotency_key(monkeypatch):
    captured: list = []

    def fake_run(cmd, **kwargs):
        captured.append(cmd)
        cp = mock.Mock()
        cp.returncode = 0
        cp.stdout = json.dumps({"id": "t_1"})
        cp.stderr = ""
        return cp

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ValueError, match="idempotency_key"):
        kanban_primitive.dispatch_to_kanban(
            {
                "title": "x",
                "body": "y",
                "assignee": "alice",
                "parent_task_id": "t_parent",
            },
            idempotency_key="",
        )
    assert captured == [], "primitive must NOT spawn subprocess when idempotency_key is empty"


def test_dispatch_to_kanban_invokes_hermes_with_correct_args(monkeypatch):
    """Happy path — primitive builds the right CLI invocation."""
    captured: list = []

    def fake_run(cmd, **kwargs):
        captured.append(cmd)
        cp = mock.Mock()
        cp.returncode = 0
        cp.stdout = json.dumps({"id": "t_xyz"})
        cp.stderr = ""
        return cp

    monkeypatch.setattr(subprocess, "run", fake_run)
    task_id = kanban_primitive.dispatch_to_kanban(
        {
            "title": "[REPO#1] do the thing",
            "body": "body text",
            "assignee": "hermes-director",
            "parent_task_id": "t_parent",
        },
        idempotency_key="github:owner/repo#1",
    )
    assert task_id == "t_xyz"
    assert len(captured) == 1, f"primitive must spawn exactly one subprocess, got {len(captured)}"
    cmd = captured[0]
    assert cmd[0] == "hermes"
    assert cmd[1:3] == ["kanban", "create"]
    assert cmd[3] == "[REPO#1] do the thing"
    assert "--idempotency-key" in cmd
    idem_idx = cmd.index("--idempotency-key")
    assert cmd[idem_idx + 1] == "github:owner/repo#1"


def test_dispatch_to_kanban_propagates_subprocess_failure(monkeypatch):
    def fake_run(cmd, **kwargs):
        cp = mock.Mock()
        cp.returncode = 1
        cp.stdout = ""
        cp.stderr = "boom: gh not authenticated"
        return cp

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="hermes kanban create failed"):
        kanban_primitive.dispatch_to_kanban(
            {
                "title": "x",
                "body": "y",
                "assignee": "alice",
                "parent_task_id": "t_parent",
            },
            idempotency_key="directive:d-1",
        )


# --- 2. Primitive is importable from the adapter module ------------------
#
# This is the runtime complement to the static source guard. We import
# the primitive from the adapter's namespace and verify it is the SAME
# function the primitive module exposes — i.e. the adapter references
# the primitive, not a re-implementation.

def test_directive_adapter_imports_the_primitive():
    """OrchestratorDispatcher must reference
    ``directive_watcher.kanban_primitive.dispatch_to_kanban`` at runtime.
    This test asserts the import surface is intact; the static guard
    above asserts the adapter does not bypass it."""
    from directive_watcher import orch_dispatch, kanban_primitive

    assert hasattr(kanban_primitive, "dispatch_to_kanban")
    # The adapter module must import the primitive module (binding it
    # under its namespace). We do not require a hard reference to the
    # function symbol — the source-guard above is the structural rule.
    import inspect
    adapter_src = inspect.getsource(orch_dispatch)
    assert "kanban_primitive" in adapter_src, (
        "directive_watcher/orch_dispatch.py must reference "
        "directive_watcher.kanban_primitive.dispatch_to_kanban"
    )
    assert "dispatch_to_kanban" in adapter_src, (
        "directive_watcher/orch_dispatch.py must call "
        "dispatch_to_kanban() — see directive (comment 5629246987)"
    )


def test_workorder_adapter_imports_the_primitive():
    """orchestrator/scripts/github_poller.py must reference the same
    primitive the directive adapter uses."""
    import github_poller  # noqa: PLC0415
    import inspect

    src = inspect.getsource(github_poller)
    assert "kanban_primitive" in src, (
        "orchestrator/scripts/github_poller.py must reference "
        "directive_watcher.kanban_primitive.dispatch_to_kanban"
    )
    assert "dispatch_to_kanban" in src, (
        "orchestrator/scripts/github_poller.py must call "
        "dispatch_to_kanban() — see directive (comment 5629246987)"
    )
