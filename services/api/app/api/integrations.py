from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import secrets
import math
from typing import Literal

from fastapi import APIRouter, Depends, Query, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.proof import emit
from app.core.security import actor_of, get_current_user, SlidingWindowLimiter
from app.core.pubsub import publish
from app.models.models import Alert, IntegrationAlertLink, IntegrationConnection, IntegrationMetric
from app.schemas.schemas import IntegrationMetricOut, MetricIn

router = APIRouter()
webhook_limiter = SlidingWindowLimiter(120, 60)


class ConnectionIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    provider: Literal["metrics", "grafana", "alertmanager", "otlp", "email"]


def connection_out(row):
    received = row.last_received_at
    if received and received.tzinfo is None:
        received = received.replace(tzinfo=dt.timezone.utc)
    return {"id": row.id, "name": row.name, "provider": row.provider, "enabled": row.enabled,
        "received_count": row.received_count, "last_received_at": received,
        "created_at": row.created_at,
        "webhook_path": f"/v1/telemetry/otlp/{row.id}" if row.provider == "otlp" else f"/v1/integrations/webhooks/{row.id}"}


@router.get("/connections")
def connections(org_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, org_id)
    return [connection_out(c) for c in db.query(IntegrationConnection).filter(IntegrationConnection.org_id == org_id).order_by(IntegrationConnection.id.desc()).all()]


@router.post("/connections", status_code=201)
def create_connection(org_id: int, payload: ConnectionIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, org_id)
    if user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="admin/manager only")
    secret = secrets.token_urlsafe(32)
    row = IntegrationConnection(org_id=org_id, name=payload.name, provider=payload.provider,
        token_hash=hashlib.sha256(secret.encode()).hexdigest())
    db.add(row)
    db.commit()
    emit(db, "integration.created", {"id": row.id, "provider": row.provider}, actor_of(user), {"org_id": org_id}, {"reason": "create inbound integration"})
    return {**connection_out(row), "token": secret}


@router.post("/connections/{connection_id}/disable")
def disable_connection(connection_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    row = db.query(IntegrationConnection).filter(IntegrationConnection.id == connection_id, IntegrationConnection.org_id == user.org_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="integration not found")
    if user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="admin/manager only")
    row.enabled = False
    db.commit()
    emit(db, "integration.disabled", {"id": row.id}, actor_of(user), {"org_id": user.org_id}, {"reason": "revoke webhook credential"})
    return connection_out(row)


@router.post("/webhooks/{connection_id}", status_code=202)
async def webhook(connection_id: int, request: Request, db: Session = Depends(get_db)):
    row = db.query(IntegrationConnection).filter(IntegrationConnection.id == connection_id, IntegrationConnection.enabled.is_(True)).first()
    authorization = request.headers.get("authorization", "")
    bearer = authorization[7:] if authorization.lower().startswith("bearer ") else ""
    token = request.headers.get("x-integration-token", "") or bearer
    if not row or not token or not hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), row.token_hash):
        raise HTTPException(status_code=401, detail="invalid integration credential")
    if row.provider == "otlp":
        raise HTTPException(status_code=400, detail="OTLP connections receive data at /v1/telemetry/otlp/{id}/v1/logs or /v1/traces")
    if not webhook_limiter.allow(str(row.id)):
        raise HTTPException(status_code=429, detail="integration rate limit exceeded")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 262144:
            raise HTTPException(status_code=413, detail="webhook exceeds 256 KiB")
    import json
    if row.provider == "email":
        return _inbound_email(db, row, bytes(body), request.headers.get("content-type", ""))
    try:
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError("object required")
        items = data.get("metrics" if row.provider == "metrics" else "alerts")
        if not isinstance(items, list) or not 1 <= len(items) <= 200:
            raise ValueError("provide 1–200 metrics or alerts")
        records = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("each item must be an object")
            if row.provider == "metrics":
                value = float(item["value"])
                if not math.isfinite(value) or not str(item.get("name", "")).strip():
                    raise ValueError("finite value and metric name required")
                records.append(IntegrationMetric(org_id=row.org_id, source=row.name, name=str(item["name"])[:255],
                    value=value, host=str(item.get("host", ""))[:255]))
            else:
                labels, annotations = item.get("labels", {}), item.get("annotations", {})
                if not isinstance(labels, dict) or not isinstance(annotations, dict):
                    raise ValueError("labels and annotations must be objects")
                title = annotations.get("summary") or labels.get("alertname") or "External alert"
                severity = str(labels.get("severity", "warning")).lower()
                severity = "critical" if severity in {"critical", "high", "p1"} else "warning" if severity in {"warning", "warn", "medium"} else "info"
                resolved = item.get("status", data.get("status")) == "resolved"
                external_key = hashlib.sha256(json.dumps(labels, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                records.append({"external_key": external_key, "severity": severity, "resolved": resolved,
                    "message": f"[{row.name}] {title} · {annotations.get('description', '')}"[:4000]})
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise HTTPException(status_code=422, detail="invalid webhook payload; expected named finite metrics or alerts with labels/annotations") from exc
    # Serialize deliveries for one connection so retries cannot create duplicate alerts.
    db.query(IntegrationConnection).filter(IntegrationConnection.id == row.id).with_for_update().first()
    for record in records:
        if row.provider == "metrics":
            db.add(record)
            continue
        link = db.query(IntegrationAlertLink).filter(IntegrationAlertLink.connection_id == row.id,
            IntegrationAlertLink.external_key == record["external_key"]).first()
        alert = db.get(Alert, link.alert_id) if link else None
        if not alert:
            alert = Alert(org_id=row.org_id, kind=row.provider)
            db.add(alert)
            db.flush()
            link = IntegrationAlertLink(org_id=row.org_id, connection_id=row.id,
                external_key=record["external_key"], alert_id=alert.id, status="new")
            db.add(link)
        alert.severity = record["severity"]
        alert.message = record["message"]
        if record["resolved"]:
            alert.acked = True
        elif link.status in {"new", "resolved"}:
            alert.acked = False
        link.status = "resolved" if record["resolved"] else "firing"
        db.flush()
    # Atomic increment also preserves counters with concurrent deliveries.
    db.query(IntegrationConnection).filter(IntegrationConnection.id == row.id).update({
        IntegrationConnection.received_count: IntegrationConnection.received_count + 1,
        IntegrationConnection.last_received_at: dt.datetime.now(dt.timezone.utc)})
    db.commit()
    emit(db, "integration.webhook.received", {"id": row.id, "provider": row.provider, "records": len(records)},
        {"actor_id": f"integration:{row.id}", "actor_type": "integration"}, {"org_id": row.org_id}, {"reason": "authenticated webhook delivery"})
    publish({"type": "integration", "org_id": row.org_id})
    return {"accepted": len(records)}


def _inbound_email(db: Session, row: IntegrationConnection, body: bytes, content_type: str) -> dict:
    """Inbound mail parse webhook: JSON (Postmark, generic) or form-encoded (Mailgun, SendGrid)."""
    import json
    from urllib.parse import parse_qs

    from app.services import inbound_email

    try:
        if "application/x-www-form-urlencoded" in content_type:
            data = {k: v[0] for k, v in parse_qs(body.decode("utf-8"), keep_blank_values=True).items()}
        else:
            data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError("object required")
        result = inbound_email.ingest(db, row, data)
    except (ValueError, TypeError, UnicodeDecodeError) as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=f"invalid inbound email: {exc}") from exc
    db.query(IntegrationConnection).filter(IntegrationConnection.id == row.id).update({
        IntegrationConnection.received_count: IntegrationConnection.received_count + 1,
        IntegrationConnection.last_received_at: dt.datetime.now(dt.timezone.utc)})
    db.commit()
    if result["action"] != "duplicate":
        emit(db, f"ticket.email.{result['action']}", {k: v for k, v in result.items() if k != "action"},
            {"actor_id": f"integration:{row.id}", "actor_type": "integration"}, {"org_id": row.org_id, "ticket_id": result["ticket_id"]},
            {"reason": "inbound customer email"})
        publish({"type": "ticket", "org_id": row.org_id})
    if result["action"] == "created":
        from app.services.automation_engine import evaluate

        evaluate(db, row.org_id, "ticket.opened", {"ticket_id": result["ticket_id"], "priority": "normal", "status": "open"})
    return result


def _scope(user, org_id: int) -> None:
    if user.org_id != org_id:
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="org scope mismatch")


@router.post("/metrics", status_code=201)
def ingest_metrics(payload: MetricIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Ingest metrics from Datadog/Prometheus/Grafana (generic webhook)."""
    _scope(user, payload.org_id)
    records = []
    for m in payload.metrics:
        try:
            value = float(m.get("value", 0))
            if not math.isfinite(value):
                raise ValueError("finite value required")
        except (ValueError, TypeError, OverflowError) as exc:
            raise HTTPException(status_code=422, detail="metrics require finite numeric values") from exc
        records.append(
            IntegrationMetric(
                org_id=payload.org_id,
                source=payload.source,
                name=str(m.get("name", "metric"))[:255],
                value=value,
                host=payload.host or str(m.get("host", ""))[:255],
            )
        )
    count = len(records)
    db.add_all(records)
    db.commit()
    emit(db, "integration.metrics.ingested", {"source": payload.source, "count": count}, actor_of(user), {"org_id": payload.org_id}, {"reason": "metrics webhook"})
    return {"ingested": count}


@router.get("/metrics", response_model=list[IntegrationMetricOut])
def list_metrics(org_id: int, source: str | None = None, limit: int = Query(200, le=1000), db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, org_id)
    q = db.query(IntegrationMetric).filter(IntegrationMetric.org_id == org_id)
    if source:
        q = q.filter(IntegrationMetric.source == source)
    return q.order_by(IntegrationMetric.created_at.desc()).limit(limit).all()
