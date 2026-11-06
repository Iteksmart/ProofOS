from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.proof import emit
from app.core.security import actor_of, get_current_user
from app.models.models import ConfigurationItem
from app.schemas.schemas import CiCreate, CiOut

router = APIRouter()


def _scope(user, org_id: int) -> None:
    if user.org_id != org_id and user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="org scope mismatch")


@router.get("", response_model=list[CiOut])
def list_cis(org_id: int, ci_type: str | None = None, q: str | None = None, limit: int = Query(200, le=1000), db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, org_id)
    query = db.query(ConfigurationItem).filter(ConfigurationItem.org_id == org_id)
    if ci_type:
        query = query.filter(ConfigurationItem.ci_type == ci_type)
    if q:
        query = query.filter(ConfigurationItem.name.ilike(f"%{q}%"))
    return query.order_by(ConfigurationItem.name.asc()).limit(limit).all()


@router.post("", response_model=CiOut, status_code=201)
def create_ci(payload: CiCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, payload.org_id)
    ci = ConfigurationItem(org_id=payload.org_id, name=payload.name, ci_type=payload.ci_type, status=payload.status, description=payload.description, attributes=payload.attributes)
    db.add(ci)
    db.commit()
    db.refresh(ci)
    emit(db, "cmdb.ci.created", {"id": ci.id, "name": ci.name, "type": ci.ci_type}, actor_of(user), {"org_id": payload.org_id}, {"reason": "CMDB register"})
    return ci


@router.patch("/{ci_id}", response_model=CiOut)
def update_ci(ci_id: int, payload: dict, db: Session = Depends(get_db), user=Depends(get_current_user)):
    ci = db.query(ConfigurationItem).filter(ConfigurationItem.id == ci_id).first()
    if not ci:
        raise HTTPException(status_code=404, detail="CI not found")
    _scope(user, ci.org_id)
    for field in ("name", "ci_type", "status", "description", "attributes"):
        if field in payload:
            setattr(ci, field, payload[field])
    db.commit()
    db.refresh(ci)
    return ci
