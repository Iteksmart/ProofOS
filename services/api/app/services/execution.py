"""Executes approved state-changing actions (remote commands, script runs)."""
from __future__ import annotations

import json
import time

from sqlalchemy.orm import Session

from app.core.proof import emit
from app.models.models import Approval, Script, ScriptRun
from app.services import kill_switch


def queue_command(db: Session, org_id: int, device_id: int, body: str, who: dict) -> ScriptRun:
    """Queue an ad-hoc shell command for a device's agent (via the script queue)."""
    kill_switch.require_disengaged(db)
    s = Script(org_id=org_id, name=f"adhoc-{int(time.time())}", body=body, version="1.0.0")
    db.add(s)
    db.flush()
    run = ScriptRun(org_id=org_id, device_id=device_id, script_id=s.id, status="pending")
    db.add(run)
    db.commit()
    db.refresh(run)
    emit(
        db,
        "command.queued",
        {"device_id": device_id, "run_id": run.id, "body": body[:200]},
        who,
        {"org_id": org_id, "device_id": device_id},
        {"reason": "remote command"},
    )
    return run


def execute_approval(db: Session, approval: Approval) -> dict:
    """Execute a pending approval's action. Assumes the approval is already committed."""
    kill_switch.require_disengaged(db)
    payload = json.loads(approval.payload or "{}")
    who = {"actor_id": approval.decided_by or "approver", "actor_type": "user"}
    if approval.kind in {"command", "upgrade"}:
        run = queue_command(db, approval.org_id, payload.get("device_id"), payload.get("body", ""), who)
        return {"run_id": run.id}
    if approval.kind == "script":
        run = ScriptRun(
            org_id=approval.org_id,
            device_id=payload.get("device_id"),
            script_id=payload.get("script_id"),
            status="pending",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        emit(
            db,
            "script.queued",
            {"script_id": run.script_id, "run_id": run.id, "device_id": run.device_id},
            who,
            {"org_id": approval.org_id, "device_id": run.device_id},
            {"reason": "approved execution"},
        )
        return {"run_id": run.id}
    return {"skipped": approval.kind}
