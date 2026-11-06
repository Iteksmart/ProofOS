from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.proof import emit
from app.core.security import actor_of, get_current_user
from app.models.models import Device, Patch
from app.schemas.schemas import PatchCreate, PatchOut
from app.services.execution import queue_command

router = APIRouter()

SCAN_CMD = {
    "windows": 'powershell -Command "winget upgrade --accept-source-agreements | Out-String"',
    "linux": "apt list --upgradable 2>/dev/null || yum check-update 2>/dev/null || true",
}
DEPLOY_CMD = {
    "windows": 'powershell -Command "winget upgrade --all --silent --accept-source-agreements --accept-package-agreements"',
    "linux": "sudo apt-get update -y && sudo apt-get upgrade -y 2>/dev/null || sudo yum update -y",
}


def _scope(user, org_id: int) -> None:
    if user.org_id != org_id:
        raise HTTPException(status_code=403, detail="org scope mismatch")


def _require_admin(user) -> None:
    if user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="admin/manager only")


@router.get("", response_model=list[PatchOut])
def list_patches(org_id: int, status: str | None = None, category: str | None = None, device_id: int | None = None, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, org_id)
    q = db.query(Patch).filter(Patch.org_id == org_id)
    if status:
        q = q.filter(Patch.status == status)
    if category:
        q = q.filter(Patch.category == category)
    if device_id:
        q = q.filter(Patch.device_id == device_id)
    return q.order_by(Patch.severity.desc(), Patch.name.asc()).all()


@router.post("", response_model=PatchOut, status_code=201)
def register_patch(payload: PatchCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, payload.org_id)
    dev = db.query(Device).filter(Device.id == payload.device_id, Device.org_id == payload.org_id).first()
    if not dev:
        raise HTTPException(status_code=404, detail="device not found")
    p = Patch(org_id=payload.org_id, device_id=payload.device_id, name=payload.name, category=payload.category, current_version=payload.current_version, available_version=payload.available_version, severity=payload.severity)
    db.add(p)
    db.commit()
    db.refresh(p)
    emit(db, "patch.registered", {"id": p.id, "name": p.name, "severity": p.severity}, actor_of(user), {"org_id": payload.org_id, "device_id": payload.device_id}, {"reason": "patch inventory"})
    return p


@router.post("/{pid}/deploy")
def deploy_patch(pid: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Queue the OS-specific update command on the device's agent."""
    p = db.query(Patch).filter(Patch.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="patch not found")
    _scope(user, p.org_id)
    _require_admin(user)
    dev = db.query(Device).filter(Device.id == p.device_id).first()
    os_key = "windows" if (dev.os or "").lower().startswith("windows") else "linux"
    cmd = DEPLOY_CMD[os_key]
    run = queue_command(db, p.org_id, p.device_id, cmd, actor_of(user))
    p.status = "installed"
    db.commit()
    db.refresh(p)
    emit(db, "patch.deployed", {"patch_id": p.id, "name": p.name, "run_id": run.id}, actor_of(user), {"org_id": p.org_id, "device_id": p.device_id}, {"reason": "patch deployment"})
    return {"patch_id": p.id, "status": p.status, "run_id": run.id, "command": cmd}


@router.post("/scan")
def scan_device(device_id: int, org_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Queue the OS patch enumeration command (output appears in Scripts → run history)."""
    _scope(user, org_id)
    _require_admin(user)
    dev = db.query(Device).filter(Device.id == device_id, Device.org_id == org_id).first()
    if not dev:
        raise HTTPException(status_code=404, detail="device not found")
    os_key = "windows" if (dev.os or "").lower().startswith("windows") else "linux"
    run = queue_command(db, org_id, device_id, SCAN_CMD[os_key], actor_of(user))
    emit(db, "patch.scan", {"device_id": device_id, "run_id": run.id}, actor_of(user), {"org_id": org_id, "device_id": device_id}, {"reason": "patch scan"})
    return {"device_id": device_id, "run_id": run.id, "command": SCAN_CMD[os_key]}
