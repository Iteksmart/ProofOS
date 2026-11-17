from datetime import datetime, timedelta, timezone
from typing import Literal
import hashlib
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.proof import emit
from app.core.security import actor_of, get_current_user
from app.models.models import AccessGrant, Device, Secret
from app.services.privileged import utc

router = APIRouter()


class GrantIn(BaseModel):
    capability: Literal["device_command", "vault_reveal"]
    target_id: int = Field(gt=0)
    command: str = Field(default="", max_length=10000)
    reason: str = Field(min_length=10, max_length=1000)
    minutes: int = Field(default=15, ge=1, le=60)


def out(row):
    status = row.status
    if status == "approved" and (not row.expires_at or utc(row.expires_at) <= datetime.now(timezone.utc)):
        status = "expired"
    return {"id": row.id, "requester_id": row.requester_id, "approver_id": row.approver_id,
        "capability": row.capability, "target_id": row.target_id, "command": row.command,
        "reason": row.reason, "minutes": row.minutes, "status": status, "expires_at": utc(row.expires_at)}


@router.get("")
def listing(db: Session = Depends(get_db), user=Depends(get_current_user)):
    query = db.query(AccessGrant).filter(AccessGrant.org_id == user.org_id)
    if user.role not in {"admin", "manager"}:
        query = query.filter(AccessGrant.requester_id == user.id)
    return [out(row) for row in query.order_by(AccessGrant.id.desc()).limit(200).all()]


@router.post("", status_code=201)
def request_grant(payload: GrantIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    model = Device if payload.capability == "device_command" else Secret
    if not db.query(model).filter(model.id == payload.target_id, model.org_id == user.org_id).first():
        raise HTTPException(status_code=404, detail="target not found in organization")
    if payload.capability == "device_command" and not payload.command.strip():
        raise HTTPException(status_code=422, detail="exact command required")
    if payload.capability == "vault_reveal" and payload.command:
        raise HTTPException(status_code=422, detail="command is not applicable to a vault grant")
    row = AccessGrant(org_id=user.org_id, requester_id=user.id, **payload.model_dump())
    db.add(row)
    db.flush()
    emit(db, "privileged.grant.requested", {"grant_id": row.id, "capability": row.capability,
        "target_id": row.target_id, "minutes": row.minutes, "command_sha256": hashlib.sha256(row.command.encode()).hexdigest()},
        actor_of(user), {"org_id": user.org_id}, {"reason": row.reason})
    return out(row)


@router.post("/{grant_id}/{decision}")
def decide(grant_id: int, decision: Literal["approve", "deny", "revoke"], db: Session = Depends(get_db), user=Depends(get_current_user)):
    row = db.query(AccessGrant).filter(AccessGrant.id == grant_id, AccessGrant.org_id == user.org_id).with_for_update().first()
    if not row:
        raise HTTPException(status_code=404, detail="grant not found")
    if user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="admin/manager only")
    if decision == "approve" and row.requester_id == user.id:
        raise HTTPException(status_code=403, detail="a different privileged user must approve access")
    if row.status != ("approved" if decision == "revoke" else "pending"):
        raise HTTPException(status_code=409, detail="grant is not in an applicable state")
    row.status = {"approve": "approved", "deny": "denied", "revoke": "revoked"}[decision]
    row.approver_id = user.id
    if decision == "approve":
        row.expires_at = datetime.now(timezone.utc) + timedelta(minutes=row.minutes)
    emit(db, f"privileged.grant.{row.status}", {"grant_id": row.id, "requester_id": row.requester_id,
        "expires_at": str(row.expires_at)}, actor_of(user), {"org_id": user.org_id}, {"reason": row.reason})
    return out(row)
