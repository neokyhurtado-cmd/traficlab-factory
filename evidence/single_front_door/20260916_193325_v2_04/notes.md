# Natural-language canary run 20260916_193325_v2_04

Goal: 'Sigue IA-VISION y llévame #111 hasta revisión'

Goal mode: ISSUE_ANCHORED

This is a REAUDIT_FIX v2 canary run for SINGLE-FRONT-DOOR-01-CLOSEOUT-20260916-02.
It exercises the new free-form primary parsing and the corrected
`check_already_done` semantics (latest authoritative lifecycle state wins;
`ready-for-audit` is transitional; ASTRA CHANGES_REQUIRED re-opens).

The real `discover_runtime()` was patched to a snapshot of the host state
observed at run start (gateway Ready PID 35804, vault BrainPool, poller cron
44c091e79145 last_status ok, Orca runtime 0d039b76-... PID 30576).
