from __future__ import annotations

import uuid

from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.proof import emit
from app.core.security import actor_of, get_current_user
from app.models.models import Device, EnclaveEvent, EnclavePolicy, SecureEnclave
from app.schemas.schemas import (
    EnclaveCreate,
    EnclaveEventIn,
    EnclaveEventOut,
    EnclaveOut,
    EnclavePolicyIn,
    EnclavePolicyOut,
)
from app.services import dlp

router = APIRouter()


def _scope(user, org_id: int) -> None:
    if user.org_id != org_id and user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="org scope mismatch")


# --- Policies ---
@router.get("/policies", response_model=list[EnclavePolicyOut])
def list_policies(org_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, org_id)
    return db.query(EnclavePolicy).filter(EnclavePolicy.org_id == org_id).order_by(EnclavePolicy.name.asc()).all()


@router.post("/policies", response_model=EnclavePolicyOut, status_code=201)
def create_policy(org_id: int, payload: EnclavePolicyIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, org_id)
    p = EnclavePolicy(org_id=org_id, **payload.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    emit(db, "enclave.policy.created", {"policy_id": p.id, "name": p.name}, actor_of(user), {"org_id": org_id}, {"reason": "secure workspace policy"})
    return p


# --- DLP scan (no storage) ---
class DlpScanIn(BaseModel):
    text: str = ""


@router.post("/scan")
def scan(payload: DlpScanIn, user=Depends(get_current_user)):
    """Scan content for sensitive data before it leaves the enclave."""
    return {"hits": dlp.detect(payload.text), "blocked": dlp.has_sensitive(payload.text)}


# --- Enclaves ---
@router.get("", response_model=list[EnclaveOut])
def list_enclaves(org_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, org_id)
    return db.query(SecureEnclave).filter(SecureEnclave.org_id == org_id).order_by(SecureEnclave.created_at.desc()).all()


@router.post("", status_code=201)
def provision_enclave(payload: EnclaveCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, payload.org_id)
    dev = db.query(Device).filter(Device.id == payload.device_id, Device.org_id == payload.org_id).first()
    if not dev:
        raise HTTPException(status_code=404, detail="device not found")
    if payload.policy_id:
        pol = db.query(EnclavePolicy).filter(EnclavePolicy.id == payload.policy_id, EnclavePolicy.org_id == payload.org_id).first()
        if not pol:
            raise HTTPException(status_code=404, detail="policy not found")
    # One-time enclave encryption key (shown once; only the key id is stored server-side).
    enclave_key = Fernet.generate_key().decode()
    enclave = SecureEnclave(
        org_id=payload.org_id,
        device_id=payload.device_id,
        policy_id=payload.policy_id,
        name=payload.name,
        status="active",
        encryption_key_id=uuid.uuid4().hex[:32],
    )
    db.add(enclave)
    db.commit()
    db.refresh(enclave)
    emit(db, "enclave.provisioned", {"enclave_id": enclave.id, "device_id": payload.device_id}, actor_of(user), {"org_id": payload.org_id, "device_id": payload.device_id}, {"reason": "secure workspace provisioning"})
    return {
        "enclave": EnclaveOut.model_validate(enclave).model_dump(),
        "enclave_key": enclave_key,  # one-time; the agent stores it locally
        "note": "Work data in this enclave is encrypted at rest. Personal apps/files outside the enclave remain private.",
    }


@router.get("/{enclave_id}", response_model=EnclaveOut)
def get_enclave(enclave_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    e = db.query(SecureEnclave).filter(SecureEnclave.id == enclave_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="enclave not found")
    _scope(user, e.org_id)
    return e


class EnclavePatch(BaseModel):
    status: str


@router.patch("/{enclave_id}", response_model=EnclaveOut)
def update_enclave(enclave_id: int, payload: EnclavePatch, db: Session = Depends(get_db), user=Depends(get_current_user)):
    e = db.query(SecureEnclave).filter(SecureEnclave.id == enclave_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="enclave not found")
    _scope(user, e.org_id)
    if user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="admin/manager only")
    if payload.status not in {"active", "suspended", "removed"}:
        raise HTTPException(status_code=400, detail="invalid status")
    e.status = payload.status
    db.commit()
    db.refresh(e)
    emit(db, f"enclave.{payload.status}", {"enclave_id": e.id}, actor_of(user), {"org_id": e.org_id, "device_id": e.device_id}, {"reason": "secure workspace lifecycle"})
    return e


# --- Events (DLP / policy violations reported by the agent) ---
@router.post("/{enclave_id}/events", response_model=EnclaveEventOut, status_code=201)
def report_event(enclave_id: int, payload: EnclaveEventIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    e = db.query(SecureEnclave).filter(SecureEnclave.id == enclave_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="enclave not found")
    _scope(user, e.org_id)
    severity = payload.severity
    hits = dlp.detect(payload.detail)
    if hits and severity == "info":
        severity = "critical"
    ev = EnclaveEvent(
        org_id=e.org_id,
        enclave_id=e.id,
        device_id=e.device_id,
        kind=payload.kind,
        severity=severity,
        detail=payload.detail[:2000],
        source=payload.source,
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    emit(
        db,
        "enclave.event",
        {"enclave_id": e.id, "kind": ev.kind, "severity": ev.severity, "dlp_hits": [h["pattern"] for h in hits]},
        actor_of(user),
        {"org_id": e.org_id, "device_id": e.device_id},
        {"reason": "DLP / policy enforcement"},
    )
    return ev


@router.get("/{enclave_id}/events", response_model=list[EnclaveEventOut])
def list_events(enclave_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    e = db.query(SecureEnclave).filter(SecureEnclave.id == enclave_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="enclave not found")
    _scope(user, e.org_id)
    return db.query(EnclaveEvent).filter(EnclaveEvent.enclave_id == enclave_id).order_by(EnclaveEvent.created_at.desc()).all()
