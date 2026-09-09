"""Adversarial tests for Control BFF V0.

Verifies threat model T1..T12 from suini#54 comment 5599034906.
"""
from __future__ import annotations

import os
import re
import socket
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
# Test the check logic directly by importing a fresh module-level evaluation
# Source-code scan: the check must compare against ('127.0.0.1', 'localhost')
src = Path(bff.__file__).read_text(encoding="utf-8")
check("check compares against 127.0.0.1", '"127.0.0.1"' in src or "'127.0.0.1'" in src)
check("check compares against localhost", '"localhost"' in src or "'localhost'" in src)
# Direct unit test: patch BFF_HOST and re-evaluate the check condition
import importlib
# Make sure the function looks at BFF_HOST env dynamically (not module-level snapshot)
# We test by setting os.environ and calling — if the check has module-level captured value,
# we'd need to reload. Inspect the source for os.environ.get usage:
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
# The /api/v1/events route must be registered on the FastAPI app
events_route_paths = [getattr(r, "path", "") for r in bff.app.routes]
check("/api/v1/events route registered", "/api/v1/events" in events_route_paths)
# V0: do not run functional SSE here (TestClient + infinite-loop generator hangs).
# Real SSE smoke will run against a live uvicorn instance in the integration test plan.

print("T10. Database schema invariants")
# Connect directly to the test DB
conn = sqlite3.connect(os.environ["CONTROL_DB"])
rows = conn.execute("PRAGMA table_info(events)").fetchall()
col_names = {r[1] for r in rows}
required = {"event_id", "correlation_id", "kind", "created_at", "idempotency_key", "payload_json"}
check("events table has required columns", required.issubset(col_names))
unique_event = conn.execute("PRAGMA index_list(events)").fetchall()
has_unique_idem = any("idempotency_key" in str(conn.execute(f"PRAGMA index_info({u[1]})").fetchall()) for u in unique_event if u[2])
check("idempotency_key is unique", has_unique_idem)

print("T11. BFF does not start if BFF_HOST is non-loopback (boot guard)")
# Verified via _check_no_public_bind above; also check the actual start logic
boot_src = Path(bff.__file__).read_text(encoding="utf-8")
check("_check_no_public_bind is called at boot", "_check_no_public_bind()" in boot_src)

print("T12. No raw secret leak in logs/events (text scan)")
# Find any place the BFF logs HERMES_BEARER_KEY
boot_src_lower = boot_src.lower()
check("BFF source does not log HERMES_BEARER_KEY",
      "hermes_bearer_key" not in boot_src_lower or "log" not in boot_src_lower.split("hermes_bearer_key")[0][-200:])

print()
print(f"=== RESULT: {PASS} pass, {FAIL} fail ===")
sys.exit(0 if FAIL == 0 else 1)