from __future__ import annotations

import secrets as _secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.proof import emit
from app.core.security import actor_of, get_current_user
from app.models.models import Device, RemoteSession
from app.schemas.schemas import RemoteSessionIn, RemoteSessionOut
from app.services.execution import queue_command

settings = get_settings()
router = APIRouter()


def _scope(user, org_id: int) -> None:
    if user.org_id != org_id:
        raise HTTPException(status_code=403, detail="org scope mismatch")


@router.get("", response_model=list[RemoteSessionOut])
def list_sessions(org_id: int, status: str | None = None, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, org_id)
    q = db.query(RemoteSession).filter(RemoteSession.org_id == org_id)
    if status:
        q = q.filter(RemoteSession.status == status)
    return q.order_by(RemoteSession.created_at.desc()).all()


@router.post("/devices/{device_id}/remote-session", status_code=201)
def open_session(device_id: int, payload: RemoteSessionIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    dev = db.query(Device).filter(Device.id == device_id).first()
    if not dev:
        raise HTTPException(status_code=404, detail="device not found")
    _scope(user, dev.org_id)
    token = _secrets.token_urlsafe(24)
    s = RemoteSession(org_id=dev.org_id, device_id=device_id, kind=payload.kind, provider=payload.provider, token=token)
    db.add(s)
    db.commit()
    db.refresh(s)

    ws_url = f"/v1/ws/terminal/{device_id}?session={token}" if s.kind == "console" else None
    connect_url = None
    note = None

    if s.kind == "kvm":
        if s.provider == "meshcentral":
            if settings.meshcentral_url:
                connect_url = f"{settings.meshcentral_url.rstrip('/')}/?viewmode=10&gotonode={device_id}"
                note = "MeshCentral node id is the ProofOS device id (map via MESHCENTRAL_URL)."
            else:
                note = "MeshCentral not configured — set MESHCENTRAL_URL."
        elif s.provider == "vnc":
            is_windows = (dev.os or "").lower().startswith("windows")
            if is_windows:
                note = "Windows: use RDP (mstsc) or configure MeshCentral for screen KVM."
            else:
                cmd = f"nohup x11vnc -forever -shared -rfbport {settings.vnc_port} -passwd {token} >/dev/null 2>&1 &"
                queue_command(db, dev.org_id, device_id, cmd, actor_of(user))
                connect_url = f"vnc://{dev.ip or 'host'}:{settings.vnc_port}"
                note = "x11vnc launch queued on the agent; connect with a VNC client."
        else:
            note = "Provider unsupported for kvm; use meshcentral or vnc."

    emit(db, "remote.session.opened", {"session_id": s.id, "device_id": device_id, "kind": s.kind, "provider": s.provider}, actor_of(user), {"org_id": dev.org_id, "device_id": device_id}, {"reason": "remote control"})
    return {
        "session_id": s.id,
        "device_id": device_id,
        "kind": s.kind,
        "provider": s.provider,
        "token": token,
        "ws_url": ws_url,
        "connect_url": connect_url,
        "note": note,
    }


@router.post("/{sid}/end")
def end_session(sid: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    s = db.query(RemoteSession).filter(RemoteSession.id == sid).first()
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    _scope(user, s.org_id)
    if s.status != "active":
        raise HTTPException(status_code=409, detail=f"already {s.status}")
    s.status = "ended"
    s.ended_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(s)
    emit(db, "remote.session.ended", {"session_id": s.id, "device_id": s.device_id}, actor_of(user), {"org_id": s.org_id}, {"reason": "remote control end"})
    return {"session_id": s.id, "status": s.status}
