#!/usr/bin/env bash
# tests/run-all.sh — single-command M6 entry point.
# Runs syntax, secret-scan, redact, idempotency, ownership, stale-event.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

fail() { echo "M6 FAIL ($1)"; exit 1; }

echo "[1/6] syntax-check..."
node syntax-check.js > /tmp/m6-syntax.log 2>&1 || fail "syntax"

echo "[2/6] secret-scan..."
node secret-scan.js > /tmp/m6-secret.log 2>&1 || fail "secret-scan"

echo "[3/6] redact..."
node redact.test.js > /tmp/m6-redact.log 2>&1 || fail "redact"

echo "[4/6] idempotency..."
node idempotency.test.js > /tmp/m6-idem.log 2>&1 || fail "idempotency"

echo "[5/6] ownership-guard..."
node ownership-guard.test.js > /tmp/m6-owner.log 2>&1 || fail "ownership-guard"

echo "[6/6] stale-event..."
node stale-event.test.js > /tmp/m6-stale.log 2>&1 || fail "stale-event"

echo
echo "M6 OK — 6 modules, 30+ checks, all green."
exit 0
