#!/usr/bin/env python3
"""GitHub Directive Watcher — Hermes 2.0 / Product Foundry Event Loop.

See ``directive_watcher/README.md`` for the full contract and ``traficlab-factory#18``
for the originating Work Order.

Phase 1: outbound polling every 5 minutes against an explicit repo/author
allowlist. No public listener, no inbound port, no webhook exposure.
"""
