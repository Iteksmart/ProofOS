from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.proof import emit
from app.core.security import actor_of, get_current_user
from app.models.models import Approval
from app.schemas.schemas import ApprovalOut
from app.services.execution import execute_approval

router = APIRouter()


def _scope(user, org_id: int) -> None:
    if user.org_id != org_id:
        raise HTTPException(status_code=403, detail="org scope mismatch")


def _require_admin(user) -> None:
    if user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="admin/manager only")


@router.get("", response_model=list[ApprovalOut])
def list_approvals(
    org_id: int,
    status: str | None = None,
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _scope(user, org_id)
    q = db.query(Approval).filter(Approval.org_id == org_id)
    if status:
        q = q.filter(Approval.status == status)
    return q.order_by(Approval.created_at.desc()).limit(limit).all()


@router.post("/{aid}/approve")
def approve(aid: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = db.query(Approval).filter(Approval.id == aid).first()
    if not a:
        raise HTTPException(status_code=404, detail="approval not found")
    _scope(user, a.org_id)
    _require_admin(user)
    if a.status != "pending":
        raise HTTPException(status_code=409, detail=f"already {a.status}")
    a.status = "approved"
    a.decided_by = user.email
    a.decided_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(a)
    result = execute_approval(db, a)
    emit(
        db,
        "approval.approved",
        {"id": a.id, "kind": a.kind, "result": result},
        actor_of(user),
        {"org_id": a.org_id},
        {"reason": "human approval"},
    )
    return {"id": a.id, "status": a.status, "result": result}


@router.post("/{aid}/deny")
def deny(aid: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = db.query(Approval).filter(Approval.id == aid).first()
    if not a:
        raise HTTPException(status_code=404, detail="approval not found")
    _scope(user, a.org_id)
    _require_admin(user)
    if a.status != "pending":
        raise HTTPException(status_code=409, detail=f"already {a.status}")
    a.status = "denied"
    a.decided_by = user.email
    a.decided_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(a)
    emit(
        db,
        "approval.denied",
        {"id": a.id, "kind": a.kind},
        actor_of(user),
        {"org_id": a.org_id},
        {"reason": "human denial"},
    )
    return {"id": a.id, "status": a.status}
