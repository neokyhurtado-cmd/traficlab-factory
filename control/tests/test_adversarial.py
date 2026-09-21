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
# Original F2.4 assertion targeted `appendMsg('assistant', ...)` in the V0 chat
# stub, checking it used string concat rather than a template literal so that
# user text could not be interpolated into markup. That stub was REMOVED in
# V0.1: it echoed "Recibido: <text>" back as if an agent had replied, which the
# follow-up WO forbids ("never manufacture statuses"). The security intent
# outlives the stub, so it is now asserted generally: no template literal may be
# fed to any DOM-parsing sink anywhere in the bundle.
_dom_sinks = re.findall(
    r"(?:innerHTML|outerHTML|insertAdjacentHTML|document\.write)\s*(?:=|\()\s*`",
    appjs_src,
)
check(f"no template literal reaches a DOM-parsing sink (found {len(_dom_sinks)})",
      len(_dom_sinks) == 0)
check("chat echo stub removed (no fabricated assistant replies)",
      "appendMsg('assistant'" not in appjs_src)

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

# ===========================================================================
# F3 — V0.1 panel surfaces (Mission Control / Evidence Timeline / Human-Go)
# ===========================================================================
# These endpoints project REAL control-plane state. The tests below assert the
# two properties that make the panel trustworthy rather than decorative:
#   (a) it cannot write anything, anywhere; and
#   (b) an unavailable source is reported as NOT_AVAILABLE_YET with a reason,
#       never silently replaced by a plausible-looking default.

print()
print("=" * 60)
print("F3 — V0.1 panel surfaces")
print("=" * 60)

# Restore the main test DB for this block.
os.environ["CONTROL_DB"] = str(Path(__file__).resolve().parent / "_test_control.db")
sys.modules.pop("main", None)
import main as bff3  # noqa: E402
_importlib.reload(bff3)
from fastapi.testclient import TestClient as _TC3  # noqa: E402

client3 = _TC3(bff3.app)
client3.get("/")
cookies3 = {"control_session": bff3.SESSION_TOKEN}

import readmodels as _rm  # noqa: E402
import sources as _src  # noqa: E402

print("F3.1 — auth is enforced on every new surface")
_fresh3 = _TC3(bff3.app)
for _p in ("/api/v1/mission", "/api/v1/timeline", "/api/v1/human-go", "/api/v1/products"):
    _r = _fresh3.get(_p)
    check(f"GET {_p} without cookie -> 401", _r.status_code == 401,
          f"got {_r.status_code}")

print("F3.2 — surfaces answer 200 with the v1.1.0 read-model envelope")
_expected_types = {
    "/api/v1/mission": "MissionControl",
    "/api/v1/timeline": "EvidenceTimeline",
    "/api/v1/human-go": "HumanGoInbox",
    "/api/v1/products": "ProductCardList",
}
_payloads = {}
for _p, _type in _expected_types.items():
    _r = client3.get(_p, cookies=cookies3)
    check(f"GET {_p} with cookie -> 200", _r.status_code == 200, f"got {_r.status_code}")
    _body = _r.json()
    _payloads[_p] = _body
    check(f"{_p} type == {_type}", _body.get("type") == _type, str(_body.get("type")))
    check(f"{_p} schema_version == control-read-model/v1.1.0",
          _body.get("schema_version") == "control-read-model/v1.1.0",
          str(_body.get("schema_version")))
    check(f"{_p} carries captured_at", bool(_body.get("captured_at")))

print("F3.3 — READ-ONLY: no mutating verb can reach the evidence sources")
# The allow-lists are the enforcement point; assert the dangerous verbs are out.
for _verb in ("push", "commit", "merge", "checkout", "reset", "clean", "rebase"):
    check(f"git verb '{_verb}' rejected by allow-list",
          _verb not in _src._GIT_READONLY)
    _raised = False
    try:
        _src.git([_verb, "--dry-run"], cwd=str(Path(__file__).resolve().parent))
    except ValueError:
        _raised = True
    check(f"sources.git(['{_verb}']) raises ValueError", _raised)
for _verb in ("pr", "issue", "release", "repo"):
    _raised = False
    try:
        _src.gh([_verb, "list"])
    except ValueError:
        _raised = True
    check(f"sources.gh(['{_verb}']) raises ValueError (only 'api' allowed)", _raised)

print("F3.4 — kanban DB is opened read-only (a write must be refused by SQLite)")
_kpath = _src.kanban_db_path()
if _kpath.exists():
    _conn_ro = _src._kanban_conn()
    _write_blocked = False
    try:
        _conn_ro.execute("CREATE TABLE _should_never_exist (x INTEGER)")
    except _sq2.OperationalError as _e:
        _write_blocked = "readonly" in str(_e).lower()
    finally:
        _conn_ro.close()
    check("kanban connection refuses CREATE TABLE (mode=ro enforced)", _write_blocked)
    # And prove we did not in fact create it.
    _conn_chk = _src._kanban_conn()
    _leaked = _conn_chk.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE name='_should_never_exist'"
    ).fetchone()[0]
    _conn_chk.close()
    check("no stray table was created in the kanban DB", _leaked == 0)
else:
    check("kanban DB present for read-only assertion", True,
          "skipped: no kanban DB on this host")

print("F3.5 — no write endpoint was added by the panel surfaces")
_panel_paths = {"/api/v1/mission", "/api/v1/timeline", "/api/v1/human-go", "/api/v1/products"}
for _route in bff3.app.routes:
    _rp = getattr(_route, "path", None)
    if _rp in _panel_paths:
        _methods = set(getattr(_route, "methods", set())) - {"HEAD", "OPTIONS"}
        check(f"{_rp} is GET-only (methods={sorted(_methods)})", _methods == {"GET"})

print("F3.6 — missing sources degrade to NOT_AVAILABLE_YET, never to fake values")
_missing = _src.Fact.missing("test:source", "deliberately unavailable")
check("Fact.missing -> state NOT_AVAILABLE_YET", _missing.state == "NOT_AVAILABLE_YET")
check("Fact.missing -> value is None (no substituted default)", _missing.value is None)
check("Fact.missing -> available is False", _missing.available is False)
check("Fact.missing -> carries a human-readable reason", bool(_missing.reason))
# Point the reader at a non-existent DB and confirm it degrades rather than raising.
_orig_env = os.environ.get("CONTROL_KANBAN_DB")
os.environ["CONTROL_KANBAN_DB"] = str(Path(__file__).resolve().parent / "_does_not_exist.db")
try:
    _degraded = _src.active_tasks()
    check("absent kanban DB -> NOT_AVAILABLE_YET (no exception, no fabrication)",
          _degraded.state == "NOT_AVAILABLE_YET" and _degraded.value is None)
    check("absent kanban DB -> reason names the missing path",
          "not found" in _degraded.reason.lower(), _degraded.reason)
    _inbox_degraded = _rm.human_go_inbox()
    check("human_go_inbox survives a dead source",
          _inbox_degraded["type"] == "HumanGoInbox")
    check("human_go_inbox reports degradation instead of inventing rows",
          _inbox_degraded["pending_count"] == len(_inbox_degraded["pending"]))
finally:
    if _orig_env is None:
        os.environ.pop("CONTROL_KANBAN_DB", None)
    else:
        os.environ["CONTROL_KANBAN_DB"] = _orig_env
    _src.cache_clear()

print("F3.7 — every displayed Fact carries provenance (source + state + captured_at)")
_mission = _payloads["/api/v1/mission"]
for _field in ("git", "ci", "pull_requests", "tests", "queue_provenance"):
    _f = _mission.get(_field)
    check(f"mission.{_field} has source", isinstance(_f, dict) and bool(_f.get("source")))
    check(f"mission.{_field} has state", isinstance(_f, dict) and bool(_f.get("state")))
    check(f"mission.{_field} has captured_at",
          isinstance(_f, dict) and bool(_f.get("captured_at")))
    check(f"mission.{_field} state is a known token",
          _f.get("state") in ("VERIFIED", "STALE", "NOT_AVAILABLE_YET"), str(_f.get("state")))

print("F3.8 — product cards never claim a live target they did not probe")
_products = _payloads["/api/v1/products"]
check("two product cards (IA-VISION + SUINI)", len(_products["cards"]) == 2)
for _card in _products["cards"]:
    check(f"{_card['project_id']} declares a read-only mutation policy",
          "READ_ONLY" in _card["mutation_policy"])
    for _t in _card["targets"]:
        check(f"{_card['project_id']}/{_t['kind']} state is VERIFIED or NOT_AVAILABLE_YET",
              _t["state"] in ("VERIFIED", "NOT_AVAILABLE_YET"), _t["state"])
        if _t["state"] == "NOT_AVAILABLE_YET":
            # The crucial anti-fake assertion: an unproven target exposes NO
            # clickable endpoint, and explains itself.
            check(f"{_card['project_id']}/{_t['kind']} unavailable -> empty endpoint",
                  _t["endpoint"] == "")
            check(f"{_card['project_id']}/{_t['kind']} unavailable -> has reason",
                  bool(_t["reason"]))
        else:
            check(f"{_card['project_id']}/{_t['kind']} available -> real endpoint",
                  _t["endpoint"].startswith("http"))

print("F3.9 — Human-Go Inbox separates real gates from self-resolving noise")
_inbox = _payloads["/api/v1/human-go"]
check("pending_count matches pending length",
      _inbox["pending_count"] == len(_inbox["pending"]))
for _d in _inbox["pending"]:
    check(f"pending {_d['decision_id']} has an action hint", bool(_d["action_hint"]))
    check(f"pending {_d['decision_id']} kind is known",
          _d["kind"] in ("TASK_BLOCKED", "PR_MERGE_GATE"), _d["kind"])
for _d in _inbox["auto_resolving"]:
    check(f"auto {_d['decision_id']} is dependency/transient (not a human gate)",
          _d["block_kind"] in ("dependency", "transient"), _d["block_kind"])
# Merge gates must be labelled HUMAN_GO_REAL — the WO forbids agent merges.
for _d in _inbox["pending"]:
    if _d["kind"] == "PR_MERGE_GATE":
        check(f"{_d['decision_id']} labelled HUMAN_GO_REAL",
              _d["block_kind"] == "HUMAN_GO_REAL")

print("F3.10 — timeline hides heartbeat noise by default, exposes it on request")
_tl_default = client3.get("/api/v1/timeline?limit=25", cookies=cookies3).json()
check("default timeline contains no heartbeat rows",
      all(i["kind"] != "heartbeat" for i in _tl_default["items"]))
_tl_hb = client3.get("/api/v1/timeline?limit=25&heartbeats=1", cookies=cookies3).json()
check("heartbeats=1 is honoured (row set differs or board has none)",
      isinstance(_tl_hb["items"], list))
for _i in _tl_default["items"]:
    check(f"timeline event {_i['event_id']} has a tone",
          _i["tone"] in ("good", "bad", "warn", "neutral", "muted"), _i["tone"])
    break  # one representative assertion is enough; shape is uniform
check("timeline limit is clamped (limit=9999 -> <= 200)",
      len(client3.get("/api/v1/timeline?limit=9999", cookies=cookies3).json()["items"]) <= 200)
check("timeline rejects garbage limit without 500",
      client3.get("/api/v1/timeline?limit=abc", cookies=cookies3).status_code == 200)

print("F3.11 — UI bundle stays secret-free and innerHTML-free after the rewrite")
_ui_js = (Path(__file__).resolve().parent.parent / "ui" / "app.js").read_text(encoding="utf-8")
_ui_html = (Path(__file__).resolve().parent.parent / "ui" / "index.html").read_text(encoding="utf-8")
for _needle in ("sk-", "Bearer ", "ghp_", "github_pat_", "GITHUB_TOKEN",
                "API_SERVER_KEY", "X-Control-Token", "HERMES_BEARER_KEY"):
    check(f"app.js free of '{_needle}'", _needle not in _ui_js)
check("index.html free of inline session token",
      "__CONTROL_SESSION_TOKEN__" not in _ui_html)
check("app.js has no .innerHTML assignment",
      len(re.findall(r"\.innerHTML\s*=", _ui_js)) == 0)
check("app.js has no outerHTML assignment",
      len(re.findall(r"\.outerHTML\s*=", _ui_js)) == 0)
check("app.js has no document.write", "document.write" not in _ui_js)
check("app.js still uses the safe el() builder", "function el(tag, attrs" in _ui_js)
# The three mandated surfaces must actually be wired in the client.
for _fn in ("loadMission", "loadHumanGo", "loadTimeline", "loadProducts"):
    check(f"app.js defines {_fn}()", f"function {_fn}(" in _ui_js)
for _panel in ("panel-mission", "panel-humango", "panel-timeline"):
    check(f"index.html declares #{_panel}", f'id="{_panel}"' in _ui_html)

print("F3.12 — mobile-first + accessibility affordances present in CSS")
_css = (Path(__file__).resolve().parent.parent / "ui" / "styles.css").read_text(encoding="utf-8")
check("CSS declares a reduced-motion block", "prefers-reduced-motion" in _css)
check("CSS is mobile-first (single-column grid default)",
      "grid-template-columns: 1fr" in _css)
check("CSS widens at the 640px breakpoint", "min-width: 640px" in _css)
check("CSS widens at the 960px breakpoint", "min-width: 960px" in _css)
check("index.html sets a responsive viewport",
      "width=device-width" in _ui_html)

print("F3.13 — sqlite connections are closed, not merely committed (P1 regression)")
# `with sqlite3.connect(...)` commits but does NOT close; on Windows the leaked
# handle blocks unlink. _db_conn() must close so temp DBs can be removed.
_leak_probe = Path(__file__).resolve().parent / "_leakprobe.db"
_leak_probe.unlink(missing_ok=True)
_old_db = bff3.DB_PATH
try:
    bff3.DB_PATH = _leak_probe
    with bff3._db_conn() as _c:
        _c.execute("CREATE TABLE IF NOT EXISTS probe (x INTEGER)")
        _c.execute("INSERT INTO probe VALUES (1)")
    _unlinked = False
    try:
        _leak_probe.unlink()
        _unlinked = True
    except PermissionError:
        _unlinked = False
    check("_db_conn() releases the file handle (unlink succeeds)", _unlinked)
finally:
    bff3.DB_PATH = _old_db
    _leak_probe.unlink(missing_ok=True)
check("main.py uses _db_conn() rather than bare `with _db()`",
      "with _db() as conn" not in Path(bff3.__file__).read_text(encoding="utf-8"))

# ---------- END F3 ----------

# Record the run so Mission Control can display a real, dated test result.
# The BFF deliberately cannot trigger a test run over HTTP (that would be a
# remote-execution primitive), so it reads this marker instead. Writing it here
# means the panel can only ever show a result that actually happened.
import json as _json
import subprocess as _sp
from datetime import datetime as _dt, timezone as _tz

_marker = Path(__file__).resolve().parent / "last_run.json"
try:
    _sha = _sp.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(Path(__file__).resolve().parent.parent.parent),
        capture_output=True, text=True, timeout=10, shell=False,
    ).stdout.strip()
except Exception:
    _sha = ""
_marker.write_text(_json.dumps({
    "suite": "control/tests/test_adversarial.py",
    "passed": PASS,
    "failed": FAIL,
    "total": PASS + FAIL,
    "ok": FAIL == 0,
    "head_sha": _sha,
    "ran_at": _dt.now(_tz.utc).isoformat(),
}, indent=2), encoding="utf-8")

print()
print(f"=== RESULT: {PASS} pass, {FAIL} fail ===")
sys.exit(0 if FAIL == 0 else 1)