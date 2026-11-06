from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.proof import emit
from app.core.security import actor_of, get_current_user
from app.models.models import TimeEntry
from app.schemas.schemas import TimeEntryCreate, TimeEntryOut

router = APIRouter()


def _scope(user, org_id: int) -> None:
    if user.org_id != org_id:
        raise HTTPException(status_code=403, detail="org scope mismatch")


@router.get("", response_model=list[TimeEntryOut])
def list_entries(org_id: int, limit: int = Query(200, le=1000), db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, org_id)
    return db.query(TimeEntry).filter(TimeEntry.org_id == org_id).order_by(TimeEntry.created_at.desc()).limit(limit).all()


@router.post("", response_model=TimeEntryOut, status_code=201)
def create_entry(payload: TimeEntryCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, payload.org_id)
    e = TimeEntry(org_id=payload.org_id, user_id=user.id, minutes=payload.minutes, notes=payload.notes, billable=payload.billable, ticket_id=payload.ticket_id, project_id=payload.project_id)
    db.add(e)
    db.commit()
    db.refresh(e)
    emit(db, "psa.time.entered", {"id": e.id, "minutes": e.minutes}, actor_of(user), {"org_id": payload.org_id}, {"reason": "time tracking"})
    return e


@router.get("/summary")
def summary(org_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, org_id)
    entries = db.query(TimeEntry).filter(TimeEntry.org_id == org_id).all()
    total = sum(e.minutes for e in entries)
    billable = sum(e.minutes for e in entries if e.billable)
    return {"entries": len(entries), "total_minutes": total, "total_hours": round(total / 60, 1), "billable_hours": round(billable / 60, 1)}
