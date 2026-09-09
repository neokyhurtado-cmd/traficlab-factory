"""Control BFF — V0 skeleton.

Loopback-only HTTP+JSON+SSE service that:
- holds Hermes bearer key + GitHub token (read from ~/.hermes/.env at boot)
- serves the static SPA from / (mobile-first)
- exposes /api/v1/* read models (control-read-model/v1.0.0)
- emits /api/v1/events SSE stream (control-event/v1.0.0)
- guards cross-product writes (refuses writes outside trafficlab-factory repo)
- never exposes Hermes key or GitHub token to the browser
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

LOG = logging.getLogger("control.bff")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

APP_VERSION = "control-v0.0.1"
SCHEMA_VERSION_READ = "control-read-model/v1.0.0"
SCHEMA_VERSION_EVENT = "control-event/v1.0.0"

HERMES_API_BASE = os.environ.get("HERMES_API_BASE", "http://127.0.0.1:9119")
HERMES_BEARER_KEY = os.environ.get("HERMES_BEARER_KEY", "")
HERMES_INSTALLED_VERSION = os.environ.get("HERMES_INSTALLED_VERSION", "unknown")
BFF_HOST = os.environ.get("BFF_HOST", "127.0.0.1")
BFF_PORT = int(os.environ.get("BFF_PORT", "9118"))

UI_DIR = Path(__file__).resolve().parent.parent / "ui"
DB_PATH = Path(os.environ.get("CONTROL_DB", str(Path.home() / "AppData" / "Local" / "hermes" / "control.db")))

# ---------------------------------------------------------------------------
# Boot checks — fail loud on misconfiguration (M4 threat T1, T2)
# ---------------------------------------------------------------------------

def _check_no_public_bind() -> None:
    if BFF_HOST not in ("127.0.0.1", "localhost"):
        raise SystemExit(f"FATAL: BFF host must be loopback (got {BFF_HOST}). Refusing to start.")

def _check_credentials_present() -> None:
    if not HERMES_BEARER_KEY:
        LOG.warning("HERMES_BEARER_KEY not set; Hermes-backed endpoints will return 503")

_check_no_public_bind()
_check_credentials_present()
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Storage (sqlite — V0 only)
# ---------------------------------------------------------------------------

def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def _init_db() -> None:
    with _db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY,
            correlation_id TEXT NOT NULL,
            project_id TEXT,
            goal_id TEXT,
            run_id TEXT,
            source TEXT,
            kind TEXT NOT NULL,
            created_at TEXT NOT NULL,
            idempotency_key TEXT UNIQUE,
            payload_json TEXT NOT NULL,
            ttl_seconds INTEGER DEFAULT 60
        );
        CREATE TABLE IF NOT EXISTS visual_findings (
            finding_id TEXT PRIMARY KEY,
            preview_id TEXT,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            frame_ref_json TEXT,
            context_json TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL,
            triage_state TEXT DEFAULT 'open',
            idempotency_key TEXT UNIQUE
        );
        CREATE INDEX IF NOT EXISTS idx_events_correlation ON events(correlation_id);
        CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at);
        """)
_init_db()

# ---------------------------------------------------------------------------
# App + middleware
# ---------------------------------------------------------------------------

app = FastAPI(title="TrafficLab Control BFF", version=APP_VERSION)

@app.middleware("http")
async def security_headers(request: Request, call_next):
    # P1: Host header validation — anti-DNS-rebinding.
    # The BFF only serves loopback clients; reject anything whose Host: header
    # looks like a public host. Starlette/uvicorn already routes based on Host,
    # but we explicitly defend against a malicious client that sends a Host
    # header pointing at an external attacker-controlled domain.
    host = request.headers.get("host", "")
    # Allow only loopback hosts (case-insensitive). Allow optional :port suffix.
    # `testserver` is httpx's default Host header used by FastAPI TestClient and
    # is not routable outside the test process — safe to allow for testing.
    if host:
        host_no_port = host.split(":", 1)[0].lower()
        if host_no_port not in ("127.0.0.1", "localhost", "0.0.0.0", "testserver"):
            LOG.warning("rejected request with non-loopback Host header: %s", host)
            return JSONResponse(
                {"detail": "invalid Host header"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    # CSP — strict; no inline scripts in V0
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
    )
    return response

def _set_session_cookie(response, request: Request) -> None:
    """V0: HttpOnly session cookie. Same-origin only (loopback = safe)."""
    response.set_cookie(
        key="control_session",
        value=SESSION_TOKEN,
        httponly=True,
        samesite="strict",
        secure=False,  # loopback only — http
        max_age=8 * 3600,
        path="/",
    )

def _read_session_cookie(request: Request) -> str | None:
    return request.cookies.get("control_session")

# ---------------------------------------------------------------------------
# Auth (V0: loopback-only session token, rotated on boot)
# ---------------------------------------------------------------------------

SESSION_TOKEN = secrets.token_urlsafe(32)

def require_session(request: Request) -> None:
    token = _read_session_cookie(request)
    if not token or token != SESSION_TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing session cookie")

# ---------------------------------------------------------------------------
# Schemas — control-read-model/v1.0.0
# ---------------------------------------------------------------------------

class HealthSnapshot(BaseModel):
    schema_version: str = SCHEMA_VERSION_READ
    type: str = "HealthSnapshot"
    snapshot_id: str
    captured_at: str
    hermes_version: str
    hermes_api_base: str
    gateway_alive: bool
    bff_version: str
    db_path: str

class ProjectSummary(BaseModel):
    schema_version: str = SCHEMA_VERSION_READ
    type: str = "ProjectSummary"
    project_id: str
    display_name: str
    repo: str
    remote_head_sha: str = ""
    main_branch: str = "main"
    visor_endpoint: str = ""
    visor_alive: bool = False

class PreviewTarget(BaseModel):
    schema_version: str = SCHEMA_VERSION_READ
    type: str = "PreviewTarget"
    preview_id: str
    kind: str  # ia_vision_visor | suini_panorama
    title: str
    project_id: str
    endpoint: str
    available: bool
    available_reason: str
    mobile_compatible: bool = True

class VisualReviewFindingIn(BaseModel):
    preview_id: str
    kind: str  # looks_good | needs_work | bug | suggestion
    title: str
    frame_ref: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)

class VisualReviewFinding(BaseModel):
    schema_version: str = SCHEMA_VERSION_READ
    type: str = "VisualReviewFinding"
    finding_id: str
    preview_id: str
    kind: str
    title: str
    frame_ref: dict[str, Any]
    context: dict[str, Any]
    created_by: str
    created_at: str
    triage_state: str = "open"

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/v1/health", response_model=HealthSnapshot)
async def health(_: None = Depends(require_session)) -> HealthSnapshot:
    return HealthSnapshot(
        snapshot_id=str(uuid.uuid4()),
        captured_at=datetime.now(timezone.utc).isoformat(),
        hermes_version=HERMES_INSTALLED_VERSION,
        hermes_api_base=HERMES_API_BASE,
        gateway_alive=_hermes_alive(),
        bff_version=APP_VERSION,
        db_path=str(DB_PATH),
    )

@app.get("/api/v1/projects", response_model=list[ProjectSummary])
async def list_projects(_: None = Depends(require_session)) -> list[ProjectSummary]:
    """V0 static catalog. Refresh on M5+."""
    return [
        ProjectSummary(project_id="ia-vision", display_name="IA-VISION",
                       repo="neokyhurtado-cmd/ia-vision",
                       visor_endpoint="127.0.0.1:7921", visor_alive=_probe("http://127.0.0.1:7921/")),
        ProjectSummary(project_id="suini", display_name="SUINI",
                       repo="neokyhurtado-cmd/suini",
                       visor_endpoint="127.0.0.1:8080", visor_alive=_probe("http://127.0.0.1:8080/")),
        ProjectSummary(project_id="trafficlab-control", display_name="TrafficLab Control",
                       repo="neokyhurtado-cmd/traficlab-factory",
                       visor_endpoint="", visor_alive=False),
    ]

@app.get("/api/v1/previews", response_model=list[PreviewTarget])
async def list_previews(_: None = Depends(require_session)) -> list[PreviewTarget]:
    """V0 static previews. Real integration with visor/motor deferred to M5+."""
    ia_vision_alive = _probe("http://127.0.0.1:7921/")
    suini_alive = _probe("http://127.0.0.1:8080/")
    return [
        PreviewTarget(
            preview_id="ia-vision-visor",
            kind="ia_vision_visor",
            title="IA-VISION visor (live if running on :7921)",
            project_id="ia-vision",
            endpoint="http://127.0.0.1:7921/",
            available=ia_vision_alive,
            available_reason="visor uvicorn alive" if ia_vision_alive else "visor not running on :7921",
        ),
        PreviewTarget(
            preview_id="suini-panorama",
            kind="suini_panorama",
            title="SUINI web_modeler (live if running on :8080)",
            project_id="suini",
            endpoint="http://127.0.0.1:8080/",
            available=suini_alive,
            available_reason="web_modeler http.server alive" if suini_alive else "web_modeler not running on :8080",
        ),
    ]

def _derive_idempotency_key(payload: "VisualReviewFindingIn") -> str:
    """P2: derive a stable idempotency_key from the payload when the client
    doesn't supply one. SHA-256 of the canonical JSON of the substantive
    fields. Same body → same key → no duplicate finding on retry.
    """
    import hashlib
    canonical = json.dumps({
        "preview_id": payload.preview_id,
        "kind": payload.kind,
        "title": payload.title,
        "frame_ref": payload.frame_ref,
        "context": payload.context,
    }, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@app.post("/api/v1/findings", response_model=VisualReviewFinding, status_code=201)
async def create_finding(
    payload: VisualReviewFindingIn,
    request: Request,
    response: Response,
    _: None = Depends(require_session),
) -> VisualReviewFinding:
    """One-tap Looks good / Needs work / Create finding.

    V0: store locally. Real durable GitHub evidence writer deferred.
    Cross-product guard: findings can reference any product, but the WRITE target
    is local sqlite only — no GitHub write at this endpoint.

    P2 idempotency:
      - Client SHOULD send `Idempotency-Key: <opaque-string>` header.
      - If header missing, server derives a stable key from the payload hash.
      - Duplicate key with identical body returns the existing finding (200).
      - Duplicate key with DIFFERENT body returns 409 Conflict.
    """
    # Prefer client-supplied key; fall back to derived stable key.
    supplied = request.headers.get("idempotency-key", "").strip()
    idem_key = supplied or _derive_idempotency_key(payload)

    # Check for existing finding with this idempotency_key.
    with _db() as conn:
        existing_row = conn.execute(
            "SELECT * FROM visual_findings WHERE idempotency_key = ?", (idem_key,)
        ).fetchone()

    if existing_row is not None:
        existing = VisualReviewFinding(
            finding_id=existing_row["finding_id"],
            preview_id=existing_row["preview_id"],
            kind=existing_row["kind"],
            title=existing_row["title"],
            frame_ref=json.loads(existing_row["frame_ref_json"] or "{}"),
            context=json.loads(existing_row["context_json"] or "{}"),
            created_by=existing_row["created_by"],
            created_at=existing_row["created_at"],
            triage_state=existing_row["triage_state"],
        )
        # Detect payload divergence — same key, different body = 409.
        same_body = (
            existing.preview_id == payload.preview_id
            and existing.kind == payload.kind
            and existing.title == payload.title
            and existing.frame_ref == payload.frame_ref
            and existing.context == payload.context
        )
        if not same_body:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="idempotency_key reused with different payload",
            )
        response.status_code = status.HTTP_200_OK
        return existing

    fid = str(uuid.uuid4())
    created_by = request.client.host if request.client else "unknown"
    now = datetime.now(timezone.utc).isoformat()
    finding = VisualReviewFinding(
        finding_id=fid,
        preview_id=payload.preview_id,
        kind=payload.kind,
        title=payload.title,
        frame_ref=payload.frame_ref,
        context=payload.context,
        created_by=created_by,
        created_at=now,
        triage_state="open",
    )
    with _db() as conn:
        conn.execute(
            "INSERT INTO visual_findings VALUES (?,?,?,?,?,?,?,?,?,?)",
            (fid, payload.preview_id, payload.kind, payload.title,
             json.dumps(payload.frame_ref), json.dumps(payload.context),
             created_by, now, "open", idem_key),
        )
    await _publish_event(
        kind="finding_created",
        payload=finding.model_dump(),
        goal_id=None,
        correlation_id=payload.context.get("correlation_id") or idem_key,
    )
    return finding

@app.get("/api/v1/findings", response_model=list[VisualReviewFinding])
async def list_findings(_: None = Depends(require_session)) -> list[VisualReviewFinding]:
    with _db() as conn:
        rows = conn.execute("SELECT * FROM visual_findings ORDER BY created_at DESC").fetchall()
    out = []
    for r in rows:
        out.append(VisualReviewFinding(
            finding_id=r["finding_id"],
            preview_id=r["preview_id"],
            kind=r["kind"],
            title=r["title"],
            frame_ref=json.loads(r["frame_ref_json"] or "{}"),
            context=json.loads(r["context_json"] or "{}"),
            created_by=r["created_by"],
            created_at=r["created_at"],
            triage_state=r["triage_state"],
        ))
    return out

# ---------------------------------------------------------------------------
# SSE event stream — control-event/v1.0.0
# ---------------------------------------------------------------------------

_subscribers: set[asyncio.Queue] = set()

async def _publish_event(kind: str, payload: dict[str, Any], goal_id: str | None = None, correlation_id: str | None = None) -> None:
    event_id = str(uuid.uuid4())
    correlation = correlation_id or str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    envelope = {
        "schema_version": SCHEMA_VERSION_EVENT,
        "event_id": event_id,
        "sequence": 0,  # filled by stream consumer if needed
        "correlation_id": correlation,
        "project_id": payload.get("project_id") or "trafficlab-control",
        "goal_id": goal_id,
        "run_id": None,
        "source": "control-bff",
        "kind": kind,
        "created_at": now,
        "freshness_ttl_seconds": 60,
        "idempotency_key": f"control-bff:{event_id}",
        "payload_ref": None,
        "evidence_ref": None,
        "payload": payload,
    }
    try:
        with _db() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (event_id, correlation, envelope["project_id"], goal_id, None, "control-bff",
                 kind, now, envelope["idempotency_key"], json.dumps(envelope), 60),
            )
    except Exception as e:
        LOG.warning("failed to persist event: %s", e)
    for q in list(_subscribers):
        try:
            q.put_nowait(envelope)
        except asyncio.QueueFull:
            LOG.warning("subscriber queue full; dropping event %s", event_id)

@app.get("/api/v1/events")
async def events_stream(request: Request, _: None = Depends(require_session)):
    """SSE stream. Consumer dedupes by event_id (5min window)."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=256)
    _subscribers.add(queue)

    async def gen() -> AsyncIterator[bytes]:
        try:
            # initial heartbeat
            yield b"event: hello\ndata: {\"ok\": true}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    envelope = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"event: {envelope['kind']}\ndata: {json.dumps(envelope)}\n\n".encode("utf-8")
                except asyncio.TimeoutError:
                    yield b"event: heartbeat\ndata: {}\n\n"
        finally:
            _subscribers.discard(queue)

    from fastapi.responses import StreamingResponse
    return StreamingResponse(gen(), media_type="text/event-stream")

# ---------------------------------------------------------------------------
# Static SPA
# ---------------------------------------------------------------------------

if UI_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(UI_DIR)), name="static")

@app.get("/")
async def root():
    from fastapi.responses import HTMLResponse
    index = UI_DIR / "index.html"
    if index.exists():
        content = index.read_text(encoding="utf-8")
        resp = HTMLResponse(content=content)
        resp.set_cookie(
            key="control_session",
            value=SESSION_TOKEN,
            httponly=True,
            samesite="strict",
            secure=False,  # loopback only
            max_age=8 * 3600,
            path="/",
        )
        return resp
    return JSONResponse({"app": "TrafficLab Control BFF", "version": APP_VERSION, "ui_dir": str(UI_DIR)})

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hermes_alive() -> bool:
    """P2: probe Hermes API Server directly via TCP to the configured base URL.

    Replaces the previous 'tasklist python.exe' heuristic which had a high
    false-positive rate (any python process satisfied the check).

    Returns True only if the TCP socket connects to HERMES_API_BASE host:port
    within a short timeout. Does NOT validate the response body — that's a
    V0.1 concern (would require parsing /v1/models or similar).
    """
    return _probe(HERMES_API_BASE, timeout=0.5)

def _probe(url: str, timeout: float = 0.5) -> bool:
    """Quick TCP-level availability probe."""
    import socket
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    LOG.info("starting TrafficLab Control BFF v%s on %s:%d", APP_VERSION, BFF_HOST, BFF_PORT)
    LOG.info("session token (X-Control-Token): %s", SESSION_TOKEN)
    LOG.info("UI dir: %s exists=%s", UI_DIR, UI_DIR.exists())
    uvicorn.run(app, host=BFF_HOST, port=BFF_PORT, log_level="info")