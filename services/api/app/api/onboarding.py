from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import get_current_user
from app.models.models import OnboardingStep
from app.schemas.schemas import OnboardingStepOut

router = APIRouter()

DEFAULT_STEPS = [
    ("Client kickoff call", "Align scope, stakeholders, and success criteria."),
    ("Discover assets & inventory", "Register devices: workstations, servers, switches, APs, gateways, nodes."),
    ("Install agents on endpoints", "Deploy the ProofOS agent for inventory, heartbeat, and scripts."),
    ("Configure monitoring & alerts", "Set port/HTTP/SNMP checks, thresholds, and Slack/email/webhook alerts."),
    ("Set up backup & DR", "Confirm backup/recovery posture for critical systems."),
    ("Run security/compliance audit", "Generate an infrastructure audit and review findings."),
    ("Document access & credentials", "Record accounts, roles, and privileged access."),
    ("Handoff & training", "Train admins and hand over documentation."),
]


def _scope(user, org_id: int) -> None:
    if user.org_id != org_id and user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="org scope mismatch")


@router.post("/init", status_code=201)
def init_onboarding(org_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, org_id)
    existing = db.query(OnboardingStep).filter(OnboardingStep.org_id == org_id).count()
    if existing:
        return {"initialized": False, "steps": existing}
    for i, (title, detail) in enumerate(DEFAULT_STEPS):
        db.add(OnboardingStep(org_id=org_id, title=title, detail=detail, step_order=i))
    db.commit()
    return {"initialized": True, "steps": len(DEFAULT_STEPS)}


@router.get("", response_model=list[OnboardingStepOut])
def list_steps(org_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, org_id)
    return db.query(OnboardingStep).filter(OnboardingStep.org_id == org_id).order_by(OnboardingStep.step_order.asc()).all()


@router.post("/{step_id}/toggle", response_model=OnboardingStepOut)
def toggle_step(step_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    s = db.query(OnboardingStep).filter(OnboardingStep.id == step_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="step not found")
    _scope(user, s.org_id)
    s.done = not s.done
    db.commit()
    db.refresh(s)
    return s
