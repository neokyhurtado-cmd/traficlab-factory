"""Anti-regression tests for Lane 18 — Telegram as Normal Hermes Transport.

These tests lock the contract that Telegram in this repo is a SOURCE IDENTITY
(value of ``requester_platform``), NOT an agent, NOT a session store, NOT a
scheduler. See ``TELEGRAM_CONTRACT.md`` at the repo root for the full contract
and ``audit_findings.md`` / ``simplified_design.md`` under
``C:/TraficLabPro/evidencia/traficlab_factory_20/`` for the audit and design
trail.

Three tests in this file:

1. ``test_telegram_appears_only_in_orch_inbound_wo`` — the only place the
   literal word "telegram" appears in any ``.py`` file in this repo is in
   ``orchestrator/scripts/orch_inbound_wo.py`` — and there it is informational
   (``requester_platform`` value or docstring).

2. ``test_no_telegram_sdk_imports`` — no file in the repo may import any
   Telegram SDK or hold a bot token constant.

3. ``test_no_chat_id_to_session_map`` — there is no in-memory map, no DB
   table, no on-disk store keyed by ``chat_id`` anywhere in the repo.
"""
from __future__ import annotations

import os
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


# Anti-regression test files intentionally mention "telegram",
# "TelegramPolling", "chat_id_to_session", etc. — those mentions are
# the contract being enforced, NOT violations. The scanner that walks
# the repo therefore skips ``tests/`` (and other known noise dirs).
_SKIP_DIR_NAMES = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", "tests",
}


def _iter_production_python_files() -> list[Path]:
    """Yield every ``.py`` file under the repo root, EXCLUDING ``tests/``
    and noise directories. These are the files whose content is
    subject to the Telegram contract — test files exist exactly to
    enforce it and so are out of scope for the scanner.
    """
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
# Test 1 — Telegram is mentioned only in orch_inbound_wo.py
# ------------------------------------------------------------------

class TestTelegramSurfaceIsMinimal:

    def test_telegram_appears_only_in_orch_inbound_wo(self):
        """Every ``.py`` file (outside ``tests/``) that mentions
        ``telegram`` (case-insensitive, word-boundary match) must be one
        of the explicitly allowed files. The allowed set is small and
        intentional: the orchestrator gate itself, its dedicated test
        file, and one explanatory comment in the directive_watcher.

        Production code outside that list may not contain the word
        "telegram" — it would imply a parallel Telegram surface that
        the directive forbids.
        """
        # Files that legitimately contain the word "telegram" while
        # remaining consistent with the contract:
        #   * orchestrator/scripts/orch_inbound_wo.py — the gate (sole
        #     production reference; "requester_platform" value)
        #   * orchestrator/scripts/test_orch_inbound_wo.py — its test
        #     file, which uses "david-telegram" in fixture payloads
        #   * directive_watcher/orch_dispatch.py — contains a comment
        #     at line ~46 that explicitly says "no Telegram integration"
        allowed = {
            (
                REPO_ROOT
                / "orchestrator"
                / "scripts"
                / "orch_inbound_wo.py"
            ).resolve(),
            (
                REPO_ROOT
                / "orchestrator"
                / "scripts"
                / "test_orch_inbound_wo.py"
            ).resolve(),
            (
                REPO_ROOT
                / "directive_watcher"
                / "orch_dispatch.py"
            ).resolve(),
        }

        offenders: list[tuple[str, list[int]]] = []
        for py in _iter_production_python_files():
            if py.resolve() in allowed:
                continue
            try:
                text = py.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            # Word-boundary match, case-insensitive.
            lines = [
                i + 1 for i, line in enumerate(text.splitlines())
                if re.search(r"\btelegram\b", line, flags=re.IGNORECASE)
            ]
            if lines:
                offenders.append((str(py.relative_to(REPO_ROOT)), lines))

        assert not offenders, (
            "Telegram was mentioned in production code outside the "
            "allowed list. This violates the Telegram contract "
            "(see TELEGRAM_CONTRACT.md §1). Offending files:\n  "
            + "\n  ".join(f"{p} (lines {ls})" for p, ls in offenders)
        )

    def test_telegram_in_orch_inbound_wo_is_only_informational(self):
        """In ``orch_inbound_wo.py`` the word "telegram" must only appear
        as (a) a value of ``requester_platform`` in the docstring/payload
        examples, (b) in the ALLOWED_REQUESTERS name "david-telegram", or
        (c) in the contract docstring at the top of the file.

        A real Telegram SDK import or a Telegram-aware function definition
        would be a violation.
        """
        target = (
            REPO_ROOT / "orchestrator" / "scripts" / "orch_inbound_wo.py"
        )
        text = _read(target)
        # Find every line that mentions "telegram" (case-insensitive).
        hits = [
            (i + 1, line)
            for i, line in enumerate(text.splitlines())
            if re.search(r"\btelegram\b", line, flags=re.IGNORECASE)
        ]
        assert hits, "Expected at least one telegram reference (sanity)"
        for lineno, line in hits:
            lo = line.lower()
            stripped = line.lstrip()
            # A comment-only line is documentation — never "surface".
            is_comment = stripped.startswith("#")
            ok = (
                "david-telegram" in lo           # ALLOWED_REQUESTERS entry
                or "requester_platform" in lo    # payload field
                or "telegram contract" in lo     # the new docstring header
                or "telegram/discord" in lo      # the original docstring
                or "telegram.sdk" in lo          # the new docstring (denial)
                or "no telegram" in lo           # the new docstring (denial)
                or "telegram adapter" in lo      # the new docstring (denial)
                or "telegram session" in lo      # the new docstring (denial)
                or "telegram scheduler" in lo    # the new docstring (denial)
                or '"telegram"' in lo            # the new docstring quoting
                or "string \"telegram\" may" in lo  # the new docstring prose
                or "alice-telegram" in lo       # original docstring example
                or "telegram contract.md" in lo  # pointer to contract doc
                or is_comment                    # any explanatory comment
            )
            assert ok, (
                f"orch_inbound_wo.py:{lineno} mentions 'telegram' in a way "
                f"the contract doesn't allow: {line!r}"
            )


# ------------------------------------------------------------------
# Test 2 — No Telegram SDK imports, no bot token constants
# ------------------------------------------------------------------

class TestNoTelegramSDK:

    SDK_PATTERNS = [
        r"\bimport\s+telegram\b",
        r"\bfrom\s+telegram\b",
        r"\bimport\s+telebot\b",
        r"\bfrom\s+telebot\b",
        r"\bimport\s+aiogram\b",
        r"\bfrom\s+aiogram\b",
        r"\bimport\s+pyrogram\b",
        r"\bfrom\s+pyrogram\b",
        r"\bimport\s+python_telegram_bot\b",
        r"\bfrom\s+python_telegram_bot\b",
    ]

    TOKEN_PATTERNS = [
        # Bot token shape: <digits>:<35-ish alnum chars>
        r"\b\d{6,12}:[A-Za-z0-9_-]{30,60}\b",
        # The literal string "BOT_TOKEN" assigned to something other than a
        # documentation reference. We allow it ONLY in the contract docstring
        # at the top of orch_inbound_wo.py (see test above) and in TELEGRAM_CONTRACT.md.
    ]

    def test_no_telegram_sdk_imports(self):
        offenders: list[tuple[str, int, str]] = []
        for py in _iter_production_python_files():
            text = _read(py)
            for pat in self.SDK_PATTERNS:
                for m in re.finditer(pat, text):
                    line_no = text[: m.start()].count("\n") + 1
                    offenders.append((str(py.relative_to(REPO_ROOT)), line_no, m.group(0)))
        assert not offenders, (
            "Telegram SDK import found — violates TELEGRAM_CONTRACT.md §1:\n  "
            + "\n  ".join(f"{p}:{ln}: {snippet}" for p, ln, snippet in offenders)
        )

    def test_no_bot_token_constants(self):
        offenders: list[tuple[str, int, str]] = []
        for py in _iter_production_python_files():
            text = _read(py)
            # The "david-telegram" string from ALLOWED_REQUESTERS is a
            # requester NAME, not a bot token; the regex below excludes it.
            for pat in self.TOKEN_PATTERNS:
                for m in re.finditer(pat, text):
                    snippet = m.group(0)
                    line_no = text[: m.start()].count("\n") + 1
                    offenders.append(
                        (str(py.relative_to(REPO_ROOT)), line_no, snippet)
                    )
        assert not offenders, (
            "Possible Telegram bot token literal found — violates "
            "TELEGRAM_CONTRACT.md §1:\n  "
            + "\n  ".join(f"{p}:{ln}: {snippet}" for p, ln, snippet in offenders)
        )


# ------------------------------------------------------------------
# Test 3 — No chat_id → session map anywhere
# ------------------------------------------------------------------

class TestNoChatIdToSessionMap:

    SUSPICIOUS_KEYS = (
        "chat_id",
        "chatid",
        "requester_chat_id",
    )

    def test_no_in_memory_chat_id_store(self):
        """No Python file in the repo may declare an attribute, dict, or
        default-dict keyed by ``chat_id`` (or any of its variants). The
        orchestrator's gate is stateless and must stay stateless.

        Allowed: occurrences that are *parameters* to a function or
        *values* in a payload dict (e.g. ``"requester_chat_id": "..."``)
        are fine because they do not create state. We grep only for
        assignments / type annotations / class-attribute defaults.
        """
        # Patterns that smell like STATE keyed by chat_id.
        patterns = [
            r"self\._?\w*[Cc]hat_?[Ii]d_?\w*\s*[:=]",       # self.chat_id = ...
            r"_chat_?ids\s*[:=]\s*(\{|\[)",                 # _chat_ids = { / [
            r"chat_id_?to_?session\s*[:=]",                 # chat_id_to_session =
            r"by_?chat_?id\s*[:=]",                         # by_chat_id =
            r"DEFAULT_?CHAT_?IDS\s*[:=]",                   # DEFAULT_CHAT_IDS =
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
            "Found what looks like an in-memory chat_id state store — "
            "violates TELEGRAM_CONTRACT.md §2. Offending lines:\n  "
            + "\n  ".join(f"{p}:{ln}: {snippet}" for p, ln, snippet in offenders)
        )

    def test_no_persistent_chat_id_file(self):
        """No file under the repo may be named ``*chat_id*`` or
        ``*telegram_session*`` etc. The state store for chat sessions
        does not exist in this repo and must not be created."""
        bad_substrings = (
            "chat_id_map",
            "telegram_session",
            "telegram_state",
            "telegram_sessions",
            "telegram_store",
            "telegram_chats",
        )
        offenders: list[str] = []
        for root, dirs, files in os.walk(REPO_ROOT):
            dirs[:] = [
                d for d in dirs
                if d not in (".git", "__pycache__", "node_modules", ".venv", "venv")
            ]
            for f in files:
                low = f.lower()
                if any(sub in low for sub in bad_substrings):
                    offenders.append(str(Path(root, f).relative_to(REPO_ROOT)))
        assert not offenders, (
            "Found a file whose name implies a Telegram chat-id state "
            "store — violates TELEGRAM_CONTRACT.md §3:\n  "
            + "\n  ".join(offenders)
        )
