"""AIOps: robust anomaly detection (MAD) and root-cause correlation."""
from __future__ import annotations

import statistics

from sqlalchemy.orm import Session

from app.models.models import Alert, Device, DeviceMetric, ScriptRun, Ticket


def _modified_z(values: list[float]) -> list[float]:
    """Robust modified z-score using median absolute deviation (Iglewicz & Hoaglin)."""
    median = statistics.median(values)
    mad = statistics.median([abs(v - median) for v in values])
    if mad == 0:
        mad = 1e-6
    return [0.6745 * (v - median) / mad for v in values]


def detect_anomalies(db: Session, org_id: int, threshold: float = 3.5, window: int = 30) -> list[dict]:
    """Flag recent metric points whose robust modified z-score exceeds the threshold (MAD-based)."""
    devices = db.query(Device).filter(Device.org_id == org_id).all()
    out: list[dict] = []
    for dev in devices:
        metrics = (
            db.query(DeviceMetric)
            .filter(DeviceMetric.device_id == dev.id)
            .order_by(DeviceMetric.created_at.desc())
            .limit(window)
            .all()
        )
        for field in ("cpu", "disk", "mem"):
            values = [getattr(m, field) for m in metrics if getattr(m, field) is not None]
            if len(values) < 5:
                continue
            zs = _modified_z(values)
            latest = metrics[0]
            z = zs[0]  # latest point's robust z-score
            if abs(z) >= threshold:
                out.append(
                    {
                        "device_id": dev.id,
                        "hostname": dev.hostname,
                        "metric": field,
                        "value": getattr(latest, field),
                        "median": round(statistics.median(values), 1),
                        "robust_z": round(z, 2),
                        "severity": "warning" if abs(z) < 5 else "critical",
                    }
                )
    return out


def root_cause(db: Session, org_id: int, device_id: int) -> dict:
    """Correlate a device's recent events to suggest a likely root cause."""
    alerts = db.query(Alert).filter(Alert.org_id == org_id, Alert.device_id == device_id).order_by(Alert.created_at.desc()).limit(5).all()
    runs = db.query(ScriptRun).filter(ScriptRun.org_id == org_id, ScriptRun.device_id == device_id).order_by(ScriptRun.created_at.desc()).limit(5).all()
    tickets = db.query(Ticket).filter(Ticket.org_id == org_id, Ticket.device_id == device_id).order_by(Ticket.created_at.desc()).limit(5).all()

    events = []
    for a in alerts:
        events.append({"type": "alert", "detail": f"{a.kind} ({a.severity}): {a.message[:80]}"})
    for r in runs:
        events.append({"type": "script_run", "detail": f"script #{r.script_id} status={r.status} exit={r.exit_code}"})
    for t in tickets:
        events.append({"type": "ticket", "detail": f"#{t.id} {t.title} ({t.status})"})

    suggestion = "No correlated events — anomaly is isolated (metric-specific)."
    if alerts:
        suggestion = f"Likely cause: {alerts[0].kind} alert — {alerts[0].message[:80]}"
    elif runs and any(r.exit_code not in (None, 0) for r in runs):
        suggestion = "Likely cause: a recent script run failed (see script run history)."
    elif tickets:
        suggestion = f"Likely cause: an open ticket — #{tickets[0].id} {tickets[0].title}"

    return {"device_id": device_id, "events": events, "suggestion": suggestion}
