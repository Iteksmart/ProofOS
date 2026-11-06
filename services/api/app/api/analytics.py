from __future__ import annotations

import statistics

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import get_current_user
from app.models.models import TraceSpan
from app.services.anomaly import detect_anomalies, root_cause

router = APIRouter()


def _scope(user, org_id: int) -> None:
    if user.org_id != org_id:
        raise HTTPException(status_code=403, detail="org scope mismatch")


@router.get("/anomalies")
def anomalies(org_id: int, threshold: float = 3.5, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, org_id)
    return detect_anomalies(db, org_id, threshold=threshold)


@router.get("/root-cause")
def root_cause_ep(org_id: int, device_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, org_id)
    return root_cause(db, org_id, device_id)


@router.get("/remediation-stats")
def remediation_stats(org_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, org_id)
    from app.models.models import RemediationOutcome

    outcomes = db.query(RemediationOutcome).filter(RemediationOutcome.org_id == org_id).all()
    total = len(outcomes)
    success = sum(1 for o in outcomes if o.success is True)
    failed = sum(1 for o in outcomes if o.success is False)
    pending = sum(1 for o in outcomes if o.success is None)
    return {
        "total": total,
        "success": success,
        "failed": failed,
        "pending": pending,
        "success_rate": round(success / total * 100, 1) if total else 0.0,
    }


@router.get("/traces")
def traces(org_id: int, limit: int = Query(100, le=500), db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, org_id)
    return db.query(TraceSpan).filter((TraceSpan.org_id == org_id) | (TraceSpan.org_id.is_(None))).order_by(TraceSpan.created_at.desc()).limit(limit).all()


@router.get("/apm")
def apm_summary(org_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Lightweight APM summary: request count, latency, slowest paths."""
    _scope(user, org_id)
    spans = db.query(TraceSpan).filter((TraceSpan.org_id == org_id) | (TraceSpan.org_id.is_(None))).all()
    if not spans:
        return {"enabled_note": "APM tracing is off by default — set APM_ENABLED=true to record request spans.", "spans": 0}
    durations = [s.duration_ms for s in spans]
    paths: dict[str, list[float]] = {}
    for s in spans:
        paths.setdefault(f"{s.method} {s.path}", []).append(s.duration_ms)
    slowest = sorted(paths.items(), key=lambda kv: statistics.mean(kv[1]), reverse=True)[:10]
    return {
        "spans": len(spans),
        "avg_ms": round(statistics.mean(durations), 2),
        "p95_ms": round(sorted(durations)[int(len(durations) * 0.95) - 1] if len(durations) > 1 else durations[0], 2),
        "max_ms": round(max(durations), 2),
        "slowest_paths": [{"path": p, "avg_ms": round(statistics.mean(v), 2), "count": len(v)} for p, v in slowest],
    }
