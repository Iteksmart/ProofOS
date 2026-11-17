"""Service level objectives evaluated against OTLP spans, with burn-rate alerting."""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from app.models.models import Alert, ServiceSlo, TelemetryEvent

_ERRORS = {"ERROR", "FATAL", "CRITICAL"}
SLO_ALERT = "slo_breach"


def _p95(durations: list[float]) -> float | None:
    if not durations:
        return None
    ordered = sorted(durations)
    return round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 2)


def evaluate(db: Session, slo: ServiceSlo, now: dt.datetime | None = None) -> dict:
    """Burn rate = observed error rate / allowed error rate. Above 1.0 the error budget is being spent too fast."""
    now = now or dt.datetime.now(dt.timezone.utc)
    windows = {"short": slo.window_minutes, "long": slo.window_minutes * 4}
    result: dict = {"id": slo.id, "service": slo.service, "max_error_rate": slo.max_error_rate, "max_p95_ms": slo.max_p95_ms,
        "window_minutes": slo.window_minutes, "min_requests": slo.min_requests}
    for label, minutes in windows.items():
        rows = db.query(TelemetryEvent.severity, TelemetryEvent.duration_ms).filter(TelemetryEvent.org_id == slo.org_id,
            TelemetryEvent.service == slo.service, TelemetryEvent.kind == "span",
            TelemetryEvent.received_at >= now - dt.timedelta(minutes=minutes)).all()
        errors = sum((s or "").upper() in _ERRORS for s, _ in rows)
        rate = errors / len(rows) if rows else None
        result[label] = {"minutes": minutes, "requests": len(rows), "errors": errors, "error_rate": round(rate, 4) if rate is not None else None,
            "burn_rate": round(rate / slo.max_error_rate, 2) if rate is not None and slo.max_error_rate > 0 else None,
            "p95_ms": _p95([d or 0.0 for _, d in rows])}
    short, long = result["short"], result["long"]
    reasons = []
    if short["requests"] < slo.min_requests:
        result["status"] = "insufficient_data"
        reasons.append(f"{short['requests']} requests in {slo.window_minutes} min; {slo.min_requests} needed to judge")
    else:
        # Multi-window rule (Google SRE workbook): alert only when both windows burn, so a single blip does not page.
        if (short["burn_rate"] or 0) >= 1 and (long["burn_rate"] or 0) >= 1:
            reasons.append(f"error rate {short['error_rate']:.2%} is {short['burn_rate']}x the {slo.max_error_rate:.2%} objective")
        if slo.max_p95_ms and (short["p95_ms"] or 0) > slo.max_p95_ms:
            reasons.append(f"p95 latency {short['p95_ms']} ms exceeds {slo.max_p95_ms:g} ms")
        result["status"] = "breaching" if reasons else "ok"
    result["reasons"] = reasons
    return result


def check(db: Session, org_id: int) -> list[dict]:
    """Raise one alert per breaching SLO and acknowledge it automatically once the SLO recovers."""
    from app.core.proof import emit

    results = []
    for slo in db.query(ServiceSlo).filter(ServiceSlo.org_id == org_id).all():
        state = evaluate(db, slo)
        tag = f"[SLO {slo.service}]"
        open_alert = db.query(Alert).filter(Alert.org_id == org_id, Alert.kind == SLO_ALERT, Alert.acked.is_(False),
            Alert.message.startswith(tag)).first()
        if state["status"] == "breaching" and not open_alert:
            alert = Alert(org_id=org_id, kind=SLO_ALERT, severity="critical", message=f"{tag} " + "; ".join(state["reasons"]))
            db.add(alert)
            db.commit()
            emit(db, "slo.breached", {"service": slo.service, "alert_id": alert.id, "reasons": state["reasons"]},
                {"actor_id": "system:slo", "actor_type": "system"}, {"org_id": org_id}, {"reason": "error budget burn"})
            state["alert_id"] = alert.id
        elif state["status"] == "ok" and open_alert:
            open_alert.acked = True
            db.commit()
            emit(db, "slo.recovered", {"service": slo.service, "alert_id": open_alert.id},
                {"actor_id": "system:slo", "actor_type": "system"}, {"org_id": org_id}, {"reason": "objective met again"})
        elif open_alert:
            state["alert_id"] = open_alert.id
        results.append(state)
    return results
