from __future__ import annotations

import hashlib
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, HTTPException, Request
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db

settings = get_settings()


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode()


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode(), hashed.encode())
    except (ValueError, TypeError):
        return False


def create_access_token(subject: str, extra: dict | None = None) -> str:
    payload = {
        "sub": subject,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algo)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algo])


def _bearer_token(request: Request) -> str | None:
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth:
        return None
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return auth.strip()


def get_current_user(request: Request, db: Session = Depends(get_db)):
    """Require a valid JWT. Returns User or raises 401."""
    token = _bearer_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Missing Authorization: Bearer <token>")
    try:
        claims = decode_token(token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    sub = claims.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    from app.models.models import User

    user = db.query(User).filter(User.id == int(sub) if str(sub).isdigit() else sub).first() if str(sub).isdigit() else None
    if user is None and str(sub).isdigit():
        raise HTTPException(status_code=401, detail="User not found")
    if user is None:
        # Fallback: token subject may be email in legacy clients
        user = db.query(User).filter(User.email == str(sub)).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def get_optional_user(request: Request, db: Session = Depends(get_db)):
    token = _bearer_token(request)
    if not token:
        return None
    try:
        claims = decode_token(token)
    except JWTError:
        return None
    sub = claims.get("sub")
    if not sub or not str(sub).isdigit():
        return None
    from app.models.models import User

    return db.query(User).filter(User.id == int(sub)).first()


def require_role(*roles: str):
    def _guard(user=Depends(get_current_user)):
        if user.role not in roles:
            raise HTTPException(status_code=403, detail=f"Requires role: {', '.join(roles)}")
        return user

    return _guard


def actor_of(user) -> dict:
    return {
        "actor_id": user.id,
        "actor_type": "user",
        "email": user.email,
        "role": user.role,
    }


def agent_actor(device_id: int) -> dict:
    return {"actor_id": f"agent:{device_id}", "actor_type": "agent"}


def _agent_token_from_request(request: Request) -> str | None:
    provided = request.headers.get("X-Agent-Token")
    if provided:
        return provided.strip()
    return _bearer_token(request)


def verify_agent(request: Request, db: Session, device_id: int | None = None) -> None:
    """Authenticate an agent call via a global AGENT_TOKEN or a per-device secret.

    Precedence:
      1. A configured AGENT_TOKEN always works (bootstrap/ops).
      2. If the device has a secret_hash, the presented token must match it.
      3. Auth is only enforced when AGENT_TOKEN is set or ENV=production;
         otherwise (development/legacy) the endpoint is open.
    """
    presented = _agent_token_from_request(request)
    auth_enabled = bool(settings.agent_token) or settings.is_prod
    if settings.agent_token and presented == settings.agent_token:
        return
    if device_id is not None:
        from app.models.models import Device

        dev = db.query(Device).filter(Device.id == device_id).first()
        if dev and dev.secret_hash:
            if presented and hashlib.sha256(presented.encode()).hexdigest() == dev.secret_hash:
                return
            if auth_enabled:
                raise HTTPException(status_code=401, detail="invalid device token")
    if auth_enabled:
        raise HTTPException(status_code=401, detail="invalid agent token")
    # Development/legacy — no auth configured.


def require_agent(request: Request, db: Session = Depends(get_db)) -> None:
    """Dependency for agent endpoints; resolves device_id from path or query."""
    raw = request.path_params.get("device_id") or request.query_params.get("device_id")
    device_id: int | None = None
    if raw is not None:
        try:
            device_id = int(raw)
        except (TypeError, ValueError):
            device_id = None
    verify_agent(request, db, device_id)


class SlidingWindowLimiter:
    """In-process sliding-window rate limiter (single-worker; scale via Redis)."""

    def __init__(self, max_calls: int, window_seconds: float) -> None:
        self.max_calls = max_calls
        self.window = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.max_calls:
                return False
            q.append(now)
            return True


login_limiter = SlidingWindowLimiter(max_calls=10, window_seconds=60.0)


def rate_limit_login(request: Request) -> None:
    key = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        key = forwarded.split(",")[0].strip()
    if not login_limiter.allow(key):
        raise HTTPException(status_code=429, detail="too many login attempts, try again later")
