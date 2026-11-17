"""Resource-scoped, expiring authorization for otherwise non-privileged users."""
from datetime import datetime, timezone
import hashlib
import hmac
from fastapi import HTTPException
from app.core.proof import emit
from app.core.security import actor_of
from app.models.models import AccessGrant


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def authorize(db, user, capability, target_id, command=""):
    if user.role in {"admin", "manager"}:
        return
    grants = db.query(AccessGrant).filter(AccessGrant.org_id == user.org_id, AccessGrant.requester_id == user.id,
        AccessGrant.capability == capability, AccessGrant.target_id == target_id, AccessGrant.status == "approved").all()
    for grant in grants:
        if not grant.expires_at or utc(grant.expires_at) <= datetime.now(timezone.utc):
            continue
        if capability == "device_command" and not hmac.compare_digest(hashlib.sha256(command.encode()).digest(), hashlib.sha256(grant.command.encode()).digest()):
            continue
        emit(db, "privileged.grant.used", {"grant_id": grant.id, "capability": capability, "target_id": target_id}, actor_of(user), {"org_id": user.org_id}, {"reason": grant.reason})
        return
    raise HTTPException(status_code=403, detail="requires admin/manager or an active scoped access grant")
