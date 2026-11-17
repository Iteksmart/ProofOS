"""Known vulnerabilities in installed software, from OSV."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.proof import emit
from app.core.security import actor_of, get_current_user
from app.models.models import Device, Patch, VulnerabilityFinding
from app.services import vulnerabilities

router = APIRouter()


@router.post("/scan")
def run_scan(db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="admin/manager only")
    try:
        result = vulnerabilities.scan(db, user.org_id)
    except Exception as exc:  # noqa: BLE001 - surface an unreachable OSV as a clear error
        raise HTTPException(status_code=502, detail=f"vulnerability database unavailable: {type(exc).__name__}") from exc
    emit(db, "vulnerability.scan.completed", result, actor_of(user), {"org_id": user.org_id}, {"reason": "match installed software to OSV"})
    return result


@router.get("")
def list_findings(status: str = Query("open", pattern="^(open|resolved|all)$"), severity: str | None = Query(None, max_length=20),
        device_id: int | None = None, db: Session = Depends(get_db), user=Depends(get_current_user)):
    q = db.query(VulnerabilityFinding).filter(VulnerabilityFinding.org_id == user.org_id)
    if status != "all":
        q = q.filter(VulnerabilityFinding.status == status)
    if severity:
        q = q.filter(VulnerabilityFinding.severity == severity)
    if device_id:
        q = q.filter(VulnerabilityFinding.device_id == device_id)
    rows = q.limit(2000).all()
    rows.sort(key=lambda r: (vulnerabilities._RANK.get(r.severity, 9), r.package, r.vuln_id))
    hosts = {d.id: d.hostname for d in db.query(Device).filter(Device.org_id == user.org_id).all()}
    open_patches = {(p.device_id, p.name) for p in db.query(Patch).filter(Patch.org_id == user.org_id, Patch.status.in_(["pending", "failed"])).all()}
    counts = {s: 0 for s in vulnerabilities.SEVERITIES}
    for r in db.query(VulnerabilityFinding).filter(VulnerabilityFinding.org_id == user.org_id, VulnerabilityFinding.status == "open").all():
        counts[r.severity if r.severity in counts else "unknown"] += 1
    return {"counts": counts, "findings": [{"id": r.id, "device_id": r.device_id, "hostname": hosts.get(r.device_id, "?"),
        "package": r.package, "version": r.version, "ecosystem": r.ecosystem, "vuln_id": r.vuln_id, "aliases": json.loads(r.aliases or "[]"),
        "summary": r.summary, "severity": r.severity, "fixed_version": r.fixed_version, "status": r.status,
        "patch_pending": (r.device_id, r.package) in open_patches, "first_seen": r.first_seen, "last_seen": r.last_seen} for r in rows]}
