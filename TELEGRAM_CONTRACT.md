# Telegram Contract — neokyhurtado-cmd/traficlab-factory

> **Binding for:** every PR that touches anything labelled "telegram" in this
> repository, including future lanes that may add Telegram-aware code.
> **Authority:** Issue #20 — TELEGRAM_NORMAL_HERMES_SESSION; Directive
> `astra-telegram-normal-hermes-session-20260911-01` (binding comment
> 5643285255).

## 1. Core principle

**Telegram is a source identity, not an agent.**

In this repository, "Telegram" appears only as a string in one place —
`orchestrator/scripts/orch_inbound_wo.py` — where it is a value of the
`requester_platform` field, exactly like `discord` is. There is no Telegram
adapter, no Telegram scheduler, no Telegram session store, and no Telegram
database in this repo, and **this contract forbids adding one.**

## 2. The six rules

1. **No bot in this repo.** The Telegram bot itself — if and when one exists
   — lives in the Hermes Agent / gateway layer, NOT here. This repo never
   holds a `BOT_TOKEN`, never imports `python-telegram-bot` / `telebot` /
   `aiogram` / `pyrogram`, and never opens a long-running
   `update_queue` / `polling` / `webhook` connection to Telegram.

2. **No per-chat session state.** Telegram-driven requests are validated by
   the stateless gate in `orchestrator/scripts/orch_inbound_wo.py`. That
   gate holds no `dict[chat_id, …]` in memory; every `dispatch(payload)`
   call is a pure function of its input + the routing table + the env-var
   allow-list.

3. **No second state store.** The only state Telegram requests may persist
   is the canonical `ORCH_INBOUND_WO` audit row in
   `hermes_cli.kanban_db`, shared with GitHub-driven directives. No
   Telegram-specific SQLite file, no `telegram_*.db`, no `telegram_*.json`
   sidecar may be added to this repo.

4. **No second scheduler.** The only long-running scheduler in this repo is
   `directive_watcher/scheduler.py`, which polls GitHub every 5 minutes.
   No `TelegramPolling*`, `telegram_scheduler`, `telegram_cron`, or
   out-of-band polling loop may be added.

5. **`requester_platform` is informational only.** The validator must
   never branch logic on whether the source is telegram vs. discord vs.
   anything else. The narrow allow-list of actions
   `{create_wo, update_wo, add_label, remove_label, transition_status}`
   is identical across all requester platforms.

6. **/new, /stop, /status are Hermes session semantics.** They are not
   Telegram-only logic. They live in the canonical session layer, not in
   any `telegram_*.py` module in this repo. The directive_watcher's
   `directive_id → session_id` registry is the canonical session store
   for work-order execution, not for chat sessions.

## 3. Why this matters

The threat this contract defends against is a "shadow orchestrator": a
parallel agent layer that ends up duplicating the routing table, the
session store, the scheduler, and the audit log — but only for one
platform. That duplicates work, doubles the audit surface, and creates a
class of bugs where a Telegram-driven action disagrees with a
Discord-driven action on the same underlying state.

## 4. Anti-regression tests

This contract is enforced by three pytest modules living next to the
code they protect:

- `tests/test_telegram_normal_session.py` — locks §1, §2, §6.
- `tests/test_no_second_state_store.py` — locks §3.
- `tests/test_no_second_scheduler.py` — locks §4 and §5.

Any PR that violates these tests must be rejected at code review.

## 5. What this contract does NOT cover

- The Telegram bot itself, if one is added, lives in another repo or
  another layer. Lane 18 deliberately stays inside this repo only.
- The official `python-telegram-bot` SDK or any other Telegram client
  library: not used here, not needed here.
- The bot token: lives in the gateway's secret store, never in this repo.

---

If a future contributor needs to violate any of §1–§6, they must open a
new lane and earn a new directive from Astra first. The default answer
is "no".
