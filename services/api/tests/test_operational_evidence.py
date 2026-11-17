"""Topology, telemetry, privileged access grants and recovery verification."""
from __future__ import annotations

import socket
import threading
import time


TRACE = "0af7651916cd43dd8448eb211c80319c"


def _login(c, email, password):
    r = c.post("/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _user(c, org_id, email, role):
    r = c.post("/v1/auth/users", json={"org_id": org_id, "email": email, "password": "a-long-test-password", "role": role})
    assert r.status_code == 201, r.text
    return _login(c, email, "a-long-test-password")


def _otlp(c, org_id):
    r = c.post(f"/v1/integrations/connections?org_id={org_id}", json={"name": "Collector", "provider": "otlp"})
    assert r.status_code == 201, r.text
    data = r.json()
    return data["webhook_path"], {"X-Integration-Token": data["token"]}, data["id"]


def _span(span_id, parent="", name="op", error=False):
    return {"traceId": TRACE, "spanId": span_id, "parentSpanId": parent, "name": name,
        "startTimeUnixNano": "1794000000000000000", "endTimeUnixNano": "1794000000250000000",
        "status": {"code": 2, "message": "upstream timeout"} if error else {"code": 1}}


def _resource_spans(service, spans):
    return {"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": service}}]}, "scopeSpans": [{"spans": spans}]}


def test_topology_graph_impact_and_scoping(auth_client):
    c, org_id, _ = auth_client
    device = c.post("/v1/devices", json={"org_id": org_id, "hostname": "db-host", "os": "Linux"}).json()
    web = c.post("/v1/topology/services", json={"name": "web"}).json()
    api = c.post("/v1/topology/services", json={"name": "api"}).json()
    db_ = c.post("/v1/topology/services", json={"name": "database", "device_id": device["id"]}).json()
    assert c.post("/v1/topology/services", json={"name": "web"}).status_code == 409
    assert c.post("/v1/topology/services", json={"name": "ghost", "device_id": 99999}).status_code == 404
    assert c.post("/v1/topology/dependencies", json={"source_id": web["id"], "target_id": api["id"]}).status_code == 201
    assert c.post("/v1/topology/dependencies", json={"source_id": api["id"], "target_id": db_["id"]}).status_code == 201
    assert c.post("/v1/topology/dependencies", json={"source_id": api["id"], "target_id": db_["id"]}).status_code == 409
    assert c.post("/v1/topology/dependencies", json={"source_id": api["id"], "target_id": api["id"]}).status_code == 422

    graph = c.get("/v1/topology").json()
    assert {n["name"] for n in graph["nodes"]} == {"web", "api", "database"}
    assert len(graph["edges"]) == 2
    by_name = {n["name"]: n for n in graph["nodes"]}
    assert by_name["web"]["health"] == "unknown"  # no evidence is never reported as healthy
    assert by_name["database"]["health"] in {"healthy", "degraded", "down", "unknown"}
    assert any("db-host" in e for e in by_name["database"]["evidence"])

    impact = c.get(f"/v1/topology/impact/{db_['id']}").json()
    assert [d["name"] for d in impact["dependents"]] == ["api", "web"]
    assert impact["dependencies"] == []
    assert [d["name"] for d in c.get(f"/v1/topology/impact/{web['id']}").json()["dependencies"]] == ["api", "database"]

    viewer = _user(c, org_id, "viewer-topology@proofos.dev", "viewer")
    assert c.post("/v1/topology/services", json={"name": "nope"}, headers=viewer).status_code == 403
    assert c.get("/v1/topology", headers=viewer).status_code == 200

    other = c.post("/v1/auth/bootstrap", json={"name": "Other topology tenant"}).json()
    foreign = {"Authorization": f"Bearer {other['access_token']}"}
    assert c.get("/v1/topology", headers=foreign).json() == {"nodes": [], "edges": []}
    assert c.get(f"/v1/topology/impact/{db_['id']}", headers=foreign).status_code == 404
    assert c.delete(f"/v1/topology/services/{db_['id']}", headers=foreign).status_code == 404

    assert c.delete(f"/v1/topology/services/{api['id']}").status_code == 200
    assert c.get("/v1/topology").json()["edges"] == []


def test_otlp_ingest_redacts_secrets_and_derives_dependencies(auth_client):
    c, org_id, _ = auth_client
    path, headers, connection_id = _otlp(c, org_id)
    logs = {"resourceLogs": [{"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "checkout"}}]},
        "scopeLogs": [{"logRecords": [
            {"timeUnixNano": "1794000000000000000", "severityText": "ERROR", "traceId": TRACE, "spanId": "b7ad6b7169203331",
             "body": {"stringValue": "payment failed password=hunter2secret order 1794000000000"},
             "attributes": [{"key": "http.status_code", "value": {"intValue": "502"}}]},
            {"severityNumber": 9, "body": {"stringValue": "request accepted"}}]}]}]}
    assert c.post(f"{path}/v1/logs", json=logs).status_code == 401
    assert c.post(f"{path}/v1/logs", json=logs, headers={"X-Integration-Token": "wrong"}).status_code == 401
    assert c.post(f"{path}/v1/logs", json={"resourceLogs": "bad"}, headers=headers).status_code == 422
    assert c.post(f"{path}/v1/logs", json={"resourceLogs": []}, headers=headers).status_code == 422
    r = c.post(f"{path}/v1/logs", json=logs, headers=headers)
    assert r.status_code == 202 and r.json()["accepted"] == 2, r.text

    errors = c.get("/v1/telemetry/events?severity=errors").json()
    assert len(errors) == 1
    assert "hunter2secret" not in errors[0]["body"] and "[redacted:generic_secret]" in errors[0]["body"]
    assert "1794000000000" in errors[0]["body"]  # numeric identifiers survive redaction
    assert errors[0]["attributes"]["http.status_code"] == "502"
    assert len(c.get("/v1/telemetry/events?q=accepted").json()) == 1
    assert c.get("/v1/telemetry/events?q=%25").json() == []

    # Parent in one batch, child in a later batch from another service.
    first = {"resourceSpans": [_resource_spans("gateway", [_span("aaaaaaaaaaaaaaa1", name="GET /checkout")])]}
    second = {"resourceSpans": [
        _resource_spans("checkout", [_span("aaaaaaaaaaaaaaa2", parent="aaaaaaaaaaaaaaa1", name="charge")]),
        _resource_spans("payments", [_span("aaaaaaaaaaaaaaa3", parent="aaaaaaaaaaaaaaa2", name="POST /charge", error=True)])]}
    assert c.post(f"{path}/v1/traces", json=first, headers=headers).json()["new_dependencies"] == []
    derived = c.post(f"{path}/v1/traces", json=second, headers=headers).json()
    assert {(e["source"], e["target"]) for e in derived["new_dependencies"]} == {("gateway", "checkout"), ("checkout", "payments")}
    assert c.post(f"{path}/v1/traces", json=second, headers=headers).json()["new_dependencies"] == []  # edges are not duplicated
    bad = {"resourceSpans": [_resource_spans("x", [{"traceId": "zz", "spanId": "1"}])]}
    assert c.post(f"{path}/v1/traces", json=bad, headers=headers).status_code == 422

    graph = c.get("/v1/topology").json()
    names = {n["id"]: n["name"] for n in graph["nodes"]}
    assert {(names[e["source_id"]], names[e["target_id"]], e["origin"]) for e in graph["edges"]} == {
        ("gateway", "checkout", "trace"), ("checkout", "payments", "trace")}
    payments = next(n for n in graph["nodes"] if n["name"] == "payments")
    assert payments["health"] == "down"  # every recent span for the service failed
    assert [d["name"] for d in c.get(f"/v1/topology/impact/{payments['id']}").json()["dependents"]] == ["checkout", "gateway"]

    trace = c.get(f"/v1/telemetry/traces/{TRACE}").json()
    assert len(trace["spans"]) >= 3 and len(trace["logs"]) == 1
    assert trace["spans"][0]["duration_ms"] == 250.0
    stats = {s["service"]: s for s in c.get("/v1/telemetry/services").json()["services"]}
    assert stats["payments"]["error_rate"] == 1.0 and stats["checkout"]["log_errors"] == 1
    assert c.get("/v1/telemetry/traces/not-hex").status_code == 422

    proofs = [p["what"] for p in c.get("/v1/proof?limit=200").json()]
    assert proofs.count("topology.dependency.observed") == 2

    # OTLP credentials are not accepted by the alert webhook, and disabling revokes ingest.
    assert c.post(f"/v1/integrations/webhooks/{connection_id}", json={"alerts": []}, headers=headers).status_code == 400
    assert c.post(f"/v1/integrations/connections/{connection_id}/disable").status_code == 200
    assert c.post(f"{path}/v1/logs", json=logs, headers=headers).status_code == 401

    other = c.post("/v1/auth/bootstrap", json={"name": "Other telemetry tenant"}).json()
    foreign = {"Authorization": f"Bearer {other['access_token']}"}
    assert c.get("/v1/telemetry/events", headers=foreign).json() == []
    assert c.get(f"/v1/telemetry/traces/{TRACE}", headers=foreign).status_code == 404
    assert c.get("/v1/telemetry/services", headers=foreign).json()["services"] == []


def test_scoped_expiring_access_grants(auth_client):
    c, org_id, _ = auth_client
    device = c.post("/v1/devices", json={"org_id": org_id, "hostname": "grant-host", "os": "Linux"}).json()
    secret = c.post("/v1/secrets", json={"org_id": org_id, "name": "db-pass", "value": "s3cret-value", "category": "database"}).json()
    engineer = _user(c, org_id, "engineer-grants@proofos.dev", "engineer")
    manager = _user(c, org_id, "manager-grants@proofos.dev", "manager")
    command = f"/v1/devices/{device['id']}/command"

    assert c.post(command, json={"body": "uptime"}, headers=engineer).status_code == 403
    assert c.post(f"/v1/secrets/{secret['id']}/reveal", headers=engineer).status_code == 403

    request = {"capability": "device_command", "target_id": device["id"], "command": "uptime", "reason": "Investigating load alert INC-1042", "minutes": 5}
    assert c.post("/v1/access", json={**request, "reason": "short"}, headers=engineer).status_code == 422
    assert c.post("/v1/access", json={**request, "command": ""}, headers=engineer).status_code == 422
    assert c.post("/v1/access", json={**request, "target_id": 99999}, headers=engineer).status_code == 404
    grant = c.post("/v1/access", json=request, headers=engineer)
    assert grant.status_code == 201, grant.text
    grant = grant.json()
    assert grant["status"] == "pending"
    assert c.post(command, json={"body": "uptime"}, headers=engineer).status_code == 403  # pending is not access
    assert c.post(f"/v1/access/{grant['id']}/approve", headers=engineer).status_code == 403

    approved = c.post(f"/v1/access/{grant['id']}/approve", headers=manager)
    assert approved.status_code == 200 and approved.json()["status"] == "approved" and approved.json()["expires_at"]
    assert c.post(f"/v1/access/{grant['id']}/approve", headers=manager).status_code == 409
    assert c.post(command, json={"body": "uptime"}, headers=engineer).status_code == 200
    assert c.post(command, json={"body": "rm -rf /"}, headers=engineer).status_code == 403  # only the approved command
    assert c.post(f"/v1/secrets/{secret['id']}/reveal", headers=engineer).status_code == 403  # only the approved capability

    # Expiry is enforced at use time.
    from app.core.db import SessionLocal
    from app.models.models import AccessGrant
    import datetime as dt
    with SessionLocal() as db:
        db.get(AccessGrant, grant["id"]).expires_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)
        db.commit()
    assert c.post(command, json={"body": "uptime"}, headers=engineer).status_code == 403
    assert next(g for g in c.get("/v1/access", headers=engineer).json() if g["id"] == grant["id"])["status"] == "expired"

    vault = c.post("/v1/access", json={"capability": "vault_reveal", "target_id": secret["id"], "reason": "Rotate the database credential"}, headers=engineer).json()
    assert c.post(f"/v1/access/{vault['id']}/approve", headers=manager).status_code == 200
    assert c.post(f"/v1/secrets/{secret['id']}/reveal", headers=engineer).json()["value"] == "s3cret-value"
    assert c.post(f"/v1/access/{vault['id']}/revoke", headers=manager).status_code == 200
    assert c.post(f"/v1/secrets/{secret['id']}/reveal", headers=engineer).status_code == 403

    # A privileged user cannot approve their own request.
    own = c.post("/v1/access", json=request, headers=manager).json()
    assert c.post(f"/v1/access/{own['id']}/approve", headers=manager).status_code == 403
    assert c.post(f"/v1/access/{own['id']}/deny").status_code == 200

    assert {g["id"] for g in c.get("/v1/access", headers=engineer).json()} == {grant["id"], vault["id"]}
    assert len(c.get("/v1/access").json()) == 3
    proofs = [p["what"] for p in c.get("/v1/proof?limit=200").json()]
    for expected in ("privileged.grant.requested", "privileged.grant.approved", "privileged.grant.used", "privileged.grant.revoked", "privileged.grant.denied"):
        assert expected in proofs

    other = c.post("/v1/auth/bootstrap", json={"name": "Other grants tenant"}).json()
    foreign = {"Authorization": f"Bearer {other['access_token']}"}
    assert c.get("/v1/access", headers=foreign).json() == []
    assert c.post(f"/v1/access/{grant['id']}/revoke", headers=foreign).status_code == 404


def _completed_run(c, org_id, exit_code=0):
    device = c.post("/v1/devices", json={"org_id": org_id, "hostname": f"recovery-{exit_code}-{time.time_ns()}", "os": "Linux"}).json()
    plan = c.post(f"/v1/ai/remediate/{device['id']}", json={"action": "restart_nginx"}).json()
    run_id = c.post(f"/v1/approvals/{plan['approval_id']}/approve").json()["result"]["run_id"]
    return device, run_id


def _complete(c, device, run_id, exit_code=0):
    r = c.post(f"/v1/scripts/runs/{run_id}/complete", headers={"X-Agent-Token": device["device_secret"]}, json={"output": "active", "exit_code": exit_code})
    assert r.status_code == 200, r.text


def test_recovery_requires_fresh_consecutive_signed_probes(auth_client, monkeypatch):
    c, org_id, _ = auth_client
    monkeypatch.setattr("app.services.llm.get_llm_client", lambda: None)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    port = listener.getsockname()[1]
    stop = threading.Event()

    def accept():
        listener.settimeout(0.2)
        while not stop.is_set():
            try:
                listener.accept()[0].close()
            except OSError:
                pass

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    try:
        device, run_id = _completed_run(c, org_id)
        policy = {"kind": "tcp", "target": f"tcp://127.0.0.1:{port}", "samples_required": 2}
        assert c.get(f"/v1/recovery/{run_id}").json()["state"] == "unconfigured"
        assert c.put(f"/v1/recovery/{run_id}", json={"kind": "http", "target": "http://user:pw@example.com/"}).status_code == 422
        assert c.put(f"/v1/recovery/{run_id}", json={"kind": "tcp", "target": "tcp://169.254.169.254:80"}).status_code == 422
        configured = c.put(f"/v1/recovery/{run_id}", json=policy)
        assert configured.status_code == 200 and configured.json()["state"] == "awaiting_execution", configured.text
        assert c.put(f"/v1/recovery/{run_id}", json=policy).status_code == 409  # the contract is immutable
        assert c.post(f"/v1/recovery/{run_id}/sample").status_code == 409  # nothing to verify before execution

        _complete(c, device, run_id)
        assert c.get(f"/v1/scripts/runs/{run_id}/evidence").json()["recovery_verified"] is False
        first = c.post(f"/v1/recovery/{run_id}/sample")
        assert first.status_code == 200 and first.json()["state"] == "pending", first.text  # one passing probe is not recovery
        assert c.post(f"/v1/recovery/{run_id}/sample").status_code == 429
        time.sleep(1.1)
        second = c.post(f"/v1/recovery/{run_id}/sample").json()
        assert second["state"] == "healthy" and second["verified"] is True
        assert all(o["passed"] and o["intact"] for o in second["observations"])
        evidence = c.get(f"/v1/scripts/runs/{run_id}/evidence").json()
        assert evidence["recovery_verified"] is True and evidence["recovery"]["state"] == "healthy"

        # Tampering with a stored observation invalidates the evidence.
        from app.core.db import SessionLocal
        from app.models.models import RecoveryObservation
        with SessionLocal() as db:
            row = db.query(RecoveryObservation).order_by(RecoveryObservation.id.desc()).first()
            row.payload = row.payload.replace('"passed": true', '"passed": false')
            db.commit()
        tampered = c.get(f"/v1/recovery/{run_id}").json()
        assert tampered["state"] == "evidence_invalid" and tampered["verified"] is False

        viewer = _user(c, org_id, "viewer-recovery@proofos.dev", "viewer")
        assert c.post(f"/v1/recovery/{run_id}/sample", headers=viewer).status_code == 403
        other = c.post("/v1/auth/bootstrap", json={"name": "Other recovery tenant"}).json()
        assert c.get(f"/v1/recovery/{run_id}", headers={"Authorization": f"Bearer {other['access_token']}"}).status_code == 404
    finally:
        stop.set()
        thread.join(timeout=2)
        listener.close()


def test_recovery_reports_failed_probe_and_failed_execution(auth_client, monkeypatch):
    c, org_id, _ = auth_client
    monkeypatch.setattr("app.services.llm.get_llm_client", lambda: None)
    closed = socket.socket()
    closed.bind(("127.0.0.1", 0))
    port = closed.getsockname()[1]
    closed.close()

    device, run_id = _completed_run(c, org_id)
    assert c.put(f"/v1/recovery/{run_id}", json={"kind": "tcp", "target": f"tcp://127.0.0.1:{port}", "samples_required": 2}).status_code == 200
    _complete(c, device, run_id)
    failed = c.post(f"/v1/recovery/{run_id}/sample").json()
    assert failed["state"] == "failed" and failed["verified"] is False
    assert failed["observations"][0]["passed"] is False and failed["observations"][0]["error"]

    device2, run2 = _completed_run(c, org_id, exit_code=1)
    assert c.put(f"/v1/recovery/{run2}", json={"kind": "tcp", "target": f"tcp://127.0.0.1:{port}"}).status_code == 200
    _complete(c, device2, run2, exit_code=1)
    assert c.get(f"/v1/recovery/{run2}").json()["state"] == "execution_unverified"
    assert c.post(f"/v1/recovery/{run2}/sample").status_code == 409
