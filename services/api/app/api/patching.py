"""Patch policies, approvals and compliance."""
from __future__ import annotations

import datetime as dt
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.proof import emit
from app.core.security import actor_of, get_current_user
from app.models.models import Customer, Patch, PatchPolicy
from app.services import patching

router = APIRouter()


def _writer(user) -> None:
    if user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="admin/manager only")


class PolicyIn(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    enabled: bool = True
    auto_approve: list[Literal["critical", "important", "moderate", "low"]] = ["critical", "important"]
    categories: list[Literal["os", "security", "third_party", "other"]] = []
    device_types: list[Literal["workstation", "server", "access_point", "gateway", "switch", "node"]] = []
    customer_id: int | None = Field(default=None, gt=0)
    window_days: list[int] = [0, 1, 2, 3, 4, 5, 6]
    window_start_hour: int = Field(default=22, ge=0, le=23)
    window_end_hour: int = Field(default=4, ge=0, le=23)
    defer_days: int = Field(default=0, ge=0, le=60)
    reboot: Literal["never", "if_required", "always"] = "if_required"

    @field_validator("window_days")
    @classmethod
    def _days(cls, value: list[int]) -> list[int]:
        if not value or any(d < 0 or d > 6 for d in value):
            raise ValueError("choose at least one day; Monday = 0 … Sunday = 6")
        return sorted(set(value))


def _out(policy: PatchPolicy, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    nxt = patching.next_window_start(policy, now)
    return {"id": policy.id, "name": policy.name, "enabled": policy.enabled, "auto_approve": patching.loads(policy.auto_approve),
        "categories": patching.loads(policy.categories), "device_types": patching.loads(policy.device_types),
        "customer_id": policy.customer_id, "window_days": patching.loads(policy.window_days),
        "window_start_hour": policy.window_start_hour, "window_end_hour": policy.window_end_hour,
        "defer_days": policy.defer_days, "reboot": policy.reboot, "last_run_at": policy.last_run_at,
        "window_open": patching.in_window(policy, now), "next_window": nxt.isoformat() if nxt else None}


def _apply(policy: PatchPolicy, payload: PolicyIn) -> None:
    policy.name, policy.enabled = payload.name.strip(), payload.enabled
    policy.auto_approve, policy.categories = json.dumps(payload.auto_approve), json.dumps(payload.categories)
    policy.device_types, policy.window_days = json.dumps(payload.device_types), json.dumps(payload.window_days)
    policy.customer_id = payload.customer_id
    policy.window_start_hour, policy.window_end_hour = payload.window_start_hour, payload.window_end_hour
    policy.defer_days, policy.reboot = payload.defer_days, payload.reboot


def _load(db: Session, user, policy_id: int) -> PatchPolicy:
    policy = db.query(PatchPolicy).filter(PatchPolicy.id == policy_id, PatchPolicy.org_id == user.org_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail="policy not found in organization")
    return policy


def _check_customer(db: Session, user, customer_id: int | None) -> None:
    if customer_id and not db.query(Customer).filter(Customer.id == customer_id, Customer.org_id == user.org_id).first():
        raise HTTPException(status_code=404, detail="customer not found in organization")


@router.get("/policies")
def list_policies(db: Session = Depends(get_db), user=Depends(get_current_user)):
    now = dt.datetime.now(dt.timezone.utc)
    return [_out(p, now) for p in db.query(PatchPolicy).filter(PatchPolicy.org_id == user.org_id).order_by(PatchPolicy.id).all()]


@router.post("/policies", status_code=201)
def create_policy(payload: PolicyIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _writer(user)
    _check_customer(db, user, payload.customer_id)
    policy = PatchPolicy(org_id=user.org_id)
    _apply(policy, payload)
    db.add(policy)
    db.flush()
    emit(db, "patch.policy.created", {"policy_id": policy.id, **payload.model_dump()}, actor_of(user), {"org_id": user.org_id}, {"reason": "define patch policy"})
    return _out(policy)


@router.put("/policies/{policy_id}")
def update_policy(policy_id: int, payload: PolicyIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _writer(user)
    _check_customer(db, user, payload.customer_id)
    policy = _load(db, user, policy_id)
    _apply(policy, payload)
    emit(db, "patch.policy.updated", {"policy_id": policy.id, **payload.model_dump()}, actor_of(user), {"org_id": user.org_id}, {"reason": "change patch policy"})
    return _out(policy)


@router.delete("/policies/{policy_id}")
def delete_policy(policy_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _writer(user)
    policy = _load(db, user, policy_id)
    db.delete(policy)
    emit(db, "patch.policy.deleted", {"policy_id": policy_id}, actor_of(user), {"org_id": user.org_id}, {"reason": "remove patch policy"})
    return {"ok": True}


@router.get("/policies/{policy_id}/preview")
def preview(policy_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    policy = _load(db, user, policy_id)
    now = dt.datetime.now(dt.timezone.utc)
    from app.models.models import Device
    names = {d.id: d.hostname for d in db.query(Device).filter(Device.org_id == user.org_id).all()}
    groups = patching.eligible(db, policy, now)
    return {**_out(policy, now), "devices": [{"device_id": device_id, "hostname": names.get(device_id, "?"),
        "patches": [{"id": p.id, "name": p.name, "severity": p.severity, "approval": p.approval} for p in patches]}
        for device_id, patches in groups.items()], "patch_count": sum(len(p) for p in groups.values())}


class RunIn(BaseModel):
    force: bool = False


@router.post("/policies/{policy_id}/run")
def run(policy_id: int, payload: RunIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _writer(user)
    return patching.run_policy(db, _load(db, user, policy_id), actor_of(user), force=payload.force)


class ApprovalIn(BaseModel):
    patch_ids: list[int] = Field(min_length=1, max_length=1000)
    decision: Literal["approve", "reject", "defer", "reset"]


@router.post("/approvals")
def approvals(payload: ApprovalIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _writer(user)
    ids = sorted(set(payload.patch_ids))
    rows = db.query(Patch).filter(Patch.org_id == user.org_id, Patch.id.in_(ids)).all()
    if len(rows) != len(ids):
        raise HTTPException(status_code=404, detail="one or more patches are not in this organization")
    state = {"approve": "approved", "reject": "rejected", "defer": "deferred", "reset": "unreviewed"}[payload.decision]
    for row in rows:
        row.approval = state
    emit(db, f"patch.approval.{state}", {"patch_ids": ids, "names": [r.name for r in rows]}, actor_of(user),
        {"org_id": user.org_id}, {"reason": f"patch {payload.decision}"})
    return {"updated": len(rows), "approval": state}


@router.get("/compliance")
def get_compliance(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return patching.compliance(db, user.org_id)
