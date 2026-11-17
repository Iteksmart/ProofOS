"""Service level objectives: define, evaluate and alert on error-budget burn."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.proof import emit
from app.core.security import actor_of, get_current_user
from app.models.models import ServiceSlo
from app.services import slo as slo_service

router = APIRouter()


class SloIn(BaseModel):
    service: str = Field(min_length=1, max_length=255)
    max_error_rate: float = Field(default=0.01, gt=0, le=1)
    max_p95_ms: float = Field(default=0, ge=0, le=600000)
    window_minutes: int = Field(default=15, ge=5, le=360)
    min_requests: int = Field(default=20, ge=1, le=1000000)


def _writer(user) -> None:
    if user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="admin/manager only")


@router.get("")
def list_slos(db: Session = Depends(get_db), user=Depends(get_current_user)):
    rows = db.query(ServiceSlo).filter(ServiceSlo.org_id == user.org_id).order_by(ServiceSlo.service).all()
    return [slo_service.evaluate(db, r) for r in rows]


@router.put("")
def upsert_slo(payload: SloIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _writer(user)
    row = db.query(ServiceSlo).filter(ServiceSlo.org_id == user.org_id, ServiceSlo.service == payload.service.strip()).first()
    if not row:
        row = ServiceSlo(org_id=user.org_id, service=payload.service.strip())
        db.add(row)
    for key in ("max_error_rate", "max_p95_ms", "window_minutes", "min_requests"):
        setattr(row, key, getattr(payload, key))
    db.commit()
    emit(db, "slo.defined", payload.model_dump(), actor_of(user), {"org_id": user.org_id}, {"reason": "set service objective"})
    return slo_service.evaluate(db, row)


@router.delete("/{slo_id}", status_code=204)
def delete_slo(slo_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _writer(user)
    row = db.query(ServiceSlo).filter(ServiceSlo.id == slo_id, ServiceSlo.org_id == user.org_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="SLO not found")
    db.delete(row)
    db.commit()
    emit(db, "slo.deleted", {"id": slo_id, "service": row.service}, actor_of(user), {"org_id": user.org_id}, {"reason": "remove service objective"})


@router.post("/check")
def check_now(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return slo_service.check(db, user.org_id)
