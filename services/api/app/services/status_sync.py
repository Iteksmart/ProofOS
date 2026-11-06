"""Device alive/status sync — derives online/stale/offline from heartbeat recency.

On transition to stale/offline it creates an alert (deduped) and fires the
configured notification channels (Slack / email / webhook).
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from app.core.pubsub import publish
from app.models.models import Alert, Device, DeviceMetric
from app.services.notifier import send_alert

ONLINE_AFTER_S = 180   # heartbeat within 3 min → online
STALE_AFTER_S = 600    # heartbeat within 10 min → stale


def _desired_status(dev: Device, now: dt.datetime) -> str:
    last = dev.last_seen
    if last is None:
        return "online"
    try:
        age = (now - last).total_seconds()
    except TypeError:
        age = (now.replace(tzinfo=None) - last).total_seconds()
    if age > STALE_AFTER_S:
        return "offline"
    if age > ONLINE_AFTER_S:
        return "stale"
    return "online"


def sync_device_statuses(db: Session, org_id: int | None = None) -> dict:
    """Mark stale/offline devices and raise alerts + notifications. Returns counts."""
    q = db.query(Device)
    if org_id is not None:
        q = q.filter(Device.org_id == org_id)
    devices = q.all()
    now = dt.datetime.now(dt.timezone.utc)

    changed = 0
    new_alerts: list[Alert] = []
    for dev in devices:
        # Only consider devices that have heartbeated at least once (agent enrolled).
        has_metric = db.query(DeviceMetric.id).filter(DeviceMetric.device_id == dev.id).first() is not None
        if not has_metric:
            continue
        desired = _desired_status(dev, now)
        if desired == dev.status:
            continue
        dev.status = desired
        changed += 1
        if desired in {"stale", "offline"}:
            exists = (
                db.query(Alert.id)
                .filter(Alert.org_id == dev.org_id, Alert.device_id == dev.id, Alert.kind == f"device_{desired}", Alert.acked.is_(False))
                .first()
            )
            if not exists:
                severity = "critical" if desired == "offline" else "warning"
                alert = Alert(org_id=dev.org_id, device_id=dev.id, kind=f"device_{desired}", severity=severity, message=f"{dev.hostname} is {desired}")
                db.add(alert)
                new_alerts.append(alert)
        publish({"type": "device", "device_id": dev.id, "hostname": dev.hostname, "status": dev.status, "org_id": dev.org_id})

    db.commit()
    for alert in new_alerts:
        db.refresh(alert)
        send_alert({"id": alert.id, "org_id": alert.org_id, "device_id": alert.device_id, "kind": alert.kind, "severity": alert.severity, "message": alert.message}, db)

    return {"changed": changed, "alerts": len(new_alerts)}
