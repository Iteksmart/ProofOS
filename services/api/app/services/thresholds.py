"""Metric threshold alerting on agent heartbeats, with automatic resolution."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.pubsub import publish
from app.models.models import Alert, AlertThreshold, Device, DeviceMetric

LABEL = {"cpu": "CPU", "mem": "Memory", "disk": "Disk"}
RECOMMENDED = [
    {"metric": "cpu", "limit": 90.0, "samples": 3, "severity": "warning"},
    {"metric": "mem", "limit": 90.0, "samples": 3, "severity": "warning"},
    {"metric": "disk", "limit": 90.0, "samples": 1, "severity": "critical"},
]


def evaluate(db: Session, device: Device) -> list[dict]:
    """Open an alert after N consecutive samples at or above the limit; resolve it once
    the latest sample drops back below. Returns the changes made."""
    thresholds = db.query(AlertThreshold).filter(AlertThreshold.org_id == device.org_id, AlertThreshold.enabled.is_(True)).all()
    thresholds = [t for t in thresholds if not t.device_type or t.device_type == (device.device_type or "workstation")]
    if not thresholds:
        return []
    depth = max(t.samples for t in thresholds)
    samples = db.query(DeviceMetric).filter(DeviceMetric.device_id == device.id).order_by(DeviceMetric.id.desc()).limit(depth).all()
    if not samples:
        return []
    changes: list[dict] = []
    for t in thresholds:
        kind = f"threshold_{t.metric}"
        recent = [float(getattr(s, t.metric) or 0) for s in samples[: t.samples]]
        breached = len(recent) == t.samples and all(v >= t.limit for v in recent)
        open_alert = db.query(Alert).filter(Alert.org_id == device.org_id, Alert.device_id == device.id,
            Alert.kind == kind, Alert.acked.is_(False)).first()
        if breached and not open_alert:
            message = f"{device.hostname}: {LABEL[t.metric]} at {recent[0]:.0f}% (limit {t.limit:g}% for {t.samples} sample{'s' if t.samples > 1 else ''})"
            db.add(Alert(org_id=device.org_id, device_id=device.id, kind=kind, severity=t.severity, message=message, acked=False))
            changes.append({"opened": kind, "severity": t.severity, "message": message})
        elif open_alert and recent and recent[0] < t.limit:
            open_alert.acked = True
            open_alert.message = f"{open_alert.message} — resolved: {LABEL[t.metric]} back to {recent[0]:.0f}%"
            changes.append({"resolved": kind})
    if changes:
        db.commit()
        publish({"type": "alert", "device_id": device.id, "org_id": device.org_id})
    return changes
