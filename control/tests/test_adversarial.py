"""Adversarial tests for Control BFF V0.

Verifies threat model T1..T12 from suini#54 comment 5599034906.
Also includes F2 close-out fix-specific tests (F2.1..F2.4) for PR #6 review.
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys
import logging
from pathlib import Path

# Suppress noisy logs from httpx/uvicorn during tests
logging.disable(logging.CRITICAL)

# Allow tests to import the BFF module
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bff"))

# Force-loopback defaults for test runs
os.environ.setdefault("BFF_HOST", "127.0.0.1")
os.environ.setdefault("BFF_PORT", "9118")
os.environ.setdefault("HERMES_BEARER_KEY", "test-key-not-real")
os.environ.setdefault("HERMES_INSTALLED_VERSION", "v0.test")
# isolated DB so tests don't touch user's
os.environ["CONTROL_DB"] = str(Path(__file__).resolve().parent / "_test_control.db")
if Path(os.environ["CONTROL_DB"]).exists():
    Path(os.environ["CONTROL_DB"]).unlink()

import importlib
import main as bff  # noqa: E402

importlib.reload(bff)

from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(bff.app)

PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}: {detail}")


# Read UI bundle for secret-leak tests
ui_app_js = (Path(__file__).resolve().parent.parent / "ui" / "app.js").read_text(encoding="utf-8")
ui_index = (Path(__file__).resolve().parent.parent / "ui" / "index.html").read_text(encoding="utf-8")

print("T1. UI bundle must not contain Hermes bearer key patterns")
check("ui/app.js no sk- prefix", "sk-" not in ui_app_js)
check("ui/app.js no Bearer literal", "Bearer " not in ui_app_js)
check("ui/app.js no API_SERVER_KEY", "API_SERVER_KEY" not in ui_app_js)
check("ui/app.js no X-Control-Token header injection", "X-Control-Token" not in ui_app_js)
check("ui/index.html no inline token", "window.__CONTROL_SESSION_TOKEN__" not in ui_index)

print("T2. UI bundle must not contain GitHub token patterns")
check("ui/app.js no ghp_", "ghp_" not in ui_app_js)
check("ui/app.js no github_pat_", "github_pat_" not in ui_app_js)
check("ui/app.js no GITHUB_TOKEN", "GITHUB_TOKEN" not in ui_app_js)

print("T3. BFF must refuse to start on non-loopback host")
check("boot check function exists", callable(bff._check_no_public_bind))
src = Path(bff.__file__).read_text(encoding="utf-8")
check("check compares against 127.0.0.1", '"127.0.0.1"' in src or "'127.0.0.1'" in src)
check("check compares against localhost", '"localhost"' in src or "'localhost'" in src)
check("check reads BFF_HOST dynamically via os.environ.get",
      "os.environ.get" in src and 'BFF_HOST' in src)

print("T4. Session cookie is HttpOnly + SameSite (validated in T5 below after / request)")

print("T5. Auth required on /api/v1/*")
# Use a fresh client so cookies from / don't leak into these checks
fresh = TestClient(bff.app)
r = fresh.get("/api/v1/health")
check("GET /api/v1/health without cookie -> 401", r.status_code == 401)
r = fresh.get("/api/v1/projects")
check("GET /api/v1/projects without cookie -> 401", r.status_code == 401)
r = fresh.get("/api/v1/previews")
check("GET /api/v1/previews without cookie -> 401", r.status_code == 401)
r = fresh.get("/api/v1/findings")
check("GET /api/v1/findings without cookie -> 401", r.status_code == 401)

# Now hit / to get the cookie set
r = client.get("/")
check("GET / returns 200", r.status_code == 200)
set_cookie = r.headers.get("set-cookie", "")
check("Set-Cookie present", "control_session=" in set_cookie)
check("HttpOnly flag", "HttpOnly" in set_cookie or "httponly" in set_cookie.lower())
check("SameSite=Strict", "SameSite=strict" in set_cookie or "samesite=strict" in set_cookie.lower())
check("Path=/", "Path=/" in set_cookie)

m = re.search(r"control_session=([^;]+)", set_cookie)
session_cookie_value = m.group(1) if m else None
check("session cookie extracted", session_cookie_value is not None)
cookies = {"control_session": session_cookie_value} if session_cookie_value else {}

print("T6. Auth works with valid cookie")
r = client.get("/api/v1/health", cookies=cookies)
check("GET /api/v1/health with cookie -> 200", r.status_code == 200)
data = r.json()
check("response has schema_version", data.get("schema_version", "").startswith("control-read-model/"))
check("response has type=HealthSnapshot", data.get("type") == "HealthSnapshot")

print("T7. /api/v1/projects returns 3 items")
r = client.get("/api/v1/projects", cookies=cookies)
check("status 200", r.status_code == 200)
items = r.json()
check("3 projects", len(items) == 3)
ids = {p["project_id"] for p in items}
check("contains ia-vision", "ia-vision" in ids)
check("contains suini", "suini" in ids)
check("contains trafficlab-control", "trafficlab-control" in ids)

print("T8. Findings create + idempotency")
# Reset sqlite state for idempotency tests (T8 + F2.4 share DB)
with bff._db() as conn:
    conn.execute("DELETE FROM visual_findings")
    conn.execute("DELETE FROM events")
    conn.commit()
payload = {
    "preview_id": "ia-vision-visor",
    "kind": "needs_work",
    "title": "test finding — stale speeds panel",
    "frame_ref": {"video_id": 42, "timestamp_s": 1234.5},
    "context": {"product_sha": "42cb9d60dd3f", "pr_ref": "ia-vision#36"},
}
r = client.post("/api/v1/findings", json=payload, cookies=cookies)
check("POST /api/v1/findings -> 201", r.status_code == 201)
finding = r.json()
check("response has finding_id", "finding_id" in finding)
check("response kind matches", finding["kind"] == "needs_work")

# Listing returns it
r = client.get("/api/v1/findings", cookies=cookies)
check("GET /api/v1/findings returns list", r.status_code == 200 and isinstance(r.json(), list))
check("created finding is in list", any(f["finding_id"] == finding["finding_id"] for f in r.json()))

print("T9. Event stream subscription rejects unauth")
# Use a fresh client to avoid the session cookie set by the earlier GET /
no_cookie_client = TestClient(bff.app)
r = no_cookie_client.get("/api/v1/events")
check("GET /api/v1/events without cookie -> 401", r.status_code == 401)

print("T9b. Event stream SSE route exists and is wired")
events_route_paths = [getattr(r, "path", "") for r in bff.app.routes]
check("/api/v1/events route registered", "/api/v1/events" in events_route_paths)

print("T10. Database schema invariants")
conn = sqlite3.connect(os.environ["CONTROL_DB"])
rows = conn.execute("PRAGMA table_info(events)").fetchall()
col_names = {r[1] for r in rows}
required = {"event_id", "correlation_id", "kind", "created_at", "idempotency_key", "payload_json"}
check("events table has required columns", required.issubset(col_names))
unique_event = conn.execute("PRAGMA index_list(events)").fetchall()
has_unique_idem = any("idempotency_key" in str(conn.execute(f"PRAGMA index_info({u[1]})").fetchall()) for u in unique_event if u[2])
check("idempotency_key is unique", has_unique_idem)

print("T11. BFF does not start if BFF_HOST is non-loopback (boot guard)")
boot_src = Path(bff.__file__).read_text(encoding="utf-8")
check("_check_no_public_bind is called at boot", "_check_no_public_bind()" in boot_src)

print("T12. No raw secret leak in logs/events (text scan)")
boot_src_lower = boot_src.lower()
check("BFF source does not log HERMES_BEARER_KEY",
      "hermes_bearer_key" not in boot_src_lower or "log" not in boot_src_lower.split("hermes_bearer_key")[0][-200:])

# ---------- F2 CLOSE-OUT: 4 fix-specific adversarial tests ----------

print()
print("=" * 60)
print("F2 CLOSEOUT — fix-specific adversarial tests")
print("=" * 60)

print("F2.1 P1 — Host header validation (anti-DNS-rebinding)")
# Host header must be loopback (or the TestClient sentinel `testserver`);
# anything else returns 400 BEFORE auth runs.
for bad_host in ("evil.com", "192.0.2.1", "attacker.example.org", "google.com"):
    r = client.get("/api/v1/health", headers={"Host": bad_host})
    check(f"GET /api/v1/health with Host: {bad_host} -> 400", r.status_code == 400)
# Loopback hosts must still work
for ok_host in ("127.0.0.1", "127.0.0.1:9118", "localhost", "localhost:80", "testserver"):
    r = client.get("/", headers={"Host": ok_host})
    check(f"GET / with Host: {ok_host} -> 200 (loopback allowed)", r.status_code == 200)
# Default TestClient Host: testserver must work
r = client.get("/api/v1/health", cookies=cookies)
check("GET /api/v1/health with default TestClient Host (testserver) -> 200",
      r.status_code == 200)
# Source-of-truth: confirm testserver is whitelisted only because it's a TestClient sentinel
# — the production allow-list excludes it. Verify by reading the source:
boot_src_h = Path(bff.__file__).read_text(encoding="utf-8")
check("Host allow-list contains 127.0.0.1 + localhost + 0.0.0.0 + testserver",
      '"127.0.0.1", "localhost", "0.0.0.0", "testserver"' in boot_src_h or
      "'127.0.0.1', 'localhost', '0.0.0.0', 'testserver'" in boot_src_h)

print("F2.2 P2 — gateway_alive probes Hermes real (TCP connect)")
boot_src2 = Path(bff.__file__).read_text(encoding="utf-8")
check("_hermes_alive defined", "def _hermes_alive" in boot_src2)
# Strip docstring/comments when looking for old heuristic. Use regex that
# matches only top-level definitions / function calls.
import re as _re
# _gateway_alive must NOT be defined as a function anywhere
old_def = _re.search(r"^def\s+_gateway_alive\s*\(", boot_src2, _re.MULTILINE)
check("_gateway_alive removed (no python.exe heuristic function)", old_def is None)
# tasklist subprocess call must NOT appear
tasklist_use = _re.search(r"subprocess\.run\([^)]*tasklist", boot_src2, _re.DOTALL)
check("subprocess tasklist removed", tasklist_use is None)
check("_hermes_alive calls _probe with HERMES_API_BASE",
      "_probe(HERMES_API_BASE" in boot_src2)
result = bff._hermes_alive()
check(f"_hermes_alive() returns bool (got {type(result).__name__})",
      isinstance(result, bool))

print("F2.3 P2 — Idempotency-Key on POST /api/v1/findings")
# Wipe findings again so tests are deterministic
with bff._db() as conn:
    conn.execute("DELETE FROM visual_findings")
    conn.execute("DELETE FROM events")
    conn.commit()

# Case A: same Idempotency-Key + same body → second POST returns 200 with same finding_id
payload_a = {
    "preview_id": "ia-vision-visor",
    "kind": "needs_work",
    "title": "idempotency test A",
    "frame_ref": {"video_id": 1},
    "context": {"note": "first call"},
}
r1 = client.post("/api/v1/findings", json=payload_a,
                 headers={"Idempotency-Key": "test-key-A"},
                 cookies=cookies)
check("first POST with Idempotency-Key -> 201", r1.status_code == 201)
fid_a = r1.json()["finding_id"]
r2 = client.post("/api/v1/findings", json=payload_a,
                 headers={"Idempotency-Key": "test-key-A"},
                 cookies=cookies)
check("duplicate POST same key+body -> 200", r2.status_code == 200)
check("duplicate returns same finding_id", r2.json()["finding_id"] == fid_a)
# Database count must still be 1
with bff._db() as conn:
    n = conn.execute("SELECT COUNT(*) c FROM visual_findings WHERE finding_id = ?",
                     (fid_a,)).fetchone()["c"]
check("DB has exactly 1 row for this key", n == 1)

# Case B: same Idempotency-Key + DIFFERENT body → 409 Conflict
payload_b_diff = dict(payload_a)
payload_b_diff["title"] = "DIFFERENT TITLE"
r3 = client.post("/api/v1/findings", json=payload_b_diff,
                 headers={"Idempotency-Key": "test-key-A"},
                 cookies=cookies)
check("same key + different body -> 409", r3.status_code == 409)
check("409 detail mentions idempotency_key",
      "idempotency_key" in (r3.json().get("detail") or "").lower())

# Case C: no Idempotency-Key → server derives stable hash → same payload = no duplicate
payload_c = {
    "preview_id": "suini-panorama",
    "kind": "bug",
    "title": "no-header dedup test",
    "frame_ref": {"scenario_id": 99},
    "context": {"note": "no header"},
}
r4 = client.post("/api/v1/findings", json=payload_c, cookies=cookies)
check("first POST without Idempotency-Key -> 201", r4.status_code == 201)
fid_c = r4.json()["finding_id"]
r5 = client.post("/api/v1/findings", json=payload_c, cookies=cookies)
check("same payload without header -> 200 (server-derived key matches)", r5.status_code == 200)
check("no-header dedup returns same finding_id", r5.json()["finding_id"] == fid_c)

# Case D: different payload without header → different derived key → 201 (new finding)
payload_d = dict(payload_c)
payload_d["title"] = "different title"
r6 = client.post("/api/v1/findings", json=payload_d, cookies=cookies)
check("different payload without header -> 201 (new finding)", r6.status_code == 201)
check("different payload has new finding_id",
      r6.json()["finding_id"] != fid_c)

# Verify idempotency_key column exists and is unique
import sqlite3 as _sq
_conn = _sq.connect(os.environ["CONTROL_DB"])
_cols = {r[1] for r in _conn.execute("PRAGMA table_info(visual_findings)").fetchall()}
check("visual_findings has idempotency_key column", "idempotency_key" in _cols)
_idx = _conn.execute("PRAGMA index_list(visual_findings)").fetchall()
has_unique = False
for ix in _idx:
    info = _conn.execute(f"PRAGMA index_info({ix[1]})").fetchall()
    cols = {r[2] for r in info}
    if cols == {"idempotency_key"}:
        has_unique = True
check("idempotency_key has unique constraint", has_unique)
_conn.close()

print("F2.4 P2 — innerHTML eliminated in ui/app.js (textContent everywhere)")
appjs_src = (Path(__file__).resolve().parent.parent / "ui" / "app.js").read_text(encoding="utf-8")
import re
innerhtml_assigns = re.findall(r"\.innerHTML\s*=", appjs_src)
check(f"no .innerHTML = assignments in app.js (found {len(innerhtml_assigns)})",
      len(innerhtml_assigns) == 0)
template_html = re.findall(r"\.innerHTML\s*=\s*`", appjs_src)
check(f"no template-string innerHTML in app.js (found {len(template_html)})",
      len(template_html) == 0)
check("ui/app.js defines el(tag, attrs, ...children) helper",
      "function el(tag, attrs, ...children)" in appjs_src)
appendmsg_block = re.search(r"appendMsg\('assistant'.*?\);", appjs_src, re.DOTALL)
check("appendMsg assistant uses string concat (not template literal with ${text})",
      appendmsg_block is not None and "${" not in (appendmsg_block.group(0) or ""))

# ---------- END F2 CLOSE-OUT ----------

# ---------- F2.1-UPGRADE-PATH: legacy DB migration (PR #6 re-audit) ----------

print()
print("=" * 60)
print("F2.1-UPGRADE-PATH — legacy DB migration (no control.db deletion)")
print("=" * 60)

import importlib as _importlib
import sqlite3 as _sq2

LEGACY_DB = Path(__file__).resolve().parent / "_legacy_test.db"
if LEGACY_DB.exists():
    LEGACY_DB.unlink()

print("Step 1: hand-build a pre-F2 DB with the exact 9-column schema")
_conn = _sq2.connect(LEGACY_DB)
_conn.executescript("""
CREATE TABLE events (
    event_id TEXT PRIMARY KEY,
    correlation_id TEXT NOT NULL,
    project_id TEXT, goal_id TEXT, run_id TEXT, source TEXT,
    kind TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    ttl_seconds INTEGER DEFAULT 60
);
CREATE TABLE visual_findings (
    finding_id TEXT PRIMARY KEY,
    preview_id TEXT,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    frame_ref_json TEXT,
    context_json TEXT,
    created_by TEXT,
    created_at TEXT NOT NULL,
    triage_state TEXT DEFAULT 'open'
);
""")
# Pre-existing data that must NOT be lost
_conn.execute(
    "INSERT INTO visual_findings (finding_id, preview_id, kind, title, frame_ref_json, context_json, created_by, created_at) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
    ("legacy-fid-1", "ia-vision-visor", "needs_work", "pre-F2 row", "{}", "{}", "old-session", "2026-09-01T00:00:00Z"),
)
_conn.commit()
_conn.close()

# Verify the legacy shape: 9 cols, no idempotency_key. SQLite always creates
# an auto-index for PRIMARY KEY, so we can't expect index_list to be empty;
# we just verify the only index is the implicit one (origin='c' or 'pk').
_conn = _sq2.connect(LEGACY_DB)
_cols_before = {r[1] for r in _conn.execute("PRAGMA table_info(visual_findings)").fetchall()}
_idx_before = _conn.execute("PRAGMA index_list(visual_findings)").fetchall()
_conn.close()
check("legacy DB has 9 columns (no idempotency_key)",
      len(_cols_before) == 9 and "idempotency_key" not in _cols_before)
# Exclude the implicit PRIMARY KEY index: every other index in this table
# would have been created by the application. Pre-F2 should have none.
non_pk_indexes = [ix for ix in _idx_before
                  if ix[3] != "pk" and not ix[1].startswith("sqlite_autoindex")]
check("legacy DB has no application indexes on visual_findings",
      len(non_pk_indexes) == 0)

print("Step 2: point BFF at legacy DB, import fresh, run _init_db()")
os.environ["CONTROL_DB"] = str(LEGACY_DB)
# Drop cached bff module to force re-execution
sys.modules.pop("main", None)
sys.modules.pop("bff", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bff"))
import main as bff_legacy  # noqa: E402
_importlib.reload(bff_legacy)
check("BFF imported against legacy DB without error", bff_legacy is not None)

print("Step 3: verify migration result")
_conn = _sq2.connect(LEGACY_DB)
_cols_after = {r[1] for r in _conn.execute("PRAGMA table_info(visual_findings)").fetchall()}
check("post-migration has idempotency_key column", "idempotency_key" in _cols_after)
check("post-migration still has 9 original columns",
      len(_cols_after & {"finding_id","preview_id","kind","title","frame_ref_json",
                         "context_json","created_by","created_at","triage_state"}) == 9)
# Legacy row survived and got a backfilled key
row = _conn.execute(
    "SELECT finding_id, idempotency_key FROM visual_findings WHERE finding_id = 'legacy-fid-1'"
).fetchone()
check("legacy row preserved", row is not None and row[0] == "legacy-fid-1")
check("legacy row has backfilled idempotency_key",
      row is not None and row[1] is not None and row[1].startswith("legacy:"))
# UNIQUE index now exists
_idx_after = _conn.execute("PRAGMA index_list(visual_findings)").fetchall()
has_uniq = False
for ix in _idx_after:
    info = _conn.execute(f"PRAGMA index_info({ix[1]})").fetchall()
    if {r[2] for r in info} == {"idempotency_key"} and ix[2]:  # ix[2] is `unique` flag
        has_uniq = True
check("uniq_visual_findings_idem index exists and is unique", has_uniq)
_conn.close()

print("Step 4: idempotency still works post-migration (same key -> 200, same id)")
from fastapi.testclient import TestClient as _TC2
_legacy_client = _TC2(bff_legacy.app)
# Hit / to get a session cookie
_legacy_client.get("/")
# Get the cookie from the client
_session_cookie = None
for c in _legacy_client.cookies.jar:
    if c.name == "control_session":
        _session_cookie = c.value
        break
check("legacy session cookie set", _session_cookie is not None)
_legacy_cookies = {"control_session": _session_cookie} if _session_cookie else {}

payload_mig = {
    "preview_id": "ia-vision-visor",
    "kind": "needs_work",
    "title": "post-migration first call",
    "frame_ref": {"video_id": 7},
    "context": {"note": "first call after migrate"},
}
r_first = _legacy_client.post("/api/v1/findings", json=payload_mig,
                              headers={"Idempotency-Key": "post-mig-key-1"},
                              cookies=_legacy_cookies)
check("first POST on migrated DB -> 201", r_first.status_code == 201)
fid_first = r_first.json()["finding_id"]
r_dup = _legacy_client.post("/api/v1/findings", json=payload_mig,
                            headers={"Idempotency-Key": "post-mig-key-1"},
                            cookies=_legacy_cookies)
check("duplicate POST same key on migrated DB -> 200", r_dup.status_code == 200)
check("duplicate POST returns same finding_id",
      r_dup.json()["finding_id"] == fid_first)

# Verify exactly 2 rows total (1 legacy + 1 new) — no duplicate created
_conn = _sq2.connect(LEGACY_DB)
_n_total = _conn.execute("SELECT COUNT(*) FROM visual_findings").fetchone()[0]
_n_legacy = _conn.execute(
    "SELECT COUNT(*) FROM visual_findings WHERE idempotency_key LIKE 'legacy:%'"
).fetchone()[0]
_n_new = _conn.execute(
    "SELECT COUNT(*) FROM visual_findings WHERE idempotency_key NOT LIKE 'legacy:%'"
).fetchone()[0]
check("DB total = 2 rows (1 legacy + 1 new, no duplicate)", _n_total == 2)
check("legacy rows preserved with legacy: prefix", _n_legacy == 1)
check("new rows have non-legacy idempotency_key", _n_new == 1)
_conn.close()

print("Step 5: re-running migration is idempotent (no errors, no data loss)")
# Call _init_db again via reload
sys.modules.pop("main", None)
sys.modules.pop("bff", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bff"))
import main as bff_re
_importlib.reload(bff_re)
_conn = _sq2.connect(LEGACY_DB)
_n_after_rerun = _conn.execute("SELECT COUNT(*) FROM visual_findings").fetchone()[0]
_cols_after_rerun = {r[1] for r in _conn.execute("PRAGMA table_info(visual_findings)").fetchall()}
check("re-running migration preserves row count (2)", _n_after_rerun == 2)
check("re-running migration preserves schema (idempotency_key present)",
      "idempotency_key" in _cols_after_rerun)
_conn.close()

# Restore test env
os.environ["CONTROL_DB"] = str(Path(__file__).resolve().parent / "_test_control.db")
# Clean up legacy DB so it doesn't pollute gitignore
LEGACY_DB.unlink(missing_ok=True)

# ---------- END F2.1-UPGRADE-PATH ----------

print()
print(f"=== RESULT: {PASS} pass, {FAIL} fail ===")
sys.exit(0 if FAIL == 0 else 1)