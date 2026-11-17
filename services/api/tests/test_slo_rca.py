"""Service level objectives and probable-cause ranking on the dependency graph."""
from __future__ import annotations


def _spans(org_id, service, total, errors, duration=50.0):
    from app.core.db import SessionLocal
    from app.models.models import TelemetryEvent

    with SessionLocal() as db:
        for i in range(total):
            db.add(TelemetryEvent(org_id=org_id, kind="span", service=service, name="GET /",
                severity="ERROR" if i < errors else "INFO", duration_ms=duration))
        db.commit()


def test_slo_burn_alerts_once_and_recovers(auth_client):
    c, org_id, _ = auth_client
    created = c.put("/v1/slos", json={"service": "checkout", "max_error_rate": 0.05, "max_p95_ms": 300, "window_minutes": 15, "min_requests": 10})
    assert created.status_code == 200 and created.json()["status"] == "insufficient_data"

    _spans(org_id, "checkout", 40, 10)  # 25% errors against a 5% objective
    states = c.post("/v1/slos/check").json()
    assert states[0]["status"] == "breaching" and states[0]["short"]["burn_rate"] == 5.0
    alert_id = states[0]["alert_id"]
    assert c.post("/v1/slos/check").json()[0]["alert_id"] == alert_id  # one page, not one per minute
    from app.models.models import Alert
    from app.core.db import SessionLocal
    with SessionLocal() as db:
        assert db.query(Alert).filter(Alert.org_id == org_id, Alert.kind == "slo_breach", Alert.acked.is_(False)).count() == 1

    # Recovery: enough healthy traffic pulls the rate under the objective, and the alert is acknowledged automatically.
    _spans(org_id, "checkout", 400, 0)
    assert c.post("/v1/slos/check").json()[0]["status"] == "ok"
    from app.core.db import SessionLocal
    from app.models.models import Alert
    with SessionLocal() as db:
        assert db.get(Alert, alert_id).acked is True

    _spans(org_id, "search", 30, 0, duration=900)
    c.put("/v1/slos", json={"service": "search", "max_p95_ms": 500, "min_requests": 10})
    search = next(s for s in c.get("/v1/slos").json() if s["service"] == "search")
    assert search["status"] == "breaching" and "p95 latency" in search["reasons"][0]
    assert c.put("/v1/slos", json={"service": "x", "max_error_rate": 0}).status_code == 422
    assert c.delete(f"/v1/slos/{search['id']}").status_code == 204


def test_probable_cause_prefers_deepest_failing_dependency(auth_client):
    c, org_id, _ = auth_client
    ids = {name: c.post("/v1/topology/services", json={"name": name}).json()["id"] for name in ("web", "api", "db", "cache")}
    for source, target in (("web", "api"), ("api", "db"), ("api", "cache")):
        assert c.post("/v1/topology/dependencies", json={"source_id": ids[source], "target_id": ids[target]}).status_code == 201
    _spans(org_id, "web", 10, 3)
    _spans(org_id, "api", 10, 6)
    _spans(org_id, "db", 10, 9)
    _spans(org_id, "cache", 10, 0)
    result = c.get(f"/v1/topology/probable-cause/{ids['web']}").json()
    names = [r["name"] for r in result["candidates"]]
    assert names[0] == "db" and result["candidates"][0]["origin"] is True
    assert "cache" not in names and set(names) == {"db", "api", "web"}
    assert c.get("/v1/topology/probable-cause/999999").status_code == 404
