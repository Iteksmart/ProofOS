"""Agent v2 protocol: signed jobs, push channel, run lifecycle and releases."""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import hmac
import json

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal, get_db
from app.core.proof import emit, public_key_hex
from app.core.security import agent_actor, require_agent, verify_agent
from app.models.models import Device, ScriptRun
from app.services import agent_jobs

router = APIRouter()


class OutputIn(BaseModel):
    chunk: str = Field(max_length=65536)


def _run_for_agent(db: Session, request: Request, run_id: int) -> ScriptRun:
    run = db.get(ScriptRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    verify_agent(request, db, run.device_id)
    return run


@router.get("/server-key")
def server_key():
    """Public. Agents pin this key at enrollment and verify every job against it."""
    return {"algorithm": "ed25519", "key_id": "ed25519:proofos-1", "public_key": public_key_hex(),
            "job_purpose": agent_jobs.JOB_PURPOSE}


@router.get("/jobs")
def jobs(device_id: int, db: Session = Depends(get_db), agent: None = Depends(require_agent)):
    return {"jobs": agent_jobs.pending_jobs(db, device_id), "push_connected": agent_jobs.hub.connected(device_id)}


@router.post("/runs/{run_id}/start")
def start(run_id: int, request: Request, db: Session = Depends(get_db)):
    run = _run_for_agent(db, request, run_id)
    if run.status in {"cancelled", "expired"}:
        raise HTTPException(status_code=409, detail=f"run {run.status}")
    if run.status == "pending":
        run.status, run.started_at = "running", dt.datetime.now(dt.timezone.utc)
        db.commit()
        from app.core.pubsub import publish

        publish({"type": "run.status", "org_id": run.org_id, "run_id": run.id, "device_id": run.device_id, "status": "running"})
    elif run.status not in {"running", "cancelling"}:
        raise HTTPException(status_code=409, detail="run already finished")
    return {"run_id": run.id, "status": run.status}


@router.post("/runs/{run_id}/output")
def output(run_id: int, payload: OutputIn, request: Request, db: Session = Depends(get_db)):
    run = _run_for_agent(db, request, run_id)
    if run.status not in {"running", "cancelling"}:
        raise HTTPException(status_code=409, detail="run is not running")
    agent_jobs.append_output(db, run, payload.chunk)
    return {"cancel": run.status == "cancelling"}


@router.get("/release")
def release():
    info = agent_jobs.release()
    if not info:
        raise HTTPException(status_code=404, detail="no agent build is published on this server")
    return info


@router.get("/download")
def download():
    if not agent_jobs.DIST.exists():
        raise HTTPException(status_code=404, detail="no agent build is published on this server")
    return FileResponse(agent_jobs.DIST, media_type="application/zip", filename="proofos-agent.pyz")


def _token_valid(db: Session, device_id: int, token: str) -> bool:
    dev = db.query(Device).filter(Device.id == device_id).first()
    if not dev or not token:
        return False
    if dev.secret_hash:
        return hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), dev.secret_hash)
    shared = get_settings().agent_token
    return bool(shared) and hmac.compare_digest(token, shared)


def _ws_output(device_id: int, run_id: int, chunk: str) -> None:
    with SessionLocal() as db:
        run = db.get(ScriptRun, run_id)
        if run and run.device_id == device_id and run.status in {"running", "cancelling"}:
            agent_jobs.append_output(db, run, chunk)


def _ws_hello(device_id: int, info: dict) -> None:
    with SessionLocal() as db:
        dev = db.get(Device, device_id)
        if dev:
            dev.agent_version = str(info.get("version", ""))[:50] or dev.agent_version
            dev.status, dev.last_seen = "online", dt.datetime.now(dt.timezone.utc)
            db.commit()
            emit(db, "agent.connected", {"device_id": device_id, "version": dev.agent_version,
                "capabilities": [str(c)[:40] for c in info.get("capabilities", [])][:20]},
                agent_actor(device_id), {"org_id": dev.org_id, "device_id": device_id}, {"reason": "agent push channel opened"})


@router.websocket("/ws")
async def agent_socket(ws: WebSocket):
    """Push channel. The server sends {type: jobs|cancel}; the agent streams output and pings."""
    try:
        device_id = int(ws.query_params.get("device_id", "0"))
    except ValueError:
        device_id = 0
    token = ws.headers.get("x-agent-token", "")
    with SessionLocal() as db:
        ok = device_id > 0 and _token_valid(db, device_id, token)
    if not ok:
        await ws.close(code=1008)
        return
    await ws.accept()
    agent_jobs.hub.attach(device_id, ws, asyncio.get_running_loop())
    try:
        await ws.send_text(json.dumps({"type": "jobs"}))  # pick up anything queued while offline
        while True:
            raw = await ws.receive_text()
            if len(raw) > 70000:
                continue
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            kind = msg.get("type")
            if kind == "hello":
                await asyncio.to_thread(_ws_hello, device_id, msg)
            elif kind == "output" and isinstance(msg.get("run_id"), int) and isinstance(msg.get("chunk"), str):
                await asyncio.to_thread(_ws_output, device_id, msg["run_id"], msg["chunk"][:65536])
            elif kind == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        pass
    finally:
        agent_jobs.hub.detach(device_id, ws)
