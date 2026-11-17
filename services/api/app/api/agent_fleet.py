"""Fleet-wide agent management: health, multi-node commands, execution policy and updates."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.proof import emit
from app.core.security import actor_of, get_current_user
from app.models.models import Device, ScriptRun
from app.services import agent_jobs, kill_switch
from app.services.execution import queue_command

router = APIRouter()
STALE = dt.timedelta(minutes=5)


class Selection(BaseModel):
    device_ids: list[int] = Field(min_length=1, max_length=500)


class ExecIn(Selection):
    body: str = Field(min_length=1, max_length=20000)


class PolicyIn(Selection):
    exec_enabled: bool


def _writer(user) -> None:
    if user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="admin/manager only")


def _owned(db: Session, user, ids: list[int]) -> dict[int, Device]:
    ids = list(dict.fromkeys(ids))
    owned = {d.id: d for d in db.query(Device).filter(Device.org_id == user.org_id, Device.id.in_(ids)).all()}
    if len(owned) != len(ids):
        raise HTTPException(status_code=404, detail="one or more devices are not in this organization")
    return owned


def _version(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in v.split("."))
    except ValueError:
        return ()


@router.get("")
def fleet(db: Session = Depends(get_db), user=Depends(get_current_user)):
    release = agent_jobs.release()
    latest = release["version"] if release else ""
    now = dt.datetime.now(dt.timezone.utc)
    devices = db.query(Device).filter(Device.org_id == user.org_id).order_by(Device.hostname).all()
    active = dict(db.query(ScriptRun.device_id, func.count(ScriptRun.id)).filter(ScriptRun.org_id == user.org_id,
        ScriptRun.status.in_(["pending", "running", "cancelling"])).group_by(ScriptRun.device_id).all())
    rows = []
    for d in devices:
        seen = d.last_seen if d.last_seen is None or d.last_seen.tzinfo else d.last_seen.replace(tzinfo=dt.timezone.utc)
        installed = bool(d.agent_version)
        if not installed:
            health = "not_installed"
        elif seen is None or now - seen > STALE:
            health = "offline"
        elif d.agent_locked or not d.agent_exec_enabled:
            health = "restricted"
        else:
            health = "healthy"
        rows.append({"id": d.id, "hostname": d.hostname, "os": d.os, "device_type": d.device_type, "customer_id": d.customer_id,
            "agent_version": d.agent_version, "outdated": installed and bool(latest) and _version(d.agent_version) < _version(latest),
            "push_connected": agent_jobs.hub.connected(d.id), "last_seen": seen, "health": health,
            "locked": d.agent_locked, "exec_enabled": d.agent_exec_enabled, "spooled": d.agent_spooled,
            "active_runs": active.get(d.id, 0), "reboot_required": d.reboot_required})
    count = lambda pred: sum(1 for r in rows if pred(r))  # noqa: E731
    return {"latest_version": latest, "agents": rows, "summary": {
        "installed": count(lambda r: r["agent_version"]), "connected": count(lambda r: r["push_connected"]),
        "offline": count(lambda r: r["health"] == "offline"), "outdated": count(lambda r: r["outdated"]),
        "restricted": count(lambda r: r["health"] == "restricted"), "not_installed": count(lambda r: r["health"] == "not_installed")}}


@router.post("/exec")
def exec_many(payload: ExecIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Queue one command on many endpoints; each node gets its own signed job and run."""
    _writer(user)
    owned = _owned(db, user, payload.device_ids)
    kill_switch.require_disengaged(db)
    results = []
    for device_id in owned:
        try:
            run = queue_command(db, user.org_id, device_id, payload.body, actor_of(user))
            db.commit()
            results.append({"device_id": device_id, "hostname": owned[device_id].hostname, "ok": True, "run_id": run.id})
        except HTTPException as exc:
            db.rollback()
            results.append({"device_id": device_id, "hostname": owned[device_id].hostname, "ok": False, "error": exc.detail})
    emit(db, "agent.fleet.exec", {"device_ids": list(owned), "queued": sum(r["ok"] for r in results), "command_chars": len(payload.body)},
        actor_of(user), {"org_id": user.org_id}, {"reason": "multi-node command"})
    return {"results": results}


@router.post("/policy")
def set_policy(payload: PolicyIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Allow or forbid remote execution per endpoint, enforced by the server for every queue path."""
    _writer(user)
    owned = _owned(db, user, payload.device_ids)
    for d in owned.values():
        d.agent_exec_enabled = payload.exec_enabled
    db.commit()
    emit(db, "agent.policy.changed", {"device_ids": list(owned), "exec_enabled": payload.exec_enabled},
        actor_of(user), {"org_id": user.org_id}, {"reason": "remote execution policy"})
    return {"updated": len(owned), "exec_enabled": payload.exec_enabled}


@router.post("/update")
def update_now(payload: Selection, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Ask connected agents to check for the signed release now instead of within six hours."""
    _writer(user)
    if not agent_jobs.release():
        raise HTTPException(status_code=404, detail="no agent build is published on this server")
    owned = _owned(db, user, payload.device_ids)
    notified = [i for i in owned if agent_jobs.hub.notify(i, {"type": "update"})]
    emit(db, "agent.update.requested", {"device_ids": list(owned), "notified": notified},
        actor_of(user), {"org_id": user.org_id}, {"reason": "roll out signed agent release"})
    return {"notified": notified, "not_connected": [i for i in owned if i not in notified]}
