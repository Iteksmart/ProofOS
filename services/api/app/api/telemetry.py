"""OpenTelemetry (OTLP/JSON) log and trace ingestion, query, and trace-derived topology."""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.proof import emit
from app.core.security import SlidingWindowLimiter, get_current_user
from app.models.models import IntegrationConnection, TelemetryEvent
from app.services import topology
from app.services.dlp import PATTERNS

router = APIRouter()
ingest_limiter = SlidingWindowLimiter(240, 60)

MAX_BODY_BYTES = 1_048_576
MAX_RECORDS = 1000
RETENTION = dt.timedelta(days=7)
_HEX = re.compile(r"^[0-9a-f]+$")
_ERRORS = {"ERROR", "FATAL", "CRITICAL"}
_CREDENTIAL_PATTERNS = {"aws_access_key", "google_api_key", "private_key", "generic_secret"}
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}")


def redact(text: str) -> str:
    """Mask credential-shaped values before storage so they never reach search or AI context."""
    for name, pattern, _severity in PATTERNS:
        if name in _CREDENTIAL_PATTERNS:
            text = re.sub(pattern, f"[redacted:{name}]", text)
    return _BEARER.sub("[redacted:bearer_token]", text)


def _value(raw) -> str:
    if not isinstance(raw, dict):
        return str(raw)
    for key in ("stringValue", "intValue", "doubleValue", "boolValue"):
        if key in raw:
            return str(raw[key])
    return json.dumps(raw)[:500]


def _attributes(items) -> dict[str, str]:
    out: dict[str, str] = {}
    if isinstance(items, list):
        for item in items[:40]:
            if isinstance(item, dict) and isinstance(item.get("key"), str):
                out[item["key"][:120]] = redact(_value(item.get("value")))[:500]
    return out


def _hex_id(raw, length: int) -> str:
    value = str(raw or "").lower()
    return value if len(value) == length and _HEX.match(value) and set(value) != {"0"} else ""


def _time(raw) -> dt.datetime:
    try:
        nanos = int(raw)
        if nanos <= 0:
            raise ValueError
        return dt.datetime.fromtimestamp(nanos / 1e9, tz=dt.timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return dt.datetime.now(dt.timezone.utc)


def _log_severity(record: dict) -> str:
    text = str(record.get("severityText") or "").upper()
    if text:
        return text[:30]
    try:
        number = int(record.get("severityNumber") or 0)
    except (TypeError, ValueError):
        number = 0
    return "FATAL" if number >= 21 else "ERROR" if number >= 17 else "WARN" if number >= 13 else "INFO" if number >= 9 else "DEBUG"


def _service(resource) -> str:
    attrs = _attributes((resource or {}).get("attributes")) if isinstance(resource, dict) else {}
    return (attrs.get("service.name") or "unknown-service")[:255]


def _parse_logs(data: dict) -> list[dict]:
    rows = []
    for resource in data.get("resourceLogs") or []:
        service = _service(resource.get("resource"))
        for scope in resource.get("scopeLogs") or []:
            for record in scope.get("logRecords") or []:
                if not isinstance(record, dict):
                    raise ValueError("log records must be objects")
                rows.append({"kind": "log", "service": service, "trace_id": _hex_id(record.get("traceId"), 32),
                    "span_id": _hex_id(record.get("spanId"), 16), "parent_span_id": "", "name": "",
                    "severity": _log_severity(record), "body": redact(_value(record.get("body")))[:4000], "duration_ms": 0.0,
                    "attributes": _attributes(record.get("attributes")), "observed_at": _time(record.get("timeUnixNano") or record.get("observedTimeUnixNano"))})
    return rows


def _parse_spans(data: dict) -> list[dict]:
    rows = []
    for resource in data.get("resourceSpans") or []:
        service = _service(resource.get("resource"))
        for scope in resource.get("scopeSpans") or []:
            for span in scope.get("spans") or []:
                if not isinstance(span, dict):
                    raise ValueError("spans must be objects")
                trace_id, span_id = _hex_id(span.get("traceId"), 32), _hex_id(span.get("spanId"), 16)
                if not trace_id or not span_id:
                    raise ValueError("spans require hex traceId (32) and spanId (16)")
                start, end = _time(span.get("startTimeUnixNano")), _time(span.get("endTimeUnixNano"))
                status = span.get("status") if isinstance(span.get("status"), dict) else {}
                failed = status.get("code") in (2, "2", "STATUS_CODE_ERROR")
                rows.append({"kind": "span", "service": service, "trace_id": trace_id, "span_id": span_id,
                    "parent_span_id": _hex_id(span.get("parentSpanId"), 16), "name": str(span.get("name") or "")[:255],
                    "severity": "ERROR" if failed else "OK", "body": redact(str(status.get("message") or ""))[:4000],
                    "duration_ms": round(max(0.0, (end - start).total_seconds() * 1000), 3),
                    "attributes": _attributes(span.get("attributes")), "observed_at": start})
    return rows


async def _ingest(connection_id: int, request: Request, db: Session, parser, root_key: str) -> dict:
    row = db.query(IntegrationConnection).filter(IntegrationConnection.id == connection_id,
        IntegrationConnection.enabled.is_(True), IntegrationConnection.provider == "otlp").first()
    authorization = request.headers.get("authorization", "")
    bearer = authorization[7:] if authorization.lower().startswith("bearer ") else ""
    token = request.headers.get("x-integration-token", "") or bearer
    if not row or not token or not hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), row.token_hash):
        raise HTTPException(status_code=401, detail="invalid integration credential")
    if not ingest_limiter.allow(str(row.id)):
        raise HTTPException(status_code=429, detail="telemetry rate limit exceeded")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="telemetry batch exceeds 1 MiB")
    try:
        data = json.loads(body)
        if not isinstance(data, dict) or not isinstance(data.get(root_key), list):
            raise ValueError(f"OTLP/JSON object with {root_key} required")
        rows = parser(data)
        if not 1 <= len(rows) <= MAX_RECORDS:
            raise ValueError(f"provide 1–{MAX_RECORDS} records per batch")
    except (ValueError, TypeError, AttributeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=f"invalid OTLP/JSON payload: {exc}") from exc

    org_id, connection_name = row.org_id, row.name
    now = dt.datetime.now(dt.timezone.utc)
    for item in rows:
        db.add(TelemetryEvent(org_id=org_id, received_at=now, **{**item, "attributes": json.dumps(item["attributes"])}))
    new_edges: list[dict] = []
    if root_key == "resourceSpans":
        owners = {(r["trace_id"], r["span_id"]): r["service"] for r in rows}
        missing = {(r["trace_id"], r["parent_span_id"]) for r in rows if r["parent_span_id"]} - set(owners)
        if missing:
            trace_ids = {trace_id for trace_id, _ in missing}
            for trace_id, span_id, service in db.query(TelemetryEvent.trace_id, TelemetryEvent.span_id, TelemetryEvent.service).filter(
                    TelemetryEvent.org_id == org_id, TelemetryEvent.kind == "span", TelemetryEvent.trace_id.in_(trace_ids)).all():
                owners.setdefault((trace_id, span_id), service)
        for item in rows:
            parent = owners.get((item["trace_id"], item["parent_span_id"])) if item["parent_span_id"] else None
            if parent and parent != item["service"] and topology.observe_edge(db, org_id, parent, item["service"]):
                new_edges.append({"source": parent, "target": item["service"]})
        for service in {r["service"] for r in rows}:
            topology.get_or_create_node(db, org_id, service)
    row.received_count += len(rows)
    row.last_received_at = now
    db.query(TelemetryEvent).filter(TelemetryEvent.org_id == org_id, TelemetryEvent.received_at < now - RETENTION).delete(synchronize_session=False)
    db.commit()
    for edge in new_edges:
        emit(db, "topology.dependency.observed", {**edge, "origin": "trace"}, {"actor_id": f"integration:{connection_id}", "actor_type": "integration"},
            {"org_id": org_id}, {"reason": f"parent/child spans received via {connection_name}"})
    return {"accepted": len(rows), "new_dependencies": new_edges}


@router.post("/otlp/{connection_id}/v1/logs", status_code=202)
async def ingest_logs(connection_id: int, request: Request, db: Session = Depends(get_db)):
    return await _ingest(connection_id, request, db, _parse_logs, "resourceLogs")


@router.post("/otlp/{connection_id}/v1/traces", status_code=202)
async def ingest_traces(connection_id: int, request: Request, db: Session = Depends(get_db)):
    return await _ingest(connection_id, request, db, _parse_spans, "resourceSpans")


def _out(row: TelemetryEvent) -> dict:
    try:
        attributes = json.loads(row.attributes or "{}")
    except json.JSONDecodeError:
        attributes = {}
    return {"id": row.id, "kind": row.kind, "service": row.service, "trace_id": row.trace_id, "span_id": row.span_id,
        "parent_span_id": row.parent_span_id, "name": row.name, "severity": row.severity, "body": row.body,
        "duration_ms": row.duration_ms, "attributes": attributes, "observed_at": row.observed_at, "received_at": row.received_at}


@router.get("/events")
def events(kind: str | None = Query(None, pattern="^(log|span)$"), service: str | None = Query(None, max_length=255),
        severity: str | None = Query(None, max_length=30), q: str | None = Query(None, max_length=200),
        trace_id: str | None = Query(None, max_length=32), limit: int = Query(100, ge=1, le=500),
        db: Session = Depends(get_db), user=Depends(get_current_user)):
    query = db.query(TelemetryEvent).filter(TelemetryEvent.org_id == user.org_id)
    if kind:
        query = query.filter(TelemetryEvent.kind == kind)
    if service:
        query = query.filter(TelemetryEvent.service == service)
    if severity == "errors":
        query = query.filter(TelemetryEvent.severity.in_(_ERRORS))
    elif severity:
        query = query.filter(TelemetryEvent.severity == severity.upper())
    if trace_id:
        query = query.filter(TelemetryEvent.trace_id == trace_id.lower())
    if q:
        needle = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.filter(TelemetryEvent.body.ilike(needle, escape="\\") | TelemetryEvent.name.ilike(needle, escape="\\"))
    return [_out(r) for r in query.order_by(TelemetryEvent.observed_at.desc(), TelemetryEvent.id.desc()).limit(limit).all()]


@router.get("/services")
def services(minutes: int = Query(60, ge=5, le=1440), db: Session = Depends(get_db), user=Depends(get_current_user)):
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutes)
    rows = db.query(TelemetryEvent.service, TelemetryEvent.kind, TelemetryEvent.severity, TelemetryEvent.duration_ms, TelemetryEvent.received_at).filter(
        TelemetryEvent.org_id == user.org_id, TelemetryEvent.received_at >= since).all()
    stats: dict[str, dict] = {}
    for service, kind, severity, duration, received in rows:
        s = stats.setdefault(service, {"service": service, "spans": 0, "span_errors": 0, "logs": 0, "log_errors": 0, "durations": [], "last_received_at": received})
        failed = (severity or "").upper() in _ERRORS
        if kind == "span":
            s["spans"] += 1
            s["span_errors"] += failed
            s["durations"].append(duration or 0.0)
        else:
            s["logs"] += 1
            s["log_errors"] += failed
        if received and received > s["last_received_at"]:
            s["last_received_at"] = received
    out = []
    for s in stats.values():
        durations = sorted(s.pop("durations"))
        s["p95_ms"] = round(durations[min(len(durations) - 1, int(len(durations) * 0.95))], 2) if durations else None
        s["error_rate"] = round(s["span_errors"] / s["spans"], 4) if s["spans"] else None
        out.append(s)
    return {"window_minutes": minutes, "services": sorted(out, key=lambda s: s["service"])}


@router.get("/traces/{trace_id}")
def trace(trace_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    trace_id = trace_id.lower()
    if not _hex_id(trace_id, 32):
        raise HTTPException(status_code=422, detail="trace id must be 32 hex characters")
    rows = db.query(TelemetryEvent).filter(TelemetryEvent.org_id == user.org_id, TelemetryEvent.trace_id == trace_id).order_by(
        TelemetryEvent.observed_at.asc(), TelemetryEvent.id.asc()).limit(1000).all()
    if not rows:
        raise HTTPException(status_code=404, detail="trace not found in organization")
    return {"trace_id": trace_id, "spans": [_out(r) for r in rows if r.kind == "span"], "logs": [_out(r) for r in rows if r.kind == "log"]}
