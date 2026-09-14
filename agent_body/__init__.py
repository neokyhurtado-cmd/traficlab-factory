"""Agent Body — EVOLUTION-V1 closeout package.

Sibling of orchestrator/, control/, directive_watcher/. Hosts BODY-0..BODY-2
sidecar primitives used by Hermes workers to resume after a fresh session
without manual context copy/paste. Per #27 safety boundaries, this package
NEVER mutates: provider, model, API key, .env, config.yaml, gateway,
Telegram/Discord/WhatsApp, scheduler, runtime configuration, or any
~/.hermes/profile/* file.

The package is intentionally framework-free: pure stdlib + sqlite3 + the
existing PyYAML. Tests live in agent_body/tests/.
"""
