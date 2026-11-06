from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.proof import emit
from app.core.security import actor_of, get_current_user
from app.models.models import ChangeRequest
from app.schemas.schemas import ChangeCreate, ChangeOut, ChangeUpdate

router = APIRouter()

VALID_STATUS = {"draft", "submitted", "approved", "rejected", "implemented"}


def _scope(user, org_id: int) -> None:
    if user.org_id != org_id and user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="org scope mismatch")


@router.get("", response_model=list[ChangeOut])
def list_changes(org_id: int, status: str | None = None, limit: int = Query(200, le=1000), db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, org_id)
    q = db.query(ChangeRequest).filter(ChangeRequest.org_id == org_id)
    if status:
        q = q.filter(ChangeRequest.status == status)
    return q.order_by(ChangeRequest.created_at.desc()).limit(limit).all()


@router.post("", response_model=ChangeOut, status_code=201)
def create_change(payload: ChangeCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, payload.org_id)
    c = ChangeRequest(org_id=payload.org_id, title=payload.title, description=payload.description, risk=payload.risk, impact=payload.impact, plan=payload.plan, requester_id=user.id)
    db.add(c)
    db.commit()
    db.refresh(c)
    emit(db, "change.created", {"id": c.id, "title": c.title, "risk": c.risk}, actor_of(user), {"org_id": payload.org_id}, {"reason": "change management"})
    return c


@router.patch("/{cid}", response_model=ChangeOut)
def update_change(cid: int, payload: ChangeUpdate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    c = db.query(ChangeRequest).filter(ChangeRequest.id == cid).first()
    if not c:
        raise HTTPException(status_code=404, detail="change not found")
    _scope(user, c.org_id)
    if payload.status and payload.status not in VALID_STATUS:
        raise HTTPException(status_code=400, detail=f"invalid status: {payload.status}")
    for field in ("title", "description", "risk", "impact", "plan", "status"):
        val = getattr(payload, field)
        if val is not None:
            setattr(c, field, val)
    db.commit()
    db.refresh(c)
    if payload.status:
        emit(db, "change.status", {"id": c.id, "status": c.status}, actor_of(user), {"org_id": c.org_id}, {"reason": "change transition"})
    return c
