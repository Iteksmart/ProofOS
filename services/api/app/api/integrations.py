from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.proof import emit
from app.core.security import actor_of, get_current_user
from app.models.models import IntegrationMetric
from app.schemas.schemas import IntegrationMetricOut, MetricIn

router = APIRouter()


def _scope(user, org_id: int) -> None:
    if user.org_id != org_id:
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="org scope mismatch")


@router.post("/metrics", status_code=201)
def ingest_metrics(payload: MetricIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Ingest metrics from Datadog/Prometheus/Grafana (generic webhook)."""
    _scope(user, payload.org_id)
    count = 0
    for m in payload.metrics:
        if not isinstance(m, dict):
            continue
        db.add(
            IntegrationMetric(
                org_id=payload.org_id,
                source=payload.source,
                name=str(m.get("name", "metric")),
                value=float(m.get("value", 0)),
                host=payload.host or str(m.get("host", "")),
            )
        )
        count += 1
    db.commit()
    emit(db, "integration.metrics.ingested", {"source": payload.source, "count": count}, actor_of(user), {"org_id": payload.org_id}, {"reason": "metrics webhook"})
    return {"ingested": count}


@router.get("/metrics", response_model=list[IntegrationMetricOut])
def list_metrics(org_id: int, source: str | None = None, limit: int = Query(200, le=1000), db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, org_id)
    q = db.query(IntegrationMetric).filter(IntegrationMetric.org_id == org_id)
    if source:
        q = q.filter(IntegrationMetric.source == source)
    return q.order_by(IntegrationMetric.created_at.desc()).limit(limit).all()
