from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.proof import emit
from app.core.security import actor_of, get_current_user
from app.models.models import KillSwitch
from app.services import kill_switch as ks

settings = get_settings()
router = APIRouter()


class KillSwitchIn(BaseModel):
    engaged: bool
    reason: str = ""


def _require_admin(user) -> None:
    if user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="admin/manager only")


@router.get("/kill-switch")
def get_kill_switch(db: Session = Depends(get_db), user=Depends(get_current_user)):
    row = db.query(KillSwitch).filter(KillSwitch.id == 1).first()
    return {
        "engaged": ks.engaged(db),
        "db_engaged": bool(row.engaged) if row else False,
        "env_override": settings.kill_switch,
        "reason": row.reason if row else "",
    }


@router.post("/kill-switch")
def set_kill_switch(payload: KillSwitchIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _require_admin(user)
    row = db.query(KillSwitch).filter(KillSwitch.id == 1).first()
    if not row:
        row = KillSwitch(id=1, engaged=payload.engaged, reason=payload.reason)
        db.add(row)
    else:
        row.engaged = payload.engaged
        row.reason = payload.reason
    db.commit()
    db.refresh(row)
    emit(
        db,
        "kill_switch." + ("engaged" if payload.engaged else "disengaged"),
        {"reason": payload.reason},
        actor_of(user),
        {"org_id": user.org_id},
        {"reason": "kill switch"},
    )
    return {"engaged": row.engaged, "reason": row.reason}


@router.get("/selfcheck")
def selfcheck(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Deep health of ProofOS itself: ledger integrity, anchoring, job delivery, telemetry, kill switch.

    Each check reports ok / warn / fail with the measured value, so monitoring can alert on
    specific failure modes instead of a single up/down.
    """
    import datetime as dt
    import os

    from app.core.proof import verify, verify_chain
    from app.models.models import ProofAnchor, ProofRecord, ScriptRun, TelemetryEvent
    from app.services.agent_jobs import hub

    if user.role not in {"admin", "manager", "auditor"}:
        raise HTTPException(status_code=403, detail="admin, manager or auditor only")
    now = dt.datetime.now(dt.timezone.utc)
    aware = lambda t: t if t is None or t.tzinfo else t.replace(tzinfo=dt.timezone.utc)  # noqa: E731
    checks: dict[str, dict] = {}

    recent = db.query(ProofRecord).order_by(ProofRecord.created_at.desc()).limit(500).all()
    chain = verify_chain(recent)
    head_ok = verify(recent[0])["verified"] if recent else True
    checks["ledger"] = {"status": "ok" if chain["chain_ok"] and head_ok else "fail",
        "detail": f"{chain['count']} most recent receipts linked; head signature {'valid' if head_ok else 'INVALID'}",
        "broken_ids": chain["broken_ids"][:10]}

    interval = int(os.getenv("PROOF_ANCHOR_INTERVAL_MINUTES", "60"))
    last = db.query(ProofAnchor).order_by(ProofAnchor.created_at.desc()).first()
    if interval <= 0:
        checks["anchoring"] = {"status": "warn", "detail": "independent timestamping is disabled"}
    elif not last:
        checks["anchoring"] = {"status": "warn", "detail": "no independent timestamp yet"}
    else:
        age = (now - aware(last.created_at)).total_seconds() / 60
        checks["anchoring"] = {"status": "ok" if age <= interval * 3 else "warn",
            "detail": f"last anchor {age:.0f} min ago (interval {interval} min)", "minutes": round(age)}

    stale_pending = db.query(ScriptRun).filter(ScriptRun.status == "pending", ScriptRun.created_at < now - dt.timedelta(hours=1)).count()
    stuck_running = db.query(ScriptRun).filter(ScriptRun.status.in_(["running", "cancelling"]),
        ScriptRun.started_at < now - dt.timedelta(hours=2)).count()
    checks["job_delivery"] = {"status": "ok" if not stuck_running and stale_pending < 25 else "warn",
        "detail": f"{stale_pending} jobs waiting over 1 h (agent offline?), {stuck_running} running over 2 h",
        "stale_pending": stale_pending, "stuck_running": stuck_running, "agents_connected": len(hub._sockets)}

    last_event = db.query(TelemetryEvent.received_at).order_by(TelemetryEvent.received_at.desc()).first()
    if last_event is None:
        checks["telemetry_ingest"] = {"status": "warn", "detail": "no telemetry received yet"}
    else:
        age = (now - aware(last_event[0])).total_seconds() / 60
        checks["telemetry_ingest"] = {"status": "ok" if age <= 60 else "warn", "detail": f"last event {age:.0f} min ago",
            "minutes": round(age)}

    engaged = ks.engaged(db)
    checks["kill_switch"] = {"status": "warn" if engaged else "ok", "detail": "engaged: automation halted" if engaged else "disengaged"}

    worst = "fail" if any(c["status"] == "fail" for c in checks.values()) else "warn" if any(c["status"] == "warn" for c in checks.values()) else "ok"
    return {"status": worst, "checked_at": now.isoformat(), "checks": checks}
