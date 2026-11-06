from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.proof import emit
from app.core.security import actor_of, get_current_user
from app.models.models import KillSwitch
from app.services import kill_switch as ks

settings = get_settings()
router = APIRouter()


class KillSwitchIn(BaseModel):
    engaged: bool
    reason: str = ""


def _require_admin(user) -> None:
    if user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="admin/manager only")


@router.get("/kill-switch")
def get_kill_switch(db: Session = Depends(get_db), user=Depends(get_current_user)):
    row = db.query(KillSwitch).filter(KillSwitch.id == 1).first()
    return {
        "engaged": ks.engaged(db),
        "db_engaged": bool(row.engaged) if row else False,
        "env_override": settings.kill_switch,
        "reason": row.reason if row else "",
    }


@router.post("/kill-switch")
def set_kill_switch(payload: KillSwitchIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _require_admin(user)
    row = db.query(KillSwitch).filter(KillSwitch.id == 1).first()
    if not row:
        row = KillSwitch(id=1, engaged=payload.engaged, reason=payload.reason)
        db.add(row)
    else:
        row.engaged = payload.engaged
        row.reason = payload.reason
    db.commit()
    db.refresh(row)
    emit(
        db,
        "kill_switch." + ("engaged" if payload.engaged else "disengaged"),
        {"reason": payload.reason},
        actor_of(user),
        {"org_id": user.org_id},
        {"reason": "kill switch"},
    )
    return {"engaged": row.engaged, "reason": row.reason}
