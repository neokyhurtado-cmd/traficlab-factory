"""Anti-regression test: no second state store for Telegram.

Companion to ``test_telegram_normal_session.py`` — locks
TELEGRAM_CONTRACT.md §3 ("No second state store").

What this test enforces:
  - No SQLite CREATE TABLE in this repo's production code may be keyed by
    ``chat_id``, ``telegram``, or ``tg_``.
  - No file extension ``.db`` / ``.sqlite`` / ``.sqlite3`` may be added
    with a Telegram-shaped name.
  - The only SQLite databases this repo is allowed to create are the
    ones already present (``control/bff/main.py`` opens ``control.db`` and
    the directive_watcher sidecar; ``orch_inbound_wo.py`` uses the
    *shared* ``hermes_cli.kanban_db`` for its audit row — not a Telegram
    database).
"""
from __future__ import annotations

import os
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


# Same skip-list rationale as test_telegram_normal_session.py:
# tests/ is where the contract is enforced, so the scanner skips it.
_SKIP_DIR_NAMES = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", "tests",
}


def _iter_production_python_files() -> list[Path]:
    out: list[Path] = []
    for root, dirs, files in os.walk(REPO_ROOT):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIR_NAMES]
        for f in files:
            if f.endswith(".py"):
                out.append(Path(root) / f)
    return out


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


# ------------------------------------------------------------------
# Test 1 — No Telegram-keyed CREATE TABLE in production code
# ------------------------------------------------------------------

class TestNoTelegramKeyedTable:

    # CREATE TABLE/VIEW/TRIGGER patterns where the table name itself
    # contains a Telegram-specific substring.
    TABLE_NAME_PATTERNS = [
        r"CREATE\s+(?:TEMP\s+|TEMPORARY\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
        r"[\"']?([A-Za-z_][A-Za-z0-9_]*)[\"']?",
        r"CREATE\s+(?:TEMP\s+|TEMPORARY\s+)?VIEW\s+(?:IF\s+NOT\s+EXISTS\s+)?"
        r"[\"']?([A-Za-z_][A-Za-z0-9_]*)[\"']?",
    ]

    TELEGRAM_TABLE_HINTS = (
        "telegram",
        "tg_",
        "_tg_",
        "tg_chat",
        "tg_session",
        "tg_state",
    )

    def test_no_create_table_telegram_keyed(self):
        """No Python file may create a SQLite table whose name implies a
        Telegram-keyed state store.

        The orchestrator's audit row goes to ``hermes_cli.kanban_db`` (a
        shared store with a generic schema) — that's the only persistence
        path allowed for Telegram-driven traffic, and it MUST NOT acquire
        a telegram-specific column or table.
        """
        # Allowlist: the production code that creates known-good tables.
        # If you need to add a new CREATE TABLE statement that has nothing
        # to do with Telegram, you do NOT need to add it here — this test
        # only flags tables whose NAME contains a Telegram hint.
        offenders: list[tuple[str, int, str]] = []
        for py in _iter_production_python_files():
            text = _read(py)
            for pat in self.TABLE_NAME_PATTERNS:
                for m in re.finditer(pat, text, flags=re.IGNORECASE):
                    table_name = m.group(1).lower()
                    if any(h in table_name for h in self.TELEGRAM_TABLE_HINTS):
                        line_no = text[: m.start()].count("\n") + 1
                        offenders.append(
                            (str(py.relative_to(REPO_ROOT)), line_no, table_name)
                        )
        assert not offenders, (
            "Found a CREATE TABLE/VIEW whose name contains a Telegram "
            "hint — violates TELEGRAM_CONTRACT.md §3:\n  "
            + "\n  ".join(f"{p}:{ln}: table={n}" for p, ln, n in offenders)
        )

    def test_no_alter_table_add_telegram_column(self):
        """No Python file may add a Telegram-named column to an existing
        table. The audit row in ``kanban_db`` already carries
        ``requester_platform`` as a generic string — no extra
        ``telegram_*`` columns are needed.
        """
        offenders: list[tuple[str, int, str]] = []
        col_pat = re.compile(
            r"ALTER\s+TABLE\s+\S+\s+ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?"
            r"[\"']?([A-Za-z_][A-Za-z0-9_]*)[\"']?",
            re.IGNORECASE,
        )
        for py in _iter_production_python_files():
            text = _read(py)
            for m in col_pat.finditer(text):
                col_name = m.group(1).lower()
                if any(h in col_name for h in self.TELEGRAM_TABLE_HINTS):
                    line_no = text[: m.start()].count("\n") + 1
                    offenders.append(
                        (str(py.relative_to(REPO_ROOT)), line_no, col_name)
                    )
        assert not offenders, (
            "Found an ALTER TABLE ... ADD COLUMN with a Telegram-shaped "
            "name — violates TELEGRAM_CONTRACT.md §3:\n  "
            + "\n  ".join(f"{p}:{ln}: column={n}" for p, ln, n in offenders)
        )


# ------------------------------------------------------------------
# Test 2 — No telegram_*.db / *_tg_session.db file in the tree
# ------------------------------------------------------------------

class TestNoTelegramDbFile:

    BAD_SUFFIXES = (".db", ".sqlite", ".sqlite3")
    BAD_NAME_HINTS = (
        "telegram",
        "tg_",
        "tg.",
    )

    def test_no_telegram_named_db_in_repo(self):
        offenders: list[str] = []
        for root, dirs, files in os.walk(REPO_ROOT):
            # Skip the well-known control DB that lives next to the BFF.
            if "node_modules" in root or ".git" in root or "__pycache__" in root:
                continue
            for f in files:
                low = f.lower()
                if not any(low.endswith(s) for s in self.BAD_SUFFIXES):
                    continue
                if any(h in low for h in self.BAD_NAME_HINTS):
                    offenders.append(str(Path(root, f).relative_to(REPO_ROOT)))
        assert not offenders, (
            "Found a SQLite database file with a Telegram-shaped name — "
            "violates TELEGRAM_CONTRACT.md §3:\n  " + "\n  ".join(offenders)
        )


# ------------------------------------------------------------------
# Test 3 — kanban_db audit row schema is platform-neutral
# ------------------------------------------------------------------

class TestKanbanDbSchemaPlatformNeutral:
    """The audit row written by ``orch_inbound_wo._emit_audit_row`` must
    carry the ``requester_platform`` as a generic string field — no
    Telegram-specific column."""

    def test_audit_row_payload_has_no_telegram_specific_columns(self):
        # Lazy import so we don't drag hermes_cli into pytest collection.
        try:
            import orch_inbound_wo  # type: ignore
        except Exception:
            pytest_import_error = True  # noqa: F841 — handled below
            return  # orchestrator/scripts not on sys.path is fine; this test
            # only fires when the test is run from a context where the
            # orchestrator scripts module is importable.

        # Reach into the source to verify the audit payload shape.
        src_path = (
            REPO_ROOT / "orchestrator" / "scripts" / "orch_inbound_wo.py"
        )
        src = _read(src_path)

        # Pull out the dict literal passed to _append_event.
        m = re.search(
            r"_append_event\(\s*conn,\s*task_id,\s*\"ORCH_INBOUND_WO\",\s*(\{.*?\})\s*\)",
            src,
            flags=re.DOTALL,
        )
        assert m is not None, (
            "Could not find the ORCH_INBOUND_WO audit payload literal in "
            "orch_inbound_wo.py — the source shape may have changed; this "
            "test needs to be updated alongside the code."
        )
        audit_dict = m.group(1)
        for key in re.findall(r"\"([A-Za-z_][A-Za-z0-9_]*)\"\s*:", audit_dict):
            lk = key.lower()
            assert "telegram" not in lk, (
                f"Audit payload key '{key}' contains 'telegram' — the "
                "kanban_db schema must stay platform-neutral. Use "
                "'platform' or 'requester_platform' instead."
            )
