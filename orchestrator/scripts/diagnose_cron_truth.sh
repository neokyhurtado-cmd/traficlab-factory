#!/usr/bin/env bash
# diagnose_cron_truth.sh — Prove `hermes cron list` matches cron/jobs.json.
#
# Locked in WO-ORCH-AUTODISPATCH-02 step 7. Run this after any cron
# migration or package upgrade to confirm the CLI adapter is reading the
# same store the scheduler is ticking. Exits 0 when the two agree on
# (id, name, schedule); non-zero when they disagree.

set -euo pipefail

PROFILE_HOME="${HERMES_HOME:-$HOME/.hermes/profiles/orchestrator}"
JOBS_JSON="$PROFILE_HOME/cron/jobs.json"

if [[ ! -f "$JOBS_JSON" ]]; then
    echo "FAIL: jobs.json not found at $JOBS_JSON"
    exit 1
fi

# `hermes cron list` is the CLI-side truth. We parse the names from the
# active jobs (line beginning with whitespace + 8-char hex id) — one per job.
# Match 12-char hex IDs (the cron job-id format) to avoid colliding with
# the 8-char execution-id hex strings that appear elsewhere in the output.
CLI_OUTPUT="$(hermes -p orchestrator cron list)"
# Replace CRs from Windows output with newlines first, then strip
# surrounding whitespace per-line so each ID lives on its own line.
CLI_IDS="$(echo "$CLI_OUTPUT" | tr '\r' '\n' | grep -oE '^\s+[0-9a-f]{12}\b' | awk '{print $1}' | sort)"

# jobs.json is the file-side truth.
# Use Python with the path passed via argv. We avoid heredoc for
# stdin so we don't fight with bash escaping of `\r` in `-c` literals.
# On Windows, Python's print() adds \r\n; pipe through tr to normalise.
read -r -d '' JSON_PY <<'PYEOF' || true
import json, sys
with open(sys.argv[1], 'r', encoding='utf-8') as f:
    d = json.load(f)
for j in d.get('jobs', []):
    print(j['id'].strip().replace(chr(13), ''))
PYEOF
JSON_IDS="$(python -c "$JSON_PY" "$JOBS_JSON" | tr -d '\r' | sort)"

if [[ -z "$CLI_IDS" ]]; then
    echo "FAIL: no jobs reported by 'hermes cron list'"
    exit 1
fi

# Sort CLI_IDS to match the JSON sort order for diff.
SORTED_CLI="$(echo "$CLI_IDS" | sort)"

if [[ "$SORTED_CLI" != "$JSON_IDS" ]]; then
    echo "FAIL: cron list and jobs.json disagree"
    echo "--- cron list ids ---"
    echo "$SORTED_CLI"
    echo "--- jobs.json ids ---"
    echo "$JSON_IDS"
    exit 1
fi

echo "PASS: $(echo "$CLI_IDS" | wc -l | tr -d ' \t') job(s) match between 'hermes cron list' and $JOBS_JSON"
