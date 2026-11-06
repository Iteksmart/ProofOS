from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import get_current_user
from app.models.models import PushDevice
from app.schemas.schemas import PushDeviceOut, PushRegister
from app.services import fcm

router = APIRouter()


def _scope(user, org_id: int) -> None:
    if user.org_id != org_id and user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="org scope mismatch")


@router.post("/register", response_model=PushDeviceOut, status_code=201)
def register(payload: PushRegister, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if payload.user_id != user.id and user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="cannot register a token for another user")
    _scope(user, payload.org_id)
    existing = db.query(PushDevice).filter(PushDevice.fcm_token == payload.fcm_token).first()
    if existing:
        return existing
    pd = PushDevice(org_id=payload.org_id, user_id=payload.user_id, fcm_token=payload.fcm_token, platform=payload.platform)
    db.add(pd)
    db.commit()
    db.refresh(pd)
    return pd


@router.get("", response_model=list[PushDeviceOut])
def list_devices(org_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, org_id)
    return db.query(PushDevice).filter(PushDevice.org_id == org_id).all()


@router.post("/test")
def test_push(org_id: int, title: str = "ProofOS", body: str = "Test push notification", db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, org_id)
    if not fcm.configured():
        raise HTTPException(status_code=400, detail="FCM not configured — set FCM_PROJECT_ID and FCM_SERVICE_ACCOUNT_JSON")
    tokens = db.query(PushDevice).filter(PushDevice.org_id == org_id).all()
    results = [fcm.send_push(t.fcm_token, title, body) for t in tokens]
    return {"sent": len(tokens), "results": results}
