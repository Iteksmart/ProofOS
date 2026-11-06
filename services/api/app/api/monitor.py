from __future__ import annotations

import socket
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.proof import emit
from app.core.security import actor_of, get_current_user
from app.models.models import Alert, Device, MonitorCheck
from app.schemas.schemas import AlertOut, CheckCreate, CheckOut
from app.services.notifier import send_alert

router = APIRouter()


def _scope(user, org_id: int) -> None:
    if user.org_id != org_id:
        raise HTTPException(status_code=403, detail="org scope mismatch")


def _run_check(kind: str, target: str, timeout: float = 3.0) -> tuple[str, float]:
    """Execute a real HTTP or TCP/port check. Returns (status, latency_ms)."""
    kind = (kind or "port").lower()
    target = (target or "").strip()
    start = time.perf_counter()
    try:
        if kind == "http":
            url = target or "http://localhost/"
            r = httpx.get(url, timeout=timeout, follow_redirects=True)
            ms = (time.perf_counter() - start) * 1000
            status = "ok" if r.status_code < 400 else "warning" if r.status_code < 500 else "critical"
            return status, round(ms, 1)
        # port / tcp / snmp / ping fall back to a TCP connect.
        # "snmp" targets UDP port 161 (SNMP agent reachability; full OID polling is roadmap).
        host, _, port = target.partition(":")
        if not host:
            return "unknown", 0.0
        default_port = 161 if kind == "snmp" else 80
        port_i = int(port) if port else default_port
        with socket.create_connection((host, port_i), timeout=timeout):
            ms = (time.perf_counter() - start) * 1000
            return "ok", round(ms, 1)
    except Exception:
        return "critical", 0.0


@router.get("", response_model=list[CheckOut])
def list_checks(org_id: int, limit: int = Query(100, le=500), db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, org_id)
    return db.query(MonitorCheck).filter(MonitorCheck.org_id == org_id).order_by(MonitorCheck.created_at.desc()).limit(limit).all()


@router.post("", response_model=CheckOut, status_code=201)
def record_check(payload: CheckCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, payload.org_id)
    dev = db.query(Device).filter(Device.id == payload.device_id, Device.org_id == payload.org_id).first()
    if not dev:
        raise HTTPException(status_code=404, detail="device not found")
    c = MonitorCheck(
        org_id=payload.org_id,
        device_id=payload.device_id,
        kind=payload.kind,
        target=payload.target or "",
        status=payload.status,
        latency_ms=payload.latency_ms,
        threshold_ms=payload.threshold_ms,
    )
    db.add(c)
    alert = None
    if payload.status not in {"ok", "warning"}:
        alert = Alert(
            org_id=payload.org_id,
            device_id=payload.device_id,
            kind=payload.kind,
            severity="warning" if payload.status == "warning" else "critical",
            message=f"Monitor {payload.kind}={payload.status} latency={payload.latency_ms}ms target={payload.target}",
        )
        db.add(alert)
    db.commit()
    db.refresh(c)
    emit(
        db,
        "monitor.check",
        {"device_id": c.device_id, "kind": c.kind, "status": c.status, "latency_ms": c.latency_ms},
        actor_of(user),
        {"org_id": c.org_id, "device_id": c.device_id},
        {"reason": "monitor check"},
    )
    if alert:
        send_alert(
            {"id": alert.id, "org_id": alert.org_id, "device_id": alert.device_id, "kind": alert.kind,
             "severity": alert.severity, "message": alert.message},
            db,
        )
    return c


@router.post("/run")
def run_checks(org_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Run a reachability check for every device in the org (real TCP connect)."""
    _scope(user, org_id)
    devices = db.query(Device).filter(Device.org_id == org_id).all()
    results: list[dict] = []
    alerts: list[Alert] = []
    for dev in devices:
        target = f"{dev.ip}:80" if dev.ip else ""
        status, latency = _run_check("port", target)
        c = MonitorCheck(org_id=org_id, device_id=dev.id, kind="port", target=target, status=status, latency_ms=latency)
        db.add(c)
        results.append({"device_id": dev.id, "hostname": dev.hostname, "status": status, "latency_ms": latency})
        if status not in {"ok", "warning"}:
            a = Alert(
                org_id=org_id,
                device_id=dev.id,
                kind="port",
                severity="critical",
                message=f"{dev.hostname} unreachable at {target or '(no ip)'}",
            )
            db.add(a)
            alerts.append(a)
    db.commit()
    for a in alerts:
        db.refresh(a)
        send_alert({"id": a.id, "org_id": a.org_id, "device_id": a.device_id, "kind": a.kind, "severity": a.severity, "message": a.message}, db)
    emit(
        db,
        "monitor.run",
        {"org_id": org_id, "devices_checked": len(results)},
        actor_of(user),
        {"org_id": org_id},
        {"reason": "run checks"},
    )
    return {"checked": len(results), "results": results}


@router.get("/summary")
def summary(org_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, org_id)
    checks = db.query(MonitorCheck).filter(MonitorCheck.org_id == org_id).all()
    ok = sum(1 for c in checks if c.status == "ok")
    fail = [c for c in checks if c.status != "ok"]
    avg_lat = (sum(c.latency_ms for c in checks) / len(checks)) if checks else 0.0
    devices = db.query(Device).filter(Device.org_id == org_id).all()
    offline = sum(1 for d in devices if (d.status or "online") != "online")
    return {
        "checks": len(checks),
        "checks_ok": ok,
        "checks_fail": len(fail),
        "avg_latency_ms": avg_lat,
        "devices": len(devices),
        "devices_offline": offline,
    }


@router.get("/alerts", response_model=list[AlertOut])
def list_alerts(org_id: int, limit: int = Query(100, le=500), db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, org_id)
    return db.query(Alert).filter(Alert.org_id == org_id).order_by(Alert.created_at.desc()).limit(limit).all()


@router.post("/alerts/{alert_id}/ack")
def ack_alert(alert_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    a = db.query(Alert).filter(Alert.id == alert_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="alert not found")
    _scope(user, a.org_id)
    a.acked = True
    db.commit()
    db.refresh(a)
    emit(
        db,
        "alert.acked",
        {"alert_id": a.id},
        actor_of(user),
        {"org_id": a.org_id},
        {"reason": "ack"},
    )
    return a
