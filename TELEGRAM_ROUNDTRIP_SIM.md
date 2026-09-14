# Telegram Round-Trip Simulation Plan

> Lane 18 — physical Telegram round-trip cannot be performed from this
> CI host because (a) there is no live bot in this repo (the bot lives
> in the gateway layer, per TELEGRAM_CONTRACT.md §1), and (b) we are
> explicitly forbidden from mutating `BOT_TOKEN` or `GATEWAY_CONFIG`.
> What we CAN do is exercise the **exact same code path** a real
> Telegram webhook would trigger, end-to-end, and prove the gate
> behaves as the directive requires.

## The harness

The script `tests/test_telegram_roundtrip_sim.py` (in this repo's
`tests/`) constructs the JSON payload that the gateway would pipe
into `orchestrator/scripts/orch_inbound_wo.py` after receiving a
real Telegram `Message` from David's chat. It then runs
`orch_inbound_wo.dispatch(payload)` and asserts:

1. The payload is accepted for the narrow allow-list of actions.
2. The audit row is recorded into the shared `kanban_db`.
3. No per-chat state is created in `orch_inbound_wo` (the
   module-level state is verified unchanged before and after).
4. The Telegram `requester_chat_id` is consumed as a second factor
   only — it never becomes a session key.

## Run it

```bash
python -m pytest tests/test_telegram_roundtrip_sim.py -v --no-header
```

## Why this is honest

This is **not** a real Telegram round-trip — but it is exactly the
shape of one. The gateway already authenticates the requester and
identifies their `chat_id`; the payload-shaped JSON the gateway
forwards to `orch_inbound_wo` is stable and documented in the
module's CALL SHAPE comment. The script reproduces that shape and
proves the gate accepts it.

A real physical round-trip (an actual `https://api.telegram.org/...`
call from a live bot) belongs to the gateway layer. Lane 18's frozen
boundaries explicitly forbid re-implementing that here.

## What the script also proves (negative paths)

- A Telegram-shaped payload that asks for `action: "shell"` is
  rejected before any external call.
- A Telegram-shaped payload with `requester_chat_id` not in
  `ORCH_INBOUND_DAVID_CHAT_IDS` is rejected.
- A Telegram-shaped payload that names a product outside the routing
  table is rejected.

These three rejections are the same ones the production gate would
emit if a real Telegram message arrived with those values — and
they are exactly what the directive's "no special agent layer"
language is protecting against.
