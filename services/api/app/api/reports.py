"""Tenant scoped operational reports and spreadsheet-safe CSV exports."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import get_current_user
from app.models.models import Alert, Device, DeviceInventory, IntegrationConnection, Patch, ScriptRun, Ticket

router = APIRouter()
CLOSED = {"resolved", "closed", "cancelled"}


def scope(user, org_id):
    if user.org_id != org_id:
        raise HTTPException(status_code=403, detail="org scope mismatch")


def counts(db, model, field, org_id):
    return dict(db.query(field, func.count(model.id)).filter(model.org_id == org_id).group_by(field).all())


@router.get("/operations")
def operations(org_id: int, days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db), user=Depends(get_current_user)):
    scope(user, org_id)
    now = datetime.now(timezone.utc)
    # Use the same UTC calendar boundaries for totals and chart buckets, including
    # today. A rolling-hour total would otherwise include an uncharted partial day.
    since = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
    def total(model, *conditions):
        return db.query(func.count(model.id)).filter(model.org_id == org_id, *conditions).scalar() or 0
    device_status = counts(db, Device, Device.status, org_id)
    patch_status = counts(db, Patch, Patch.status, org_id)
    ticket_status = counts(db, Ticket, Ticket.status, org_id)
    ticket_query = db.query(Ticket).filter(Ticket.org_id == org_id, Ticket.created_at >= since)
    created = ticket_query.count()
    completed = ticket_query.filter(Ticket.status.in_({"resolved", "closed"})).count()
    # Fixed buckets let empty dates render as zero, without fabricating activity.
    buckets = {(since + timedelta(days=i)).date().isoformat(): 0 for i in range(days)}
    for day, count in db.query(func.date(Ticket.created_at), func.count(Ticket.id)).filter(Ticket.org_id == org_id, Ticket.created_at >= since).group_by(func.date(Ticket.created_at)).all():
        key = str(day)
        if key in buckets:
            buckets[key] = count
    return {"generated_at": now, "days": days,
        "devices": {"total": sum(device_status.values()), "by_status": device_status,
            "by_os": counts(db, Device, Device.os, org_id),
            "with_inventory": total(DeviceInventory),
            "fresh_inventory": total(DeviceInventory, DeviceInventory.collected_at >= now - timedelta(hours=24))},
        "tickets": {"by_status": ticket_status, "open": sum(v for k, v in ticket_status.items() if k not in CLOSED),
            "overdue": total(Ticket, Ticket.status.notin_(CLOSED), Ticket.due_at < now),
            "created_in_period": created, "resolved_in_cohort": completed,
            "resolution_rate": round(completed / created * 100, 1) if created else None,
            "daily_created": [{"date": k, "count": v} for k, v in buckets.items()]},
        "patches": {"total": sum(patch_status.values()), "by_status": patch_status,
            "critical_pending": total(Patch, Patch.severity == "critical", Patch.status.in_(["pending", "failed"]))},
        "alerts": {"unacknowledged": total(Alert, Alert.acked.is_(False)),
            "critical": total(Alert, Alert.acked.is_(False), Alert.severity == "critical")},
        "execution": {"completed": total(ScriptRun, ScriptRun.completed_at >= since),
            "failed": total(ScriptRun, ScriptRun.completed_at >= since, ScriptRun.exit_code != 0)},
        "integrations": {"configured": total(IntegrationConnection), "enabled": total(IntegrationConnection, IntegrationConnection.enabled.is_(True)),
            "receiving": total(IntegrationConnection, IntegrationConnection.enabled.is_(True), IntegrationConnection.last_received_at >= now - timedelta(hours=24))}}


def safe_cell(value):
    text = "" if value is None else str(value)
    # Quoting alone does not prevent formulas from executing in spreadsheet apps.
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")) else text


@router.get("/export")
def export(org_id: int, kind: Literal["devices", "tickets", "patches", "integrations", "software"], db: Session = Depends(get_db), user=Depends(get_current_user)):
    scope(user, org_id)
    models = {
        "devices": (Device, ["id", "hostname", "device_type", "os", "ip", "status", "agent_version", "last_seen"]),
        "tickets": (Ticket, ["id", "title", "status", "priority", "severity", "assignee", "device_id", "due_at", "created_at"]),
        "patches": (Patch, ["id", "device_id", "name", "category", "current_version", "available_version", "severity", "status"]),
        "integrations": (IntegrationConnection, ["id", "name", "provider", "enabled", "received_count", "last_received_at"]),
    }
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    if kind == "software":
        writer.writerow(["device_id", "hostname", "name", "version", "publisher", "collected_at"])
        for snapshot, device in db.query(DeviceInventory, Device).join(Device, Device.id == DeviceInventory.device_id).filter(DeviceInventory.org_id == org_id).yield_per(100):
            for package in json.loads(snapshot.payload).get("software", []):
                writer.writerow([safe_cell(v) for v in [device.id, device.hostname, package["name"], package.get("version"), package.get("publisher"), snapshot.collected_at]])
    else:
        model, fields = models[kind]
        writer.writerow(fields)
        for row in db.query(model).filter(model.org_id == org_id).order_by(model.id).yield_per(500):
            writer.writerow([safe_cell(getattr(row, name)) for name in fields])
    return Response("\ufeff" + output.getvalue(), media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="proofos-{kind}.csv"', "Cache-Control": "no-store"})
