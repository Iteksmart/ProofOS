from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.proof import emit
from app.core.security import actor_of, get_current_user
from app.models.models import ClientProfile, Project
from app.schemas.schemas import ClientProfileIn, ClientProfileOut, ProjectCreate, ProjectOut, ProjectUpdate

router = APIRouter()


def _scope(user, org_id: int) -> None:
    if user.org_id != org_id and user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="org scope mismatch")


@router.get("/profile", response_model=ClientProfileOut)
def get_profile(org_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, org_id)
    p = db.query(ClientProfile).filter(ClientProfile.org_id == org_id).first()
    if not p:
        p = ClientProfile(org_id=org_id)
        db.add(p)
        db.commit()
        db.refresh(p)
    return p


@router.post("/profile", response_model=ClientProfileOut)
def upsert_profile(org_id: int, payload: ClientProfileIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, org_id)
    p = db.query(ClientProfile).filter(ClientProfile.org_id == org_id).first()
    if not p:
        p = ClientProfile(org_id=org_id)
        db.add(p)
    for field in ("contact_name", "contact_email", "phone", "industry", "status", "notes"):
        setattr(p, field, getattr(payload, field))
    db.commit()
    db.refresh(p)
    emit(db, "client.profile.updated", {"org_id": org_id}, actor_of(user), {"org_id": org_id}, {"reason": "consulting profile"})
    return p


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(org_id: int, limit: int = Query(200, le=500), db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, org_id)
    return db.query(Project).filter(Project.org_id == org_id).order_by(Project.created_at.desc()).limit(limit).all()


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, payload.org_id)
    p = Project(org_id=payload.org_id, name=payload.name, description=payload.description or "", status=payload.status or "planning")
    db.add(p)
    db.commit()
    db.refresh(p)
    emit(db, "project.created", {"id": p.id, "name": p.name}, actor_of(user), {"org_id": payload.org_id}, {"reason": "consulting project"})
    return p


@router.patch("/projects/{pid}", response_model=ProjectOut)
def update_project(pid: int, payload: ProjectUpdate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="project not found")
    _scope(user, p.org_id)
    for field in ("name", "description", "status", "notes"):
        val = getattr(payload, field)
        if val is not None:
            setattr(p, field, val)
    db.commit()
    db.refresh(p)
    return p
