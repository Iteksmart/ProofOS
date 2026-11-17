from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.api import ai, analytics, approvals, audits, auth, automations, changes, cmdb, consulting, devices, enclaves, integrations, itechsmart, knowledge, mcp_registry, monitor, onboarding, ops, patches, proof, push, remote, scripts, secrets, sso, tickets, time_tracking, vms
from app.core import pubsub
from app.core.config import get_settings
from app.core.db import check_db, init_db
from app.core.security import decode_token
from app.api import reports, search
from app.api import investigations
from app.api import access, fleet, recovery, telemetry, topology
from app.api import billing, customers, patching, thresholds
from app.api import anchors, portal, slos, vulnerabilities

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("proofos")

_ws_subscribers: dict[WebSocket, int | None] = {}


def _events_for_org(events: list[dict], org_id: int | None) -> list[dict]:
    if org_id is None:
        return []
    return [event for event in events if event.get("org_id") == org_id]


async def _broadcast_loop() -> None:
    while True:
        await asyncio.sleep(0.5)
        events = pubsub.drain()
        if not events:
            continue
        for ws, ws_org in list(_ws_subscribers.items()):
            # Tenant events must never fall through to every connected client.
            # Events without an org are intentionally omitted from tenant feeds.
            relevant = _events_for_org(events, ws_org)
            if not relevant:
                continue
            try:
                await ws.send_text(json.dumps({"events": relevant}))
            except Exception:
                _ws_subscribers.pop(ws, None)


async def _status_sync_loop() -> None:
    from app.core.db import SessionLocal
    from app.services.status_sync import sync_device_statuses

    while True:
        await asyncio.sleep(60)
        try:
            db = SessionLocal()
            try:
                sync_device_statuses(db)
            finally:
                db.close()
        except Exception as e:  # noqa: BLE001
            log.warning("status sync error: %s", e)


async def _patch_policy_loop() -> None:
    from app.core.db import SessionLocal
    from app.services.patching import run_due_policies

    while True:
        await asyncio.sleep(300)
        try:
            db = SessionLocal()
            try:
                run_due_policies(db)
            finally:
                db.close()
        except Exception as e:  # noqa: BLE001
            log.warning("patch policy scheduler error: %s", e)


async def _anchor_loop() -> None:
    """Timestamp the ledger head with an independent authority on a fixed interval."""
    import os

    from app.core.db import SessionLocal
    from app.services.anchoring import anchor_now

    minutes = int(os.getenv("PROOF_ANCHOR_INTERVAL_MINUTES", "60"))
    if minutes <= 0:
        return
    while True:
        await asyncio.sleep(minutes * 60)
        try:
            db = SessionLocal()
            try:
                await asyncio.to_thread(anchor_now, db)
            finally:
                db.close()
        except Exception as e:  # noqa: BLE001 - an unreachable authority must not stop the API
            log.warning("proof anchoring failed: %s", e)


async def _vulnerability_loop() -> None:
    """Re-match every tenant's installed software against OSV once a day (configurable)."""
    import os

    from app.core.db import SessionLocal
    from app.models.models import Org
    from app.services.vulnerabilities import scan

    hours = float(os.getenv("VULN_SCAN_INTERVAL_HOURS", "24"))
    if hours <= 0:
        return
    while True:
        await asyncio.sleep(hours * 3600)
        db = SessionLocal()
        try:
            for org_id in [o.id for o in db.query(Org).all()]:
                try:
                    await asyncio.to_thread(scan, db, org_id)
                except Exception as e:  # noqa: BLE001 - OSV outages must not stop the API
                    db.rollback()
                    log.warning("vulnerability scan failed org=%s: %s", org_id, e)
        finally:
            db.close()


async def _slo_loop() -> None:
    """Evaluate every SLO each minute so error-budget burn pages promptly."""
    from app.core.db import SessionLocal
    from app.models.models import ServiceSlo
    from app.services.slo import check

    while True:
        await asyncio.sleep(60)
        db = SessionLocal()
        try:
            for org_id in {o for (o,) in db.query(ServiceSlo.org_id).distinct().all()}:
                await asyncio.to_thread(check, db, org_id)
        except Exception as e:  # noqa: BLE001
            db.rollback()
            log.warning("SLO evaluation failed: %s", e)
        finally:
            db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate_production()
    init_db()
    broadcast = asyncio.create_task(_broadcast_loop())
    status_sync = asyncio.create_task(_status_sync_loop())
    patch_scheduler = asyncio.create_task(_patch_policy_loop())
    anchor_scheduler = asyncio.create_task(_anchor_loop())
    vuln_scheduler = asyncio.create_task(_vulnerability_loop())
    slo_scheduler = asyncio.create_task(_slo_loop())
    log.info("ProofOS API ready env=%s db_ok=%s", settings.api_env, check_db())
    yield
    broadcast.cancel()
    status_sync.cancel()
    patch_scheduler.cancel()
    anchor_scheduler.cancel()
    vuln_scheduler.cancel()
    slo_scheduler.cancel()


from app.services.kill_switch import KillSwitchEngaged

app = FastAPI(
    title="ProofOS API",
    version="1.0.0",
    docs_url=None if settings.is_prod else "/docs",
    redoc_url=None if settings.is_prod else "/redoc",
    openapi_url=None if settings.is_prod else "/openapi.json",
    lifespan=lifespan,
)


class LogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        resp = await call_next(request)
        dur = (time.perf_counter() - start) * 1000
        log.info("%s %s -> %s (%.1fms)", request.method, request.url.path, resp.status_code, dur)
        if settings.apm_enabled:
            try:
                import uuid

                from app.core.db import SessionLocal
                from app.models.models import TraceSpan

                db = SessionLocal()
                try:
                    db.add(TraceSpan(trace_id=uuid.uuid4().hex[:32], span_id=uuid.uuid4().hex[:16], name=request.url.path, method=request.method, path=request.url.path, status_code=resp.status_code, duration_ms=round(dur, 2)))
                    db.commit()
                finally:
                    db.close()
            except Exception:
                pass
        return resp


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("X-XSS-Protection", "0")
        if settings.is_prod:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return resp


app.add_middleware(LogMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled %s %s: %s", request.method, request.url.path, exc)
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=500, content={"ok": False, "error": "internal"})


@app.exception_handler(KillSwitchEngaged)
async def kill_switch_handler(request: Request, exc: Exception):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=409, content={"ok": False, "error": str(exc)})


@app.get("/health")
def health():
    db_ok = check_db()
    # Body and HTTP status must agree (no ok:true + 503).
    if db_ok:
        return {"ok": True, "status": "ok", "platform": "ProofOS", "version": "1.0.0", "db": "ok"}
    from fastapi import Response

    return Response(
        content='{"ok": false, "status": "degraded", "platform": "ProofOS", "version": "1.0.0", "db": "unreachable"}',
        status_code=503,
        media_type="application/json",
    )


@app.get("/")
def root():
    return {
        "service": "proofos-api",
        "version": "1.0.0",
        "docs": "/docs",
        "proof": "GET /v1/proof",
        "verify": "GET /v1/proof/verify/{id}",
        "chain": "GET /v1/proof/chain",
        "ai": "POST /v1/ai/ask",
        "auth": "POST /v1/auth/bootstrap",
    }


@app.get("/.well-known/agent.json")
def agent_card():
    """A2A agent card (discovery for MCP / A2A clients)."""
    return {
        "name": "ProofOS",
        "description": "Autonomous IT operations platform with proof-verified actions (Detect · Decide · Do · Prove).",
        "version": "1.0.0",
        "capabilities": {"mcp": True, "a2a": True, "streaming": True},
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "endpoints": {"mcp_tools": "/v1/mcp/tools", "events": "/v1/ws/events", "health": "/health"},
    }


@app.websocket("/v1/ws/events")
async def ws_events(ws: WebSocket):
    token = ws.query_params.get("token", "")
    org_id = None
    try:
        claims = decode_token(token)
        org_id = claims.get("org_id")
        if not isinstance(org_id, int) or org_id < 1 or not claims.get("sub"):
            raise ValueError("missing user or organization claim")
    except Exception:
        await ws.close(code=1008)
        return
    await ws.accept()
    _ws_subscribers[ws] = org_id
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        _ws_subscribers.pop(ws, None)


app.include_router(auth.router, prefix="/v1/auth", tags=["auth"])
app.include_router(proof.router, prefix="/v1/proof", tags=["proof"])
app.include_router(devices.router, prefix="/v1/devices", tags=["devices"])
app.include_router(tickets.router, prefix="/v1/tickets", tags=["tickets"])
app.include_router(scripts.router, prefix="/v1/scripts", tags=["scripts"])
app.include_router(automations.router, prefix="/v1/automations", tags=["automations"])
app.include_router(monitor.router, prefix="/v1/monitor", tags=["monitor"])
app.include_router(ai.router, prefix="/v1/ai", tags=["ai"])
app.include_router(approvals.router, prefix="/v1/approvals", tags=["approvals"])
app.include_router(audits.router, prefix="/v1/audits", tags=["audits"])
app.include_router(onboarding.router, prefix="/v1/onboarding", tags=["onboarding"])
app.include_router(consulting.router, prefix="/v1/consulting", tags=["consulting"])
app.include_router(cmdb.router, prefix="/v1/cmdb", tags=["cmdb"])
app.include_router(knowledge.router, prefix="/v1/knowledge", tags=["knowledge"])
app.include_router(secrets.router, prefix="/v1/secrets", tags=["secrets"])
app.include_router(time_tracking.router, prefix="/v1/time", tags=["time"])
app.include_router(vms.router, prefix="/v1/vms", tags=["vms"])
app.include_router(remote.router, prefix="/v1/remote", tags=["remote"])
app.include_router(patches.router, prefix="/v1/patches", tags=["patches"])
app.include_router(push.router, prefix="/v1/push", tags=["push"])
app.include_router(sso.router, prefix="/v1/sso", tags=["sso"])
app.include_router(ops.router, prefix="/v1/ops", tags=["ops"])
app.include_router(enclaves.router, prefix="/v1/enclaves", tags=["enclaves"])
app.include_router(changes.router, prefix="/v1/changes", tags=["changes"])
app.include_router(analytics.router, prefix="/v1/analytics", tags=["analytics"])
app.include_router(integrations.router, prefix="/v1/integrations", tags=["integrations"])
app.include_router(reports.router, prefix="/v1/reports", tags=["reports"])
app.include_router(search.router, prefix="/v1/search", tags=["search"])
app.include_router(investigations.router, prefix="/v1/ai", tags=["investigations"])
app.include_router(access.router, prefix="/v1/access", tags=["privileged access"])
app.include_router(recovery.router, prefix="/v1/recovery", tags=["recovery"])
app.include_router(topology.router, prefix="/v1/topology", tags=["topology"])
app.include_router(fleet.router, prefix="/v1/fleet", tags=["fleet"])
app.include_router(patching.router, prefix="/v1/patching", tags=["patching"])
app.include_router(thresholds.router, prefix="/v1/thresholds", tags=["thresholds"])
app.include_router(customers.router, prefix="/v1/customers", tags=["customers"])
app.include_router(billing.router, prefix="/v1/billing", tags=["billing"])
app.include_router(anchors.router, prefix="/v1/anchors", tags=["anchors"])
app.include_router(vulnerabilities.router, prefix="/v1/vulnerabilities", tags=["vulnerabilities"])
app.include_router(portal.router, prefix="/v1/portal", tags=["portal"])
app.include_router(slos.router, prefix="/v1/slos", tags=["slos"])
app.include_router(telemetry.router, prefix="/v1/telemetry", tags=["telemetry"])
app.include_router(itechsmart.router, prefix="/v1/itechsmart", tags=["itechsmart"])
app.include_router(mcp_registry.router, prefix="/v1/mcp", tags=["mcp"])
