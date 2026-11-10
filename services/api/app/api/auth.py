from __future__ import annotations

import logging
import secrets as _secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.proof import emit
from app.core.security import (
    actor_of,
    create_access_token,
    decode_token,
    get_current_user,
    hash_password,
    rate_limit_password_reset,
    rate_limit_login,
    verify_password_reset_token,
    verify_password,
)
from app.models.models import Org, User
from app.schemas.schemas import (
    LoginIn,
    OrgCreate,
    OrgRename,
    OrgOut,
    PasswordChangeIn,
    PasswordResetConfirmIn,
    PasswordResetRequestIn,
    TokenOut,
    UserCreate,
    UserOut,
    WorkspaceBootstrap,
)

settings = get_settings()
router = APIRouter()
log = logging.getLogger(__name__)


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
    if user.org_id != org_id:
        raise HTTPException(status_code=403, detail="org scope mismatch")
    return org


@router.patch("/orgs/{org_id}", response_model=OrgOut)
def rename_org(payload: OrgRename, org_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="admin only")
    if user.org_id != org_id:
        raise HTTPException(status_code=403, detail="org scope mismatch")
    org = db.query(Org).filter(Org.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="org not found")
    name = payload.name.strip()
    existing = db.query(Org).filter(func.lower(Org.name) == name.lower(), Org.id != org_id).first()
    if existing:
        raise HTTPException(status_code=409, detail="workspace name is already in use")
    old_name = org.name
    org.name = name
    emit(
        db,
        "org.renamed",
        {"old_name": old_name, "new_name": name, "id": org.id},
        actor_of(user),
        {"org_id": org.id},
        {"reason": "workspace renamed"},
    )
    db.commit()
    db.refresh(org)
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
        str(user.id), {"email": user.email, "role": user.role, "org_id": user.org_id, "auth_method": "password"}
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


@router.post("/password")
def change_password(payload: PasswordChangeIn, request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Allow verified SSO/first-run sessions to set a local password; password sessions must re-authenticate."""
    authorization = request.headers.get("authorization", "")
    access_token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else authorization.strip()
    try:
        auth_method = decode_token(access_token).get("auth_method", "password")
    except Exception:
        auth_method = "password"
    if auth_method not in {"google", "saml", "bootstrap"}:
        if not payload.current_password or not verify_password(payload.current_password, user.hashed_password):
            raise HTTPException(status_code=400, detail="current password is incorrect")
    user.hashed_password = hash_password(payload.new_password)
    db.commit()
    emit(db, "auth.password.changed", {"user_id": user.id}, actor_of(user), {"org_id": user.org_id}, {"reason": "user changed password"})
    return {"ok": True, "detail": "password updated"}


@router.get("/me", response_model=UserOut)
def me(user=Depends(get_current_user)):
    return _user_out(user)


@router.get("/users", response_model=list[UserOut])
def list_users(org_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="admin/manager only")
    if user.org_id != org_id:
        raise HTTPException(status_code=403, detail="org scope mismatch")
    return db.query(User).filter(User.org_id == org_id).order_by(User.id.asc()).all()


@router.post("/bootstrap", response_model=dict, status_code=201)
def bootstrap(payload: WorkspaceBootstrap, db: Session = Depends(get_db)):
    """Create a new workspace once; never issue an existing tenant's admin token."""
    if not settings.allow_bootstrap:
        raise HTTPException(status_code=403, detail="workspace setup is disabled")
    name = payload.name.strip()
    if len(name) < 2:
        raise HTTPException(status_code=422, detail="workspace name must contain at least 2 characters")
    existing = db.query(Org).filter(func.lower(Org.name) == name.lower()).first()
    if existing:
        raise HTTPException(status_code=409, detail="workspace already exists; sign in or ask its administrator")
    if payload.email and db.query(User).filter(func.lower(User.email) == str(payload.email).lower()).first():
        raise HTTPException(status_code=409, detail="email is already registered")

    org = Org(name=name)
    db.add(org)
    db.flush()
    # Random one-time password is returned only for this newly-created workspace.
    initial_password = payload.password or _secrets.token_urlsafe(24)
    admin_email = str(payload.email) if payload.email else f"admin-{org.id}@proofos.dev"
    user = User(org_id=org.id, email=admin_email, hashed_password=hash_password(initial_password), role="admin")
    db.add(user)
    db.flush()
    emit(
        db,
        "org.created",
        {"name": org.name, "id": org.id},
        {"actor_id": "bootstrap", "actor_type": "system"},
        {"org_id": org.id},
        {"reason": "first-run workspace setup"},
    )
    emit(
        db,
        "user.created",
        {"email": user.email, "id": user.id, "role": user.role},
        {"actor_id": "bootstrap", "actor_type": "system"},
        {"org_id": org.id},
        {"reason": "first-run workspace administrator"},
    )
    db.commit()
    db.refresh(org)
    db.refresh(user)
    token = create_access_token(str(user.id), {"email": user.email, "role": user.role, "org_id": user.org_id, "auth_method": "bootstrap"})
    result: dict = {"org": {"id": org.id, "name": org.name}, "user": _user_out(user), "access_token": token}
    if not payload.password:
        result["initial_password"] = initial_password  # returned once; UI must show it immediately
    return result


@router.post("/password/reset-request")
def request_password_reset(
    payload: PasswordResetRequestIn,
    db: Session = Depends(get_db),
    _rl: None = Depends(rate_limit_password_reset),
):
    from app.services.password_reset import email_delivery_configured, send_password_reset_email

    if not email_delivery_configured():
        raise HTTPException(status_code=503, detail="Password reset email is unavailable until SMTP is configured.")
    user = db.query(User).filter(func.lower(User.email) == str(payload.email).lower()).first()
    if user:
        try:
            send_password_reset_email(user)
        except Exception:
            # Keep the response identical for known and unknown addresses.
            log.exception("Password reset email delivery failed")
    return {"detail": "If an account matches that email, a password reset link will be sent."}


@router.post("/password/reset")
def reset_password(
    payload: PasswordResetConfirmIn,
    db: Session = Depends(get_db),
    _rl: None = Depends(rate_limit_password_reset),
):
    from jwt import PyJWTError
    from app.core.security import decode_token

    try:
        claims = decode_token(payload.token)
    except PyJWTError:
        raise HTTPException(status_code=400, detail="Password reset link is invalid or expired.")
    if claims.get("purpose") != "password_reset" or not str(claims.get("sub", "")).isdigit():
        raise HTTPException(status_code=400, detail="Password reset link is invalid or expired.")
    user = db.query(User).filter(User.id == int(claims["sub"])).first()
    if not user or not verify_password_reset_token(payload.token, user):
        raise HTTPException(status_code=400, detail="Password reset link is invalid or expired.")

    user.hashed_password = hash_password(payload.new_password)
    emit(
        db,
        "auth.password.reset",
        {"user_id": user.id},
        {"actor_id": "password-reset", "actor_type": "system"},
        {"org_id": user.org_id},
        {"reason": "password reset via email"},
    )
    db.commit()
    return {"ok": True, "detail": "Password updated. You can now sign in."}
