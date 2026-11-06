from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.proof import emit
from app.core.security import actor_of, get_current_user
from app.models.models import Automation
from app.schemas.schemas import AutomationCreate, AutomationOut, AutomationUpdate, SimulateIn
from app.services.automation_engine import evaluate, simulate

router = APIRouter()


def _scope(user, org_id: int) -> None:
    if user.org_id != org_id and user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="org scope mismatch")


@router.get("", response_model=list[AutomationOut])
def list_automations(org_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, org_id)
    return db.query(Automation).filter(Automation.org_id == org_id).all()


@router.post("", response_model=AutomationOut, status_code=201)
def create_automation(payload: AutomationCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, payload.org_id)
    a = Automation(org_id=payload.org_id, name=payload.name, trigger=payload.trigger, action=payload.action, condition=payload.condition or "", autonomy=payload.autonomy, remediation_script_id=payload.remediation_script_id, enabled=True)
    db.add(a)
    db.commit()
    db.refresh(a)
    emit(
        db,
        "automation.created",
        {"name": a.name, "id": a.id},
        actor_of(user),
        {"org_id": payload.org_id, "automation_id": a.id},
        {"reason": "rule author"},
    )
    return a


@router.patch("/{aid}/toggle", response_model=AutomationOut)
def toggle_automation(aid: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = db.query(Automation).filter(Automation.id == aid).first()
    if not a:
        raise HTTPException(status_code=404, detail="automation not found")
    _scope(user, a.org_id)
    a.enabled = not a.enabled
    db.commit()
    db.refresh(a)
    emit(
        db,
        "automation.toggled",
        {"id": a.id, "enabled": a.enabled},
        actor_of(user),
        {"org_id": a.org_id, "automation_id": a.id},
        {"reason": "toggle"},
    )
    return a


@router.patch("/{aid}", response_model=AutomationOut)
def update_automation(aid: int, payload: AutomationUpdate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = db.query(Automation).filter(Automation.id == aid).first()
    if not a:
        raise HTTPException(status_code=404, detail="automation not found")
    _scope(user, a.org_id)
    for field in ("name", "trigger", "action", "condition", "autonomy", "remediation_script_id", "enabled"):
        val = getattr(payload, field)
        if val is not None:
            setattr(a, field, val)
    db.commit()
    db.refresh(a)
    emit(
        db,
        "automation.updated",
        {"id": a.id, "trigger": a.trigger, "action": a.action},
        actor_of(user),
        {"org_id": a.org_id, "automation_id": a.id},
        {"reason": "rule edit"},
    )
    return a


@router.post("/evaluate", status_code=201)
def run_evaluate(org_id: int, trigger: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, org_id)
    runs = evaluate(db, org_id, trigger, {"manual": True})
    return [{"id": r.id, "automation_id": r.automation_id, "trigger": r.trigger, "result": r.result} for r in runs]


@router.post("/simulate")
def simulate_automations(payload: SimulateIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Dry-run (no side effects): show what automations would do."""
    _scope(user, payload.org_id)
    return simulate(db, payload.org_id, payload.trigger, payload.context or {})
