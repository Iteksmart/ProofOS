"""Fleet-level operations: plain-English device queries and bulk actions."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.proof import emit
from app.core.security import actor_of, get_current_user
from app.models.models import Device, Script
from app.schemas.schemas import DeviceOut, TicketCreate
from app.services import device_query, discovery
from app.services.execution import queue_command

router = APIRouter()
MAX_BULK = 200


@router.get("/query")
def query_devices(q: str = Query(min_length=2, max_length=300), db: Session = Depends(get_db), user=Depends(get_current_user)):
    parsed = device_query.parse(q)
    rows = device_query.apply(db, user.org_id, parsed) if parsed.understood else []
    return {
        "query": q,
        "understood": parsed.understood,
        "ignored": parsed.ignored,
        "device_ids": [d.id for d in rows],
        "devices": [DeviceOut.model_validate(d).model_dump(mode="json") for d in rows],
        "engine": "deterministic parser",
    }


class BulkIn(BaseModel):
    device_ids: list[int] = Field(min_length=1, max_length=MAX_BULK)
    action: Literal["run_script", "create_ticket", "install_software", "uninstall_software"]
    package: str | None = Field(default=None, max_length=128)
    script_id: int | None = Field(default=None, gt=0)
    title: str | None = Field(default=None, min_length=3, max_length=500)
    body: str = Field(default="", max_length=10000)
    priority: Literal["low", "normal", "high", "urgent"] = "normal"

    @model_validator(mode="after")
    def _requires(self):
        if self.action == "run_script" and not self.script_id:
            raise ValueError("script_id is required for run_script")
        if self.action == "create_ticket" and not self.title:
            raise ValueError("title is required for create_ticket")
        if self.action.endswith("_software") and not discovery.valid_package(self.package or ""):
            raise ValueError("package must be a package id such as Mozilla.Firefox or htop")
        return self


@router.post("/bulk")
def bulk_action(payload: BulkIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    ids = list(dict.fromkeys(payload.device_ids))
    if payload.action != "create_ticket" and user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="admin/manager only")
    if payload.action == "create_ticket" and user.role in {"viewer", "auditor"}:
        raise HTTPException(status_code=403, detail="read-only role")
    owned = {d.id: d for d in db.query(Device).filter(Device.org_id == user.org_id, Device.id.in_(ids)).all()}
    if len(owned) != len(ids):
        raise HTTPException(status_code=404, detail="one or more devices are not in this organization")
    if payload.action != "create_ticket":
        from app.services import kill_switch
        kill_switch.require_disengaged(db)
    if payload.action == "run_script":
        script = db.query(Script).filter(Script.id == payload.script_id, Script.org_id == user.org_id).first()
        if not script:
            raise HTTPException(status_code=404, detail="script not found in organization")
        from app.services import kill_switch
        kill_switch.require_disengaged(db)

    from app.api.scripts import queue_run
    from app.api.tickets import create_ticket

    results = []
    for device_id in ids:
        try:
            if payload.action == "run_script":
                run = queue_run(payload.script_id, device_id, db, user)
                results.append({"device_id": device_id, "ok": True, "run_id": run.id})
            elif payload.action.endswith("_software"):
                command = discovery.package_command(owned[device_id].os, payload.package, payload.action.split("_")[0])
                run = queue_command(db, user.org_id, device_id, command, actor_of(user))
                results.append({"device_id": device_id, "ok": True, "run_id": run.id, "command": command})
            else:
                ticket = create_ticket(TicketCreate(org_id=user.org_id, title=f"{owned[device_id].hostname}: {payload.title}",
                    body=payload.body, priority=payload.priority, device_id=device_id), db, user)
                results.append({"device_id": device_id, "ok": True, "ticket_id": ticket.id})
        except HTTPException as exc:
            db.rollback()
            results.append({"device_id": device_id, "ok": False, "error": exc.detail})
    succeeded = sum(r["ok"] for r in results)
    record = emit(db, "fleet.bulk_action", {"action": payload.action, "script_id": payload.script_id, "title": payload.title, "package": payload.package,
        "device_ids": ids, "succeeded": succeeded, "failed": len(ids) - succeeded}, actor_of(user),
        {"org_id": user.org_id}, {"reason": f"bulk {payload.action} on {len(ids)} endpoints"})
    return {"action": payload.action, "requested": len(ids), "succeeded": succeeded, "failed": len(ids) - succeeded,
        "results": results, "proof_id": record.id}


class DiscoverIn(BaseModel):
    device_id: int = Field(gt=0)


@router.post("/discover", status_code=201)
def discover(payload: DiscoverIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Ask one agent to report its network neighbours (ARP / neighbour table)."""
    if user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="admin/manager only")
    device = db.query(Device).filter(Device.id == payload.device_id, Device.org_id == user.org_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="device not found in organization")
    from app.models.models import ScriptRun
    from app.services import kill_switch
    kill_switch.require_disengaged(db)
    script = Script(org_id=user.org_id, name=discovery.DISCOVERY_SCRIPT, body=discovery.DISCOVERY_CMD[discovery.os_key(device.os)], version="1.0.0")
    db.add(script)
    db.flush()
    run = ScriptRun(org_id=user.org_id, device_id=device.id, script_id=script.id, status="pending")
    db.add(run)
    db.commit()
    emit(db, "fleet.discovery.queued", {"run_id": run.id, "device_id": device.id}, actor_of(user), {"org_id": user.org_id, "device_id": device.id}, {"reason": "network discovery"})
    return {"run_id": run.id, "device_id": device.id, "command": script.body}


@router.get("/discovered")
def discovered(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Neighbours seen by each agent's most recent discovery, marked managed or unmanaged."""
    from app.models.models import ScriptRun
    runs = db.query(ScriptRun, Script).join(Script, ScriptRun.script_id == Script.id).filter(
        ScriptRun.org_id == user.org_id, Script.name == discovery.DISCOVERY_SCRIPT, ScriptRun.status == "completed",
        ScriptRun.exit_code == 0).order_by(ScriptRun.id.desc()).limit(200).all()
    devices = db.query(Device).filter(Device.org_id == user.org_id).all()
    managed = {d.ip: d for d in devices if d.ip}
    hosts = {d.id: d.hostname for d in devices}
    latest: dict[int, object] = {}
    for run, _script in runs:
        latest.setdefault(run.device_id, run)
    seen: dict[str, dict] = {}
    for device_id, run in latest.items():
        for row in discovery.parse_neighbours(run.output or ""):
            entry = seen.setdefault(row["ip"], {**row, "seen_by": [], "last_seen": run.completed_at, "managed_device_id": None, "managed_hostname": None})
            entry["seen_by"].append(hosts.get(device_id, f"#{device_id}"))
            match = managed.get(row["ip"])
            if match:
                entry["managed_device_id"], entry["managed_hostname"] = match.id, match.hostname
    rows = sorted(seen.values(), key=lambda r: (r["managed_device_id"] is not None, tuple(int(x) for x in r["ip"].split("."))))
    return {"scans": len(latest), "unmanaged": sum(r["managed_device_id"] is None for r in rows), "devices": rows}
