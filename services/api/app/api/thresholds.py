"""Alert threshold profiles for endpoint metrics."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.proof import emit
from app.core.security import actor_of, get_current_user
from app.models.models import AlertThreshold
from app.services.thresholds import RECOMMENDED

router = APIRouter()


class ThresholdIn(BaseModel):
    metric: Literal["cpu", "mem", "disk"]
    limit: float = Field(gt=0, le=100)
    samples: int = Field(default=3, ge=1, le=20)
    severity: Literal["info", "warning", "critical"] = "warning"
    device_type: Literal["", "workstation", "server", "access_point", "gateway", "switch", "node"] = ""
    enabled: bool = True


def _out(t: AlertThreshold) -> dict:
    return {"id": t.id, "metric": t.metric, "limit": t.limit, "samples": t.samples, "severity": t.severity,
        "device_type": t.device_type, "enabled": t.enabled}


def _writer(user) -> None:
    if user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="admin/manager only")


@router.get("")
def list_thresholds(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return [_out(t) for t in db.query(AlertThreshold).filter(AlertThreshold.org_id == user.org_id).order_by(AlertThreshold.id).all()]


@router.post("", status_code=201)
def create_threshold(payload: ThresholdIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _writer(user)
    row = AlertThreshold(org_id=user.org_id, **payload.model_dump())
    db.add(row)
    db.flush()
    emit(db, "threshold.created", {"threshold_id": row.id, **payload.model_dump()}, actor_of(user), {"org_id": user.org_id}, {"reason": "alert threshold"})
    return _out(row)


@router.post("/recommended", status_code=201)
def apply_recommended(db: Session = Depends(get_db), user=Depends(get_current_user)):
    _writer(user)
    have = {(t.metric, t.device_type) for t in db.query(AlertThreshold).filter(AlertThreshold.org_id == user.org_id).all()}
    created = []
    for item in RECOMMENDED:
        if (item["metric"], "") not in have:
            row = AlertThreshold(org_id=user.org_id, device_type="", enabled=True, **item)
            db.add(row)
            created.append(row)
    db.flush()
    emit(db, "threshold.recommended.applied", {"created": [t.metric for t in created]}, actor_of(user), {"org_id": user.org_id}, {"reason": "recommended thresholds"})
    return [_out(t) for t in created]


@router.put("/{threshold_id}")
def update_threshold(threshold_id: int, payload: ThresholdIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _writer(user)
    row = db.query(AlertThreshold).filter(AlertThreshold.id == threshold_id, AlertThreshold.org_id == user.org_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="threshold not found in organization")
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    emit(db, "threshold.updated", {"threshold_id": row.id, **payload.model_dump()}, actor_of(user), {"org_id": user.org_id}, {"reason": "alert threshold"})
    return _out(row)


@router.delete("/{threshold_id}")
def delete_threshold(threshold_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _writer(user)
    row = db.query(AlertThreshold).filter(AlertThreshold.id == threshold_id, AlertThreshold.org_id == user.org_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="threshold not found in organization")
    db.delete(row)
    emit(db, "threshold.deleted", {"threshold_id": threshold_id}, actor_of(user), {"org_id": user.org_id}, {"reason": "alert threshold"})
    return {"ok": True}
