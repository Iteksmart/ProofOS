from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.proof import emit
from app.core.security import actor_of, get_current_user
from app.models.models import Secret
from app.schemas.schemas import SecretCreate, SecretOut
from app.services.vault import decrypt, encrypt

router = APIRouter()


def _scope(user, org_id: int) -> None:
    if user.org_id != org_id:
        raise HTTPException(status_code=403, detail="org scope mismatch")


def _require_admin(user) -> None:
    if user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="admin/manager only")


@router.get("", response_model=list[SecretOut])
def list_secrets(org_id: int, category: str | None = None, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, org_id)
    q = db.query(Secret).filter(Secret.org_id == org_id)
    if category:
        q = q.filter(Secret.category == category)
    return q.order_by(Secret.name.asc()).all()


@router.post("", response_model=SecretOut, status_code=201)
def create_secret(payload: SecretCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, payload.org_id)
    s = Secret(org_id=payload.org_id, name=payload.name, category=payload.category, value_encrypted=encrypt(payload.value), notes=payload.notes)
    db.add(s)
    db.commit()
    db.refresh(s)
    emit(db, "vault.secret.created", {"id": s.id, "name": s.name}, actor_of(user), {"org_id": payload.org_id}, {"reason": "secret vault"})
    return s


@router.post("/{sid}/reveal")
def reveal_secret(sid: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Reveal a secret value (admin/manager; audited)."""
    s = db.query(Secret).filter(Secret.id == sid).first()
    if not s:
        raise HTTPException(status_code=404, detail="secret not found")
    _scope(user, s.org_id)
    _require_admin(user)
    value = decrypt(s.value_encrypted)
    emit(db, "vault.secret.revealed", {"id": s.id, "name": s.name}, actor_of(user), {"org_id": s.org_id}, {"reason": "reveal"})
    return {"id": s.id, "name": s.name, "value": value}
