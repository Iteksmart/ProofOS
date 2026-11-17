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
from app.services import device_query

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
    action: Literal["run_script", "create_ticket"]
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
        return self


@router.post("/bulk")
def bulk_action(payload: BulkIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    ids = list(dict.fromkeys(payload.device_ids))
    if payload.action == "run_script" and user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="admin/manager only")
    if payload.action == "create_ticket" and user.role in {"viewer", "auditor"}:
        raise HTTPException(status_code=403, detail="read-only role")
    owned = {d.id: d for d in db.query(Device).filter(Device.org_id == user.org_id, Device.id.in_(ids)).all()}
    if len(owned) != len(ids):
        raise HTTPException(status_code=404, detail="one or more devices are not in this organization")
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
            else:
                ticket = create_ticket(TicketCreate(org_id=user.org_id, title=f"{owned[device_id].hostname}: {payload.title}",
                    body=payload.body, priority=payload.priority, device_id=device_id), db, user)
                results.append({"device_id": device_id, "ok": True, "ticket_id": ticket.id})
        except HTTPException as exc:
            db.rollback()
            results.append({"device_id": device_id, "ok": False, "error": exc.detail})
    succeeded = sum(r["ok"] for r in results)
    record = emit(db, "fleet.bulk_action", {"action": payload.action, "script_id": payload.script_id, "title": payload.title,
        "device_ids": ids, "succeeded": succeeded, "failed": len(ids) - succeeded}, actor_of(user),
        {"org_id": user.org_id}, {"reason": f"bulk {payload.action} on {len(ids)} endpoints"})
    return {"action": payload.action, "requested": len(ids), "succeeded": succeeded, "failed": len(ids) - succeeded,
        "results": results, "proof_id": record.id}
