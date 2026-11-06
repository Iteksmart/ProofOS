from __future__ import annotations

import hashlib
import secrets as _secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.proof import emit
from app.core.pubsub import publish
from app.core.security import actor_of, get_current_user, require_agent
from app.models.models import Device, DeviceMetric, Org
from app.schemas.schemas import CommandIn, DeviceCreate, DeviceCreateOut, DeviceHeartbeat, DeviceMetricOut, DeviceOut
from app.services.execution import queue_command

router = APIRouter()

VALID_STATUS = {"online", "offline", "stale", "maintenance", "unknown"}


def _scope_check(db: Session, user, org_id: int) -> None:
    if user.org_id != org_id:
        raise HTTPException(status_code=403, detail="org scope mismatch")


@router.get("", response_model=list[DeviceOut])
def list_devices(
    org_id: int,
    status: str | None = None,
    q: str | None = None,
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _scope_check(db, user, org_id)
    query = db.query(Device).filter(Device.org_id == org_id)
    if status:
        query = query.filter(Device.status == status)
    if q:
        query = query.filter(Device.hostname.ilike(f"%{q}%"))
    return query.limit(limit).all()


@router.get("/{device_id}", response_model=DeviceOut)
def get_device(device_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    dev = db.query(Device).filter(Device.id == device_id).first()
    if not dev:
        raise HTTPException(status_code=404, detail="device not found")
    _scope_check(db, user, dev.org_id)
    return dev


@router.post("", response_model=DeviceCreateOut, status_code=201)
def create_device(payload: DeviceCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope_check(db, user, payload.org_id)
    org = db.query(Org).filter(Org.id == payload.org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="org not found")
    secret = _secrets.token_urlsafe(24)
    dev = Device(
        org_id=payload.org_id,
        hostname=payload.hostname,
        os=payload.os,
        ip=payload.ip,
        device_type=payload.device_type,
        secret_hash=hashlib.sha256(secret.encode()).hexdigest(),
    )
    db.add(dev)
    db.commit()
    db.refresh(dev)
    emit(
        db,
        "device.created",
        {"hostname": dev.hostname, "id": dev.id},
        actor_of(user),
        {"org_id": payload.org_id, "device_id": dev.id},
        {"reason": "manual register"},
    )
    return DeviceCreateOut(
        id=dev.id,
        org_id=dev.org_id,
        hostname=dev.hostname,
        os=dev.os,
        ip=dev.ip,
        device_type=dev.device_type,
        status=dev.status,
        cpu=dev.cpu,
        disk=dev.disk,
        mem=dev.mem,
        agent_version=dev.agent_version,
        last_seen=dev.last_seen,
        device_secret=secret,
    )


@router.post("/{device_id}/command")
def run_command(device_id: int, payload: CommandIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Run a shell command on a device via its agent (admin/manager, proof-logged)."""
    if user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="admin/manager only")
    dev = db.query(Device).filter(Device.id == device_id).first()
    if not dev:
        raise HTTPException(status_code=404, detail="device not found")
    _scope_check(db, user, dev.org_id)
    run = queue_command(db, dev.org_id, device_id, payload.body, actor_of(user))
    return {"run_id": run.id, "device_id": device_id, "status": "queued"}


@router.post("/refresh-status")
def refresh_status(db: Session = Depends(get_db), user=Depends(get_current_user), org_id: int = 0):
    """Recalculate device online/stale/offline states and raise alerts (admin)."""
    org_id = org_id or user.org_id
    _scope_check(db, user, org_id)
    from app.services.status_sync import sync_device_statuses

    result = sync_device_statuses(db, org_id)
    emit(db, "device.status.sync", {"org_id": org_id, **result}, actor_of(user), {"org_id": org_id}, {"reason": "status refresh"})
    return result


@router.post("/{device_id}/rotate-secret")
def rotate_secret(device_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Regenerate the one-time agent secret for re-enrollment (admin/manager)."""
    if user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="admin/manager only")
    dev = db.query(Device).filter(Device.id == device_id).first()
    if not dev:
        raise HTTPException(status_code=404, detail="device not found")
    _scope_check(db, user, dev.org_id)
    secret = _secrets.token_urlsafe(24)
    dev.secret_hash = hashlib.sha256(secret.encode()).hexdigest()
    db.commit()
    db.refresh(dev)
    emit(db, "device.secret.rotated", {"device_id": dev.id}, actor_of(user), {"org_id": dev.org_id, "device_id": dev.id}, {"reason": "re-enrollment"})
    return {"device_id": dev.id, "device_secret": secret}


@router.delete("/{device_id}", status_code=204)
def delete_device(device_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="admin/manager only")
    dev = db.query(Device).filter(Device.id == device_id).first()
    if not dev:
        raise HTTPException(status_code=404, detail="device not found")
    emit(
        db,
        "device.deleted",
        {"hostname": dev.hostname, "id": dev.id},
        actor_of(user),
        {"org_id": dev.org_id, "device_id": dev.id},
        {"reason": "manual delete"},
    )
    db.delete(dev)
    db.commit()


@router.post("/{device_id}/heartbeat")
def heartbeat(device_id: int, payload: DeviceHeartbeat, db: Session = Depends(get_db), agent: None = Depends(require_agent)):
    """Agent endpoint — authenticated via AGENT_TOKEN (X-Agent-Token / Bearer)."""
    dev = db.query(Device).filter(Device.id == device_id).first()
    if not dev:
        raise HTTPException(status_code=404, detail="device not found")
    if payload.status not in VALID_STATUS:
        payload.status = "online"
    dev.cpu = float(payload.cpu or 0)
    dev.disk = float(payload.disk or 0)
    dev.mem = float(payload.mem or 0)
    dev.status = payload.status
    if payload.agent_version:
        dev.agent_version = payload.agent_version
    dev.last_seen = datetime.now(timezone.utc)
    db.add(DeviceMetric(org_id=dev.org_id, device_id=dev.id, cpu=dev.cpu, disk=dev.disk, mem=dev.mem))
    db.commit()
    db.refresh(dev)
    publish({"type": "device", "device_id": dev.id, "hostname": dev.hostname, "status": dev.status, "org_id": dev.org_id})
    return {"ok": True, "device_id": dev.id, "status": dev.status}


@router.get("/{device_id}/metrics", response_model=list[DeviceMetricOut])
def device_metrics(device_id: int, limit: int = Query(50, le=500), db: Session = Depends(get_db), user=Depends(get_current_user)):
    dev = db.query(Device).filter(Device.id == device_id).first()
    if not dev:
        raise HTTPException(status_code=404, detail="device not found")
    _scope_check(db, user, dev.org_id)
    return (
        db.query(DeviceMetric)
        .filter(DeviceMetric.device_id == device_id)
        .order_by(DeviceMetric.created_at.desc())
        .limit(limit)
        .all()
    )
