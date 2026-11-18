"""Deep self-check reports specific failure modes."""
from __future__ import annotations


def test_selfcheck_reports_ledger_jobs_and_detects_tampering(auth_client):
    c, org_id, _ = auth_client
    dev = c.post("/v1/devices", json={"org_id": org_id, "hostname": "selfcheck-host"}).json()
    report = c.get("/v1/ops/selfcheck").json()
    assert report["checks"]["ledger"]["status"] == "ok"
    assert set(report["checks"]) == {"ledger", "anchoring", "job_delivery", "telemetry_ingest", "kill_switch"}
    assert report["status"] in {"ok", "warn"}

    from app.core.db import SessionLocal
    from app.models.models import ProofRecord
    with SessionLocal() as db:
        newest = db.query(ProofRecord).order_by(ProofRecord.created_at.desc()).first()
        newest.prev_hash = "f" * 64
        db.commit()
    broken = c.get("/v1/ops/selfcheck").json()
    assert broken["status"] == "fail" and broken["checks"]["ledger"]["status"] == "fail"

    viewer = c.post("/v1/auth/users", json={"org_id": org_id, "email": "viewer-selfcheck@proofos.dev", "password": "a-long-test-password", "role": "viewer"})
    token = c.post("/v1/auth/login", json={"email": "viewer-selfcheck@proofos.dev", "password": "a-long-test-password"}).json()["access_token"]
    assert c.get("/v1/ops/selfcheck", headers={"Authorization": f"Bearer {token}"}).status_code == 403
    assert dev["id"]
