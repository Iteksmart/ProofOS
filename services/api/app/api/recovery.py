from datetime import datetime, timezone
import ipaddress
import json
import socket
import time
from urllib.parse import urlsplit
from typing import Literal
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.core.db import get_db
from app.core.proof import emit
from app.core.security import actor_of, get_current_user
from app.models.models import RecoveryObservation, RecoveryPolicy, ScriptRun
from app.services.recovery import evaluate, fingerprint, policy_body
from app.services.privileged import utc

router = APIRouter()


class PolicyIn(BaseModel):
    kind: Literal["http", "tcp"] = "http"
    target: str = Field(min_length=5, max_length=1000)
    expected_status: int = Field(default=200, ge=200, le=399)
    max_latency_ms: float = Field(default=3000, gt=0, le=30000, allow_inf_nan=False)
    samples_required: int = Field(default=3, ge=2, le=5)


def load_run(db, user, run_id, write=False):
    if write and user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="admin/manager only")
    query = db.query(ScriptRun).filter(ScriptRun.id == run_id, ScriptRun.org_id == user.org_id)
    row = (query.with_for_update() if write else query).first()
    if not row:
        raise HTTPException(status_code=404, detail="run not found in organization")
    return row


def validate_target(kind, target):
    try:
        parsed = urlsplit(target)
        if parsed.scheme not in ({"http", "https"} if kind == "http" else {"tcp"}) or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError()
        port = parsed.port or (443 if parsed.scheme == "https" else 80 if kind == "http" else 0)
        if not 1 <= port <= 65535:
            raise ValueError()
        for info in socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM):
            address = ipaddress.ip_address(info[4][0])
            if address.is_link_local or address.is_multicast or address.is_unspecified:
                raise ValueError()
            if address.is_loopback and get_settings().is_prod:
                raise ValueError()
        return parsed.hostname, port
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail="use an HTTP(S) or tcp://host:port target without credentials, queries, link-local or (in production) loopback addresses") from exc


def probe(policy):
    host, port = validate_target(policy.kind, policy.target)
    start = time.perf_counter()
    status = None
    try:
        if policy.kind == "http":
            with httpx.Client(timeout=3, follow_redirects=False, trust_env=False) as client:
                with client.stream("GET", policy.target) as response:
                    status = response.status_code
            passed = status == policy.expected_status
        else:
            with socket.create_connection((host, port), timeout=3):
                passed = True
        latency = round((time.perf_counter() - start) * 1000, 2)
        return {"passed": passed and latency <= policy.max_latency_ms, "latency_ms": latency, "http_status": status, "error": None}
    except (httpx.HTTPError, OSError) as exc:
        return {"passed": False, "latency_ms": round((time.perf_counter() - start) * 1000, 2), "http_status": status, "error": type(exc).__name__}


@router.get("/{run_id}")
def get_recovery(run_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return evaluate(db, load_run(db, user, run_id))


@router.put("/{run_id}")
def configure(run_id: int, payload: PolicyIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    run = load_run(db, user, run_id, True)
    validate_target(payload.kind, payload.target)
    if db.query(RecoveryPolicy).filter(RecoveryPolicy.run_id == run_id).first():
        raise HTTPException(status_code=409, detail="recovery policy is immutable; use a new execution for a different contract")
    policy = RecoveryPolicy(org_id=user.org_id, run_id=run.id, **payload.model_dump())
    db.add(policy)
    emit(db, "recovery.policy.created", policy_body(policy), actor_of(user), {"org_id": user.org_id, "device_id": run.device_id}, {"reason": "explicit recovery contract"})
    return evaluate(db, run)


@router.post("/{run_id}/sample")
def sample(run_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    run = load_run(db, user, run_id, True)
    if run.completed_at is None or run.exit_code != 0:
        raise HTTPException(status_code=409, detail="successful execution must complete before sampling")
    policy = db.query(RecoveryPolicy).filter(RecoveryPolicy.run_id == run_id, RecoveryPolicy.org_id == user.org_id).first()
    if not policy:
        raise HTTPException(status_code=409, detail="configure a recovery contract first")
    previous = db.query(RecoveryObservation).filter(RecoveryObservation.policy_id == policy.id).order_by(RecoveryObservation.id.desc()).first()
    if previous and (datetime.now(timezone.utc) - utc(previous.created_at)).total_seconds() < 1:
        raise HTTPException(status_code=429, detail="space observations at least one second apart")
    observation = {**probe(policy), "run_id": run_id, "policy_sha256": fingerprint(policy), "observed_at": datetime.now(timezone.utc).isoformat()}
    row = RecoveryObservation(org_id=user.org_id, policy_id=policy.id, payload=json.dumps(observation), proof_id="")
    db.add(row)
    # The proof and observation commit in one transaction.
    import uuid
    row.proof_id = "pending-" + uuid.uuid4().hex[:16]
    db.flush()
    record = emit(db, "recovery.observed", {"observation": observation, "observation_id": row.id}, actor_of(user), {"org_id": user.org_id, "device_id": run.device_id}, {"reason": "server-executed recovery probe"})
    row.proof_id = record.id
    db.commit()
    return evaluate(db, run)
