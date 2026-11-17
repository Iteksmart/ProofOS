from __future__ import annotations

from datetime import datetime, timezone
import hashlib

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.proof import emit, decode_canonical, verify, public_key_hex
from app.core.security import actor_of, agent_actor, get_current_user, require_agent, verify_agent
from app.models.models import Device, Patch, ProofRecord, Script, ScriptRun
from app.schemas.schemas import RunComplete, ScriptCreate, ScriptOut, ScriptRunOut
from app.services import kill_switch

router = APIRouter()


def _scope(user, org_id: int) -> None:
    if user.org_id != org_id:
        raise HTTPException(status_code=403, detail="org scope mismatch")


@router.get("", response_model=list[ScriptOut])
def list_scripts(org_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, org_id)
    return db.query(Script).filter(Script.org_id == org_id).all()


@router.post("", response_model=ScriptOut, status_code=201)
def create_script(payload: ScriptCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, payload.org_id)
    s = Script(org_id=payload.org_id, name=payload.name, body=payload.body, version=payload.version)
    db.add(s)
    db.commit()
    db.refresh(s)
    emit(
        db,
        "script.created",
        {"name": s.name, "id": s.id, "version": s.version},
        actor_of(user),
        {"org_id": payload.org_id, "script_id": s.id},
        {"reason": "script author"},
    )
    return s


# Static routes must be declared before GET /{script_id} so FastAPI does not
# shadow GET /runs and GET /runs/pending with the {script_id} path parameter.
@router.get("/runs", response_model=list[ScriptRunOut])
def list_runs(org_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, org_id)
    return (
        db.query(ScriptRun)
        .filter(ScriptRun.org_id == org_id)
        .order_by(ScriptRun.created_at.desc())
        .limit(100)
        .all()
    )


@router.get("/runs/pending")
def pending_runs(device_id: int, db: Session = Depends(get_db), agent: None = Depends(require_agent)):
    """Agent poll — authenticated via AGENT_TOKEN (X-Agent-Token / Bearer)."""
    rows = db.query(ScriptRun).filter(ScriptRun.device_id == device_id, ScriptRun.status == "pending").all()
    jobs = []
    for r in rows:
        s = db.query(Script).filter(Script.id == r.script_id).first()
        jobs.append(
            {
                "id": r.id,
                "script_id": r.script_id,
                "device_id": r.device_id,
                "org_id": r.org_id,
                "status": r.status,
                "body": s.body if s else "",
                "name": s.name if s else "",
                "version": s.version if s else "",
            }
        )
    return jobs


@router.get("/runs/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    r = db.query(ScriptRun).filter(ScriptRun.id == run_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="run not found")
    _scope(user, r.org_id)
    s = db.query(Script).filter(Script.id == r.script_id).first()
    return {
        "id": r.id,
        "script_id": r.script_id,
        "device_id": r.device_id,
        "status": r.status,
        "output": r.output,
        "exit_code": r.exit_code,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        "script_name": s.name if s else "",
    }


@router.post("/runs/{run_id}/complete")
def complete_run(run_id: int, payload: RunComplete, db: Session = Depends(get_db), request: Request = None):
    r = db.query(ScriptRun).filter(ScriptRun.id == run_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="run not found")
    verify_agent(request, db, r.device_id)
    if r.completed_at is not None:
        if r.exit_code != payload.exit_code or r.output != (payload.output or "")[:20000]:
            raise HTTPException(status_code=409, detail="run already completed with a different result")
        return {"ok": True, "run_id": r.id}
    if r.status in {"cancelled", "expired"} and r.started_at is None:
        raise HTTPException(status_code=409, detail=f"run {r.status}")
    r.status = "cancelled" if r.status == "cancelling" else "completed"
    r.output = (payload.output or "")[:20000]
    r.exit_code = payload.exit_code
    r.completed_at = datetime.now(timezone.utc)
    script = db.query(Script).filter(Script.id == r.script_id).first()
    patches = []
    if script and script.name.startswith("patch-deploy:"):
        try:
            patch_ids = [int(x) for x in script.name.removeprefix("patch-deploy:").split(",") if x]
        except ValueError:
            patch_ids = []
        if patch_ids:
            patches = db.query(Patch).filter(Patch.id.in_(patch_ids), Patch.org_id == r.org_id, Patch.device_id == r.device_id).all()
            for patch in patches:
                patch.status = "installed" if payload.exit_code == 0 else "failed"
    scan_result = None
    if script and script.name == "patch-scan" and payload.exit_code == 0:
        from app.services import patch_scan

        scan_result = patch_scan.apply(db, r.org_id, r.device_id, patch_scan.parse(r.output))
    db.flush()
    emit(
        db,
        "script.completed",
        {"run_id": r.id, "device_id": r.device_id, "exit_code": r.exit_code,
         "command_sha256": hashlib.sha256((script.body if script else "").encode()).hexdigest(),
         "output_sha256": hashlib.sha256(r.output.encode()).hexdigest(), "output_truncated": len(payload.output or "") > 20000},
        agent_actor(r.device_id),
        {"org_id": r.org_id, "device_id": r.device_id},
        {"reason": "agent exec"},
    )
    if patches:
        emit(
            db,
            "patch.deployment.completed",
            {"patch_ids": [p.id for p in patches], "run_id": r.id, "status": patches[0].status, "exit_code": r.exit_code},
            agent_actor(r.device_id),
            {"org_id": r.org_id, "device_id": r.device_id},
            {"reason": "agent-reported patch result"},
        )
    if scan_result is not None:
        emit(db, "patch.scan.completed", {"run_id": r.id, **scan_result}, agent_actor(r.device_id),
            {"org_id": r.org_id, "device_id": r.device_id}, {"reason": "agent-reported patch inventory"})
    return {"ok": True, "run_id": r.id}


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Stop a queued run before it starts, or ask the agent to kill a running one."""
    if user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="admin/manager only")
    r = db.query(ScriptRun).filter(ScriptRun.id == run_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="run not found")
    _scope(user, r.org_id)
    if r.status == "pending":
        r.status, r.completed_at = "cancelled", datetime.now(timezone.utc)
    elif r.status == "running":
        r.status = "cancelling"
    else:
        raise HTTPException(status_code=409, detail=f"run is already {r.status}")
    db.commit()
    from app.services.agent_jobs import hub

    pushed = r.status == "cancelling" and hub.notify(r.device_id, {"type": "cancel", "run_id": r.id})
    emit(db, "script.cancel.requested", {"run_id": r.id, "device_id": r.device_id, "status": r.status, "pushed": pushed},
        actor_of(user), {"org_id": r.org_id, "device_id": r.device_id}, {"reason": "operator cancelled run"})
    return {"run_id": r.id, "status": r.status, "pushed": pushed}


@router.get("/runs/{run_id}/evidence")
def run_evidence(run_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    run = db.query(ScriptRun).filter(ScriptRun.id == run_id, ScriptRun.org_id == user.org_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="run not found in organization")
    script = db.get(Script, run.script_id)
    receipts = []
    command_hash = hashlib.sha256((script.body if script else "").encode()).hexdigest()
    output_hash = hashlib.sha256(run.output.encode()).hexdigest()
    result_matches = False
    for record in db.query(ProofRecord).filter(ProofRecord.org_id == user.org_id,
            ProofRecord.what.in_(["command.queued", "script.completed"])).order_by(ProofRecord.created_at).yield_per(200):
        body = decode_canonical(record) or {}
        payload = body.get("payload", {})
        if payload.get("run_id") != run.id:
            continue
        verification = verify(record)
        if record.what == "script.completed":
            result_matches = verification["verified"] and payload.get("command_sha256") == command_hash and payload.get("output_sha256") == output_hash and payload.get("exit_code") == run.exit_code
        receipts.append({"id": record.id, "body": body, "canonical_bytes": record.canonical_bytes,
            "signature": record.signature, "prev_hash": record.prev_hash, "payload_digest": record.payload_digest, "verification": verification})
    from app.services.recovery import evaluate

    recovery = evaluate(db, run)
    return {"run_id": run.id, "device_id": run.device_id, "status": run.status, "exit_code": run.exit_code,
        "output": run.output, "command_sha256": command_hash, "output_sha256": output_hash,
        "signed_result_matches": result_matches, "public_key_hex": public_key_hex(), "receipts": receipts,
        "recovery_verified": recovery["verified"], "recovery": recovery, "trust_note": "Signatures verify recorded agent results, not endpoint integrity or service recovery. Pin the public key independently."}


@router.get("/{script_id}", response_model=ScriptOut)
def get_script(script_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    s = db.query(Script).filter(Script.id == script_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="script not found")
    _scope(user, s.org_id)
    return s


@router.post("/{script_id}/runs", response_model=ScriptRunOut, status_code=201)
def queue_run(script_id: int, device_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="admin/manager only")
    kill_switch.require_disengaged(db)
    s = db.query(Script).filter(Script.id == script_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="script not found")
    _scope(user, s.org_id)
    dev = db.query(Device).filter(Device.id == device_id, Device.org_id == s.org_id).first()
    if not dev:
        raise HTTPException(status_code=404, detail="device not found")
    run = ScriptRun(org_id=s.org_id, device_id=device_id, script_id=script_id, status="pending")
    db.add(run)
    db.commit()
    db.refresh(run)
    emit(
        db,
        "script.queued",
        {"script_id": s.id, "run_id": run.id, "device_id": device_id},
        actor_of(user),
        {"org_id": s.org_id, "device_id": device_id},
        {"reason": "manual run"},
    )
    return run


# Back-compat: POST /{id}/run?device_id=...
@router.post("/{script_id}/run", response_model=ScriptRunOut, status_code=201)
def queue_run_compat(script_id: int, device_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return queue_run(script_id, device_id, db, user)
