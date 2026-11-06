from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.proof import emit
from app.core.security import (
    actor_of,
    create_access_token,
    get_current_user,
    hash_password,
    rate_limit_login,
    verify_password,
)
from app.models.models import Org, User
from app.schemas.schemas import LoginIn, OrgCreate, OrgOut, TokenOut, UserCreate, UserOut

settings = get_settings()
router = APIRouter()


def _user_out(u: User) -> dict:
    return {"id": u.id, "org_id": u.org_id, "email": u.email, "role": u.role}


@router.post("/orgs", response_model=OrgOut, status_code=201)
def create_org(payload: OrgCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Authenticated self-service org creation. Anonymous creation is blocked."""
    existing = db.query(Org).filter(Org.name == payload.name).first()
    if existing:
        return existing
    org = Org(name=payload.name)
    db.add(org)
    db.commit()
    db.refresh(org)
    emit(
        db,
        "org.created",
        {"name": org.name, "id": org.id},
        actor_of(user),
        {"org_id": org.id},
        {"reason": "org register"},
    )
    return org


@router.get("/orgs/{org_id}", response_model=OrgOut)
def get_org(org_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    org = db.query(Org).filter(Org.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="org not found")
    if user.org_id != org_id and user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="org scope mismatch")
    return org


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(payload: UserCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Admin/manager creates users in their own org only."""
    if user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="admin/manager only")
    if user.org_id != payload.org_id:
        raise HTTPException(status_code=403, detail="org scope mismatch")
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=400, detail="email exists")
    org = db.query(Org).filter(Org.id == payload.org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="org not found")
    if payload.role not in {"admin", "manager", "engineer", "auditor", "viewer"}:
        raise HTTPException(status_code=400, detail=f"invalid role: {payload.role}")
    new_user = User(
        org_id=payload.org_id,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=payload.role,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    emit(
        db,
        "user.created",
        {"email": new_user.email, "id": new_user.id, "role": new_user.role},
        actor_of(user),
        {"org_id": new_user.org_id},
        {"reason": "user register"},
    )
    return _user_out(new_user)


@router.post("/login", response_model=TokenOut)
def login(payload: LoginIn, db: Session = Depends(get_db), _rl: None = Depends(rate_limit_login)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="bad credentials")
    token = create_access_token(
        str(user.id), {"email": user.email, "role": user.role, "org_id": user.org_id}
    )
    emit(
        db,
        "auth.login",
        {"email": user.email, "id": user.id},
        actor_of(user),
        {"org_id": user.org_id},
        {"reason": "login"},
    )
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me", response_model=UserOut)
def me(user=Depends(get_current_user)):
    return _user_out(user)


@router.get("/users", response_model=list[UserOut])
def list_users(org_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="admin/manager only")
    return db.query(User).filter(User.org_id == org_id).order_by(User.id.asc()).all()


@router.post("/bootstrap", response_model=dict, status_code=201)
def bootstrap(payload: OrgCreate, db: Session = Depends(get_db)):
    """Create org + admin user in one shot (dev/first-run). Disabled in production
    unless ALLOW_BOOTSTRAP=true. Safe to re-run."""
    if settings.is_prod and not settings.allow_bootstrap:
        raise HTTPException(status_code=403, detail="bootstrap disabled in production")
    org = db.query(Org).filter(Org.name == payload.name).first()
    if not org:
        org = Org(name=payload.name)
        db.add(org)
        db.commit()
        db.refresh(org)
        emit(
            db,
            "org.created",
            {"name": org.name, "id": org.id},
            {"actor_id": "bootstrap", "actor_type": "system"},
            {"org_id": org.id},
            {"reason": "bootstrap"},
        )
    admin_email = f"admin-{org.id}@proofos.dev"
    user = db.query(User).filter(User.email == admin_email, User.org_id == org.id).first()
    if not user:
        user = User(org_id=org.id, email=admin_email, hashed_password=hash_password("admin12345"), role="admin")
        db.add(user)
        db.commit()
        db.refresh(user)
        emit(
            db,
            "user.created",
            {"email": user.email, "id": user.id, "role": user.role},
            {"actor_id": "bootstrap", "actor_type": "system"},
            {"org_id": org.id},
            {"reason": "bootstrap admin"},
        )
    token = create_access_token(str(user.id), {"email": user.email, "role": user.role, "org_id": user.org_id})
    return {"org": {"id": org.id, "name": org.name}, "user": _user_out(user), "access_token": token}
