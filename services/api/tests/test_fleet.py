"""Plain-English device queries and bulk actions."""
from __future__ import annotations

from app.services.device_query import parse


def test_parser_reports_what_it_understood_and_ignored():
    f = parse("offline Windows servers with critical alerts and disk over 90%")
    assert f.statuses == {"offline"} and f.os == ["windows"] and f.types == {"server"}
    assert f.alerts == "critical" and ("disk", ">", 90.0) in f.metrics and f.ignored == []
    f = parse("laptops named ws-jane with high memory missing patches")
    assert f.hostname == "ws-jane" and f.types == {"workstation"} and ("mem", ">=", 85.0) in f.metrics and f.patches == "any"
    assert parse("unmanaged gear not seen in 2 days").unseen_hours == 48
    assert parse("quantum flux").understood == [] and parse("quantum flux").ignored == ["quantum", "flux"]


def _setup(c, org_id):
    from app.core.db import SessionLocal
    from app.models.models import Alert, Device, Patch

    with SessionLocal() as db:
        rows = [
            Device(org_id=org_id, hostname="win-srv-01", os="Windows Server 2022", device_type="server", status="offline", cpu=20, disk=95, mem=40, agent_version="1.0"),
            Device(org_id=org_id, hostname="win-srv-02", os="Windows Server 2022", device_type="server", status="online", cpu=91, disk=30, mem=50, agent_version="1.0"),
            Device(org_id=org_id, hostname="ubuntu-ws-01", os="Ubuntu 24.04", device_type="workstation", status="online", cpu=10, disk=40, mem=88, agent_version=""),
        ]
        db.add_all(rows)
        db.flush()
        db.add(Alert(org_id=org_id, device_id=rows[0].id, kind="test", severity="critical", message="down", acked=False))
        db.add(Alert(org_id=org_id, device_id=rows[1].id, kind="test", severity="warning", message="slow", acked=False))
        db.add(Patch(org_id=org_id, device_id=rows[2].id, name="openssl", severity="critical", status="pending"))
        db.commit()
        return [d.id for d in rows]


def test_query_applies_filters_and_is_tenant_scoped(auth_client):
    c, org_id, _ = auth_client
    srv1, srv2, ws = _setup(c, org_id)
    q = lambda text: c.get("/v1/fleet/query", params={"q": text}).json()
    assert q("offline windows servers with critical alerts")["device_ids"] == [srv1]
    assert q("servers with alerts")["device_ids"] == [srv1, srv2]
    assert q("high cpu")["device_ids"] == [srv2]
    assert q("disk over 90%")["device_ids"] == [srv1]
    assert q("linux machines with critical patches")["device_ids"] == [] and q("ubuntu with critical patches")["device_ids"] == [ws]
    assert q("unmanaged workstations with high memory")["device_ids"] == [ws]
    result = q("windows gizmos")
    assert result["understood"] == ["OS: windows"] and result["ignored"] == ["gizmos"]
    nothing = q("quantum flux")
    assert nothing["understood"] == [] and nothing["device_ids"] == []  # never returns everything for an unparsed query
    assert c.get("/v1/fleet/query", params={"q": "x"}).status_code == 422

    other = c.post("/v1/auth/bootstrap", json={"name": "Other fleet tenant"}).json()
    assert c.get("/v1/fleet/query", params={"q": "servers"}, headers={"Authorization": f"Bearer {other['access_token']}"}).json()["device_ids"] == []


def test_bulk_actions_validate_scope_roles_and_record_proof(auth_client):
    c, org_id, _ = auth_client
    ids = _setup(c, org_id)
    script = c.post("/v1/scripts", json={"org_id": org_id, "name": "disk-check", "body": "df -h"}).json()

    run = c.post("/v1/fleet/bulk", json={"device_ids": ids + [ids[0]], "action": "run_script", "script_id": script["id"]})
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["requested"] == 3 and body["succeeded"] == 3 and all(r["run_id"] for r in body["results"])
    assert len(c.get(f"/v1/scripts/runs?org_id={org_id}").json()) == 3

    tickets = c.post("/v1/fleet/bulk", json={"device_ids": ids[:2], "action": "create_ticket", "title": "Investigate disk pressure", "priority": "high"}).json()
    assert tickets["succeeded"] == 2
    titles = {t["title"] for t in c.get(f"/v1/tickets?org_id={org_id}").json()}
    assert {"win-srv-01: Investigate disk pressure", "win-srv-02: Investigate disk pressure"} <= titles

    assert c.post("/v1/fleet/bulk", json={"device_ids": ids, "action": "run_script"}).status_code == 422
    assert c.post("/v1/fleet/bulk", json={"device_ids": ids, "action": "create_ticket"}).status_code == 422
    assert c.post("/v1/fleet/bulk", json={"device_ids": [], "action": "create_ticket", "title": "x x x"}).status_code == 422
    assert c.post("/v1/fleet/bulk", json={"device_ids": ids + [999999], "action": "create_ticket", "title": "Check"}).status_code == 404

    proofs = [p for p in c.get("/v1/proof?limit=200").json() if p["what"] == "fleet.bulk_action"]
    assert len(proofs) == 2

    c.post("/v1/auth/users", json={"org_id": org_id, "email": "viewer-fleet@proofos.dev", "password": "a-long-test-password", "role": "viewer"})
    viewer = {"Authorization": "Bearer " + c.post("/v1/auth/login", json={"email": "viewer-fleet@proofos.dev", "password": "a-long-test-password"}).json()["access_token"]}
    assert c.post("/v1/fleet/bulk", json={"device_ids": ids, "action": "run_script", "script_id": script["id"]}, headers=viewer).status_code == 403
    assert c.post("/v1/fleet/bulk", json={"device_ids": ids, "action": "create_ticket", "title": "Check"}, headers=viewer).status_code == 403

    other = c.post("/v1/auth/bootstrap", json={"name": "Other bulk tenant"}).json()
    foreign = {"Authorization": f"Bearer {other['access_token']}"}
    assert c.post("/v1/fleet/bulk", json={"device_ids": ids, "action": "create_ticket", "title": "Check"}, headers=foreign).status_code == 404

    assert c.post("/v1/ops/kill-switch", json={"engaged": True, "reason": "test"}).json()["engaged"] is True
    blocked = c.post("/v1/fleet/bulk", json={"device_ids": ids, "action": "run_script", "script_id": script["id"]})
    assert blocked.status_code == 409
    assert len(c.get(f"/v1/scripts/runs?org_id={org_id}").json()) == 3  # nothing was queued
