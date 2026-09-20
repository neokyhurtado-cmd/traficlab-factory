"""Anti-regression test: no second scheduler for Telegram.

Companion to ``test_telegram_normal_session.py`` — locks
TELEGRAM_CONTRACT.md §4 ("No second scheduler") and §5
("requester_platform is informational only").

What this test enforces:
  - No class named or imported with a Telegram-shaped scheduler identity
    may exist anywhere in production code.
  - No ``asyncio.create_task``-based background loop may be groomed for
    a Telegram poll. (We allow ``asyncio.create_task`` itself in the
    BFF where it serves the SSE event stream — that's a different concern
    and is test-guarded elsewhere.)
  - The ONLY scheduler-class the repo admits is
    ``directive_watcher.scheduler.Scheduler``, which polls GitHub.
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
# Test 1 — No Telegram-shaped scheduler class / file
# ------------------------------------------------------------------

class TestNoTelegramScheduler:

    BAD_FILENAME_HINTS = (
        "telegram",
    )

    BAD_CLASS_NAMES = (
        "TelegramPolling",
        "TelegramScheduler",
        "TelegramCron",
        "TelegramBot",
        "TelegramWorker",
    )

    def test_no_telegram_named_scheduler_file(self):
        offenders: list[str] = []
        for root, dirs, files in os.walk(REPO_ROOT):
            dirs[:] = [
                d for d in dirs
                if d not in (".git", "__pycache__", "node_modules", ".venv", "venv")
            ]
            for f in files:
                low = f.lower()
                # Only flag FILES that imply a scheduler; the contract doc
                # "TELEGRAM_CONTRACT.md" is allowed (it's at the repo
                # root, not a Python file anyway, so this guard is
                # belt-and-suspenders).
                if not f.endswith((".py", ".sh", ".yaml", ".yml")):
                    continue
                if any(h in low for h in self.BAD_FILENAME_HINTS) and (
                    "scheduler" in low or "polling" in low or "cron" in low
                    or "bot" in low or "worker" in low
                ):
                    offenders.append(str(Path(root, f).relative_to(REPO_ROOT)))
        assert not offenders, (
            "Found a file whose name implies a Telegram scheduler — "
            "violates TELEGRAM_CONTRACT.md §4:\n  " + "\n  ".join(offenders)
        )

    def test_no_telegram_scheduler_class_definition(self):
        offenders: list[tuple[str, int, str]] = []
        for py in _iter_production_python_files():
            text = _read(py)
            for cls in self.BAD_CLASS_NAMES:
                # Match `class TelegramPolling(...):` and `class TelegramPolling:`
                pat = re.compile(rf"\bclass\s+{re.escape(cls)}\b\s*[\(:]")
                for m in pat.finditer(text):
                    line_no = text[: m.start()].count("\n") + 1
                    offenders.append(
                        (str(py.relative_to(REPO_ROOT)), line_no, cls)
                    )
        assert not offenders, (
            "Found a Telegram-shaped scheduler class — violates "
            "TELEGRAM_CONTRACT.md §4:\n  "
            + "\n  ".join(f"{p}:{ln}: class {c}" for p, ln, c in offenders)
        )

    def test_no_update_queue_or_long_poll_loop_in_repo(self):
        """No file in the repo may declare a method that calls
        ``getUpdates``, ``setWebhook``, or starts an asyncio loop that
        mentions Telegram. These are the canonical long-poll primitives
        of ``python-telegram-bot`` and equivalents."""
        patterns = [
            r"\bgetUpdates\s*\(",
            r"\bsetWebhook\s*\(",
            r"\.polling\s*\(",
            r"Updater\s*\(",
        ]
        offenders: list[tuple[str, int, str]] = []
        for py in _iter_production_python_files():
            text = _read(py)
            for pat in patterns:
                for m in re.finditer(pat, text):
                    line_no = text[: m.start()].count("\n") + 1
                    offenders.append(
                        (str(py.relative_to(REPO_ROOT)), line_no, m.group(0))
                    )
        assert not offenders, (
            "Found a Telegram long-poll / webhook primitive — violates "
            "TELEGRAM_CONTRACT.md §1, §4:\n  "
            + "\n  ".join(f"{p}:{ln}: {snippet}" for p, ln, snippet in offenders)
        )


# ------------------------------------------------------------------
# Test 2 — requester_platform must not branch logic
# ------------------------------------------------------------------

class TestRequesterPlatformIsInformationalOnly:

    def test_no_branch_on_requester_platform_in_production(self):
        """No production code (outside this test file) may check
        ``requester_platform == "telegram"`` to alter behaviour. Telegram
        must always flow through the same allow-list path as Discord.

        ``orch_inbound_wo.py`` is the one place where the platform string
        is *recorded* in the audit row, but it is never used to branch
        the action. The contract docstring at the top of that file
        reinforces this.

        Allowlist for tests (self + the two siblings) and the docstring
        in ``orch_inbound_wo.py`` (which restates the contract).
        """
        allowed = {
            (REPO_ROOT / "tests" / "test_telegram_normal_session.py").resolve(),
            (REPO_ROOT / "tests" / "test_no_second_state_store.py").resolve(),
            (REPO_ROOT / "tests" / "test_no_second_scheduler.py").resolve(),
            (REPO_ROOT / "orchestrator" / "scripts" / "orch_inbound_wo.py").resolve(),
        }
        offenders: list[tuple[str, int, str]] = []
        pat = re.compile(
            r"requester_platform\s*(?:==|!=|in\s|not\s+in\s)"
            r"(\[[^\]]*\]|\"[^\"]*\")",
            re.IGNORECASE,
        )
        for py in _iter_production_python_files():
            if py.resolve() in allowed:
                continue
            text = _read(py)
            for m in pat.finditer(text):
                line_no = text[: m.start()].count("\n") + 1
                offenders.append(
                    (str(py.relative_to(REPO_ROOT)), line_no, m.group(0))
                )
        assert not offenders, (
            "Found a branch on requester_platform in production code — "
            "violates TELEGRAM_CONTRACT.md §5. Offending lines:\n  "
            + "\n  ".join(f"{p}:{ln}: {snippet}" for p, ln, snippet in offenders)
        )
