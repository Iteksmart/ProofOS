from __future__ import annotations

import hashlib
import json
import secrets as _secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.proof import emit
from app.core.pubsub import publish
from app.core.security import actor_of, agent_actor, get_current_user, require_agent
from app.models.models import Device, DeviceInventory, DeviceMetric, Org, Script, ScriptRun
from app.schemas.inventory import InventoryIn
from app.schemas.schemas import CommandIn, DeviceCreate, DeviceCreateOut, DeviceHeartbeat, DeviceMetricOut, DeviceOut
from app.services.execution import queue_command
from app.services.privileged import authorize

router = APIRouter()

VALID_STATUS = {"online", "offline", "stale", "maintenance", "unknown"}


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


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


@router.get("/inventory")
def inventory_overview(org_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope_check(db, user, org_id)
    snapshots = {s.device_id: s for s in db.query(DeviceInventory).filter(DeviceInventory.org_id == org_id).all()}
    rows = []
    for dev in db.query(Device).filter(Device.org_id == org_id).order_by(Device.hostname).all():
        snap = snapshots.get(dev.id)
        data = json.loads(snap.payload) if snap else {}
        rows.append({"device_id": dev.id, "hostname": dev.hostname, "os": data.get("os") or dev.os,
            "status": dev.status, "agent_version": dev.agent_version,
            "hardware": data.get("hardware", {}), "software_count": len(data.get("software", [])),
            "software_status": data.get("software_status", "unavailable"),
            "collected_at": _utc(snap.collected_at) if snap else None})
    return rows


@router.get("/software")
def software_inventory(org_id: int, q: str = Query("", max_length=100), db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope_check(db, user, org_id)
    groups = {}
    for snap, dev in db.query(DeviceInventory, Device).join(Device, Device.id == DeviceInventory.device_id).filter(DeviceInventory.org_id == org_id).all():
        for package in json.loads(snap.payload).get("software", []):
            if q.lower() not in f"{package['name']} {package.get('version', '')} {package.get('publisher', '')}".lower():
                continue
            key = (package["name"], package.get("version", ""), package.get("publisher", ""))
            group = groups.setdefault(key, {**package, "devices": []})
            group["devices"].append({"id": dev.id, "hostname": dev.hostname})
    rows = sorted(groups.values(), key=lambda r: (-len(r["devices"]), r["name"].lower()))
    return {"total": len(rows), "items": rows[:200]}


@router.get("/{device_id}/activity")
def device_activity(device_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    dev = get_device(device_id, db, user)
    rows = db.query(ScriptRun, Script).join(Script, Script.id == ScriptRun.script_id).filter(
        ScriptRun.device_id == dev.id, ScriptRun.org_id == dev.org_id).order_by(ScriptRun.id.desc()).limit(25).all()
    return [{"id": r.id, "name": script.name, "status": "failed" if r.exit_code not in (None, 0) else r.status,
        "created_at": _utc(r.created_at), "completed_at": _utc(r.completed_at), "exit_code": r.exit_code, "output": r.output} for r, script in rows]


@router.get("/{device_id}/inventory")
def get_inventory(device_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    dev = get_device(device_id, db, user)
    snap = db.query(DeviceInventory).filter(DeviceInventory.device_id == dev.id).first()
    return {"device_id": dev.id, "collected_at": _utc(snap.collected_at) if snap else None,
        "inventory": json.loads(snap.payload) if snap else None}


@router.post("/{device_id}/inventory")
def receive_inventory(device_id: int, payload: InventoryIn, db: Session = Depends(get_db), agent: None = Depends(require_agent)):
    dev = db.query(Device).filter(Device.id == device_id).with_for_update().first()
    if not dev:
        raise HTTPException(status_code=404, detail="device not found")
    snap = db.query(DeviceInventory).filter(DeviceInventory.device_id == device_id).first()
    if not snap:
        snap = DeviceInventory(org_id=dev.org_id, device_id=device_id)
        db.add(snap)
    old = json.loads(snap.payload or "{}")
    previous = {(p["name"], p.get("version", "")) for p in old.get("software", [])}
    current = {(p.name, p.version) for p in payload.software}
    drift = {"added": len(current - previous), "removed": len(previous - current)} if old.get("software_status") == "complete" and payload.software_status == "complete" else None
    snap.payload = payload.model_dump_json()
    snap.collected_at = datetime.now(timezone.utc)
    db.commit()
    emit(db, "device.inventory.updated", {"device_id": device_id, "software_count": len(payload.software),
        "software_status": payload.software_status, "software_changes": drift}, agent_actor(device_id),
        {"org_id": dev.org_id, "device_id": device_id}, {"reason": "agent inventory collection"})
    publish({"type": "inventory", "device_id": dev.id, "org_id": dev.org_id})
    return {"ok": True, "collected_at": snap.collected_at}


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
    if payload.customer_id is not None:
        from app.models.models import Customer

        if not db.query(Customer).filter(Customer.id == payload.customer_id, Customer.org_id == payload.org_id).first():
            raise HTTPException(status_code=404, detail="customer not found in organization")
    secret = _secrets.token_urlsafe(24)
    dev = Device(
        org_id=payload.org_id,
        hostname=payload.hostname,
        os=payload.os,
        ip=payload.ip,
        device_type=payload.device_type,
        customer_id=payload.customer_id,
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
    dev = db.query(Device).filter(Device.id == device_id).first()
    if not dev:
        raise HTTPException(status_code=404, detail="device not found")
    _scope_check(db, user, dev.org_id)
    authorize(db, user, "device_command", dev.id, payload.body)
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
    _scope_check(db, user, dev.org_id)
    emit(
        db,
        "device.deleted",
        {"hostname": dev.hostname, "id": dev.id},
        actor_of(user),
        {"org_id": dev.org_id, "device_id": dev.id},
        {"reason": "manual delete"},
    )
    _detach_dependents(db, dev.id)
    db.delete(dev)
    db.commit()


def _detach_dependents(db: Session, device_id: int) -> None:
    """Unlink history that outlives the endpoint and remove its own operational rows.

    PostgreSQL enforces these foreign keys; without this, any endpoint that ever raised
    an alert or ran a command could not be deleted. The signed proof ledger keeps the record.
    """
    from app.models.models import Base

    for table in reversed(Base.metadata.sorted_tables):
        for fk in table.foreign_keys:
            if fk.column.table.name != "devices" or table.name == "devices":
                continue
            column = table.c[fk.parent.name]
            if fk.parent.nullable:
                db.execute(table.update().where(column == device_id).values({fk.parent.name: None}))
            else:
                db.execute(table.delete().where(column == device_id))


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
    if payload.reboot_required is not None:
        dev.reboot_required = payload.reboot_required
    dev.last_seen = datetime.now(timezone.utc)
    db.add(DeviceMetric(org_id=dev.org_id, device_id=dev.id, cpu=dev.cpu, disk=dev.disk, mem=dev.mem))
    db.commit()
    db.refresh(dev)
    from app.services.thresholds import evaluate as evaluate_thresholds

    evaluate_thresholds(db, dev)
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
