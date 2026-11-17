"""Patch policies, alert thresholds, customers and billing, and AI ticket assist."""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from app.services import patching


def _login(c, org_id, email, role):
    c.post("/v1/auth/users", json={"org_id": org_id, "email": email, "password": "a-long-test-password", "role": role})
    token = c.post("/v1/auth/login", json={"email": email, "password": "a-long-test-password"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _foreign(c, name):
    other = c.post("/v1/auth/bootstrap", json={"name": name}).json()
    return {"Authorization": f"Bearer {other['access_token']}"}


# ---------------------------------------------------------------- patching

def test_maintenance_window_logic():
    policy = SimpleNamespace(window_days="[0]", window_start_hour=22, window_end_hour=4)  # Monday 22:00 → Tuesday 04:00 UTC
    monday = dt.datetime(2026, 11, 16, tzinfo=dt.timezone.utc)
    assert patching.in_window(policy, monday.replace(hour=23))
    assert patching.in_window(policy, monday.replace(hour=2) + dt.timedelta(days=1))  # early Tuesday belongs to Monday's window
    assert not patching.in_window(policy, monday.replace(hour=2))  # early Monday belongs to Sunday, not selected
    assert not patching.in_window(policy, monday.replace(hour=12))
    day = SimpleNamespace(window_days="[2]", window_start_hour=9, window_end_hour=17)
    assert patching.in_window(day, monday.replace(hour=10) + dt.timedelta(days=2))
    assert not patching.in_window(day, monday.replace(hour=17) + dt.timedelta(days=2))
    assert patching.next_window_start(policy, monday.replace(hour=12)) == monday.replace(hour=22)


def test_patch_policy_approval_window_deployment_and_completion(auth_client):
    c, org_id, _ = auth_client
    win = c.post("/v1/devices", json={"org_id": org_id, "hostname": "pp-win", "os": "Windows 11", "device_type": "workstation"}).json()
    srv = c.post("/v1/devices", json={"org_id": org_id, "hostname": "pp-srv", "os": "Ubuntu 24.04", "device_type": "server"}).json()
    mk = lambda dev, name, sev, cat="os": c.post("/v1/patches", json={"org_id": org_id, "device_id": dev["id"], "name": name, "severity": sev, "category": cat}).json()
    crit = mk(win, "2026-11 Cumulative Update (KB5050001)", "critical", "security")
    low = mk(win, "Vendor Driver [Vendor.Driver]", "low")
    rejected = mk(win, "Optional feature (KB5050009)", "critical")
    vague = mk(win, "Some driver", "critical")
    srv_patch = mk(srv, "openssl", "critical", "security")

    assert c.post("/v1/patching/approvals", json={"patch_ids": [rejected["id"]], "decision": "reject"}).json()["approval"] == "rejected"
    always_open = {"name": "Workstations nightly", "auto_approve": ["critical"], "device_types": ["workstation"],
        "window_days": [0, 1, 2, 3, 4, 5, 6], "window_start_hour": 0, "window_end_hour": 0, "reboot": "if_required"}
    assert c.post("/v1/patching/policies", json={**always_open, "window_days": []}).status_code == 422
    policy = c.post("/v1/patching/policies", json=always_open)
    assert policy.status_code == 201, policy.text
    policy = policy.json()
    assert policy["window_open"] is True

    preview = c.get(f"/v1/patching/policies/{policy['id']}/preview").json()
    assert {p["id"] for p in preview["devices"][0]["patches"]} == {crit["id"], vague["id"]}  # low not auto-approved, rejected excluded, server out of scope

    assert c.post("/v1/patching/approvals", json={"patch_ids": [low["id"]], "decision": "approve"}).status_code == 200
    run = c.post(f"/v1/patching/policies/{policy['id']}/run", json={}).json()
    assert run["ran"] is True and len(run["runs"]) == 1
    assert [s["patch_id"] for s in run["skipped"]] == [vague["id"]]  # no KB or package id: never guessed
    assert sorted(run["runs"][0]["patch_ids"]) == sorted([crit["id"], low["id"]])  # one agent run covers both patches
    statuses = {p["id"]: (p["status"], p["approval"]) for p in c.get(f"/v1/patches?org_id={org_id}").json()}
    assert statuses[crit["id"]] == ("deploying", "approved") and statuses[rejected["id"]] == ("pending", "rejected")
    assert statuses[srv_patch["id"]] == ("pending", "unreviewed")

    run_id = run["runs"][0]["run_id"]
    script = next(r for r in c.get(f"/v1/scripts/runs?org_id={org_id}").json() if r["id"] == run_id)
    body = c.get(f"/v1/scripts/{script['script_id']}").json()["body"]
    import base64
    assert body.startswith("powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand ")
    decoded = base64.b64decode(body.split()[-1]).decode("utf-16-le")
    assert "Microsoft.Update.Session" in decoded and "RebootPending" in decoded
    assert "$approved = @('KB5050001')" in decoded and "winget upgrade --id Vendor.Driver --exact" in decoded
    assert "KB5050009" not in decoded and "--all" not in decoded  # the rejected patch is never installed
    assert c.post(f"/v1/patches/{rejected['id']}/deploy").status_code == 409
    assert c.post(f"/v1/patches/{vague['id']}/deploy").status_code == 422
    assert c.post(f"/v1/scripts/runs/{run_id}/complete", headers={"X-Agent-Token": win["device_secret"]}, json={"output": "ok", "exit_code": 0}).status_code == 200
    statuses = {p["id"]: p["status"] for p in c.get(f"/v1/patches?org_id={org_id}").json()}
    assert statuses[crit["id"]] == "installed" and statuses[low["id"]] == "installed"

    compliance = c.get("/v1/patching/compliance").json()
    rows = {r["hostname"]: r for r in compliance["devices"]}
    assert rows["pp-srv"]["critical"] == 1 and rows["pp-srv"]["compliant"] is False
    assert rows["pp-win"]["pending"] == 2 and compliance["awaiting_approval"] == 2  # rejected patch still pending; server patch unreviewed

    closed = {**always_open, "name": "Never open", "window_days": [0], "window_start_hour": 1, "window_end_hour": 2}
    p2 = c.post("/v1/patching/policies", json=closed).json()
    if not p2["window_open"]:
        assert c.post(f"/v1/patching/policies/{p2['id']}/run", json={}).json()["ran"] is False

    proofs = [p["what"] for p in c.get("/v1/proof?limit=300").json()]
    for expected in ("patch.policy.created", "patch.policy.run", "patch.deployment.queued", "patch.deployment.completed", "patch.approval.rejected"):
        assert expected in proofs

    viewer = _login(c, org_id, "viewer-patching@proofos.dev", "viewer")
    assert c.post(f"/v1/patching/policies/{policy['id']}/run", json={"force": True}, headers=viewer).status_code == 403
    foreign = _foreign(c, "Other patching tenant")
    assert c.get(f"/v1/patching/policies/{policy['id']}/preview", headers=foreign).status_code == 404
    assert c.post("/v1/patching/approvals", json={"patch_ids": [srv_patch["id"]], "decision": "approve"}, headers=foreign).status_code == 404
    assert c.get("/v1/patching/compliance", headers=foreign).json()["total_devices"] == 0


def test_scheduler_runs_once_per_window_and_respects_kill_switch(auth_client):
    c, org_id, _ = auth_client
    dev = c.post("/v1/devices", json={"org_id": org_id, "hostname": "sched", "os": "Ubuntu", "device_type": "server"}).json()
    c.post("/v1/patches", json={"org_id": org_id, "device_id": dev["id"], "name": "kernel", "severity": "critical"})
    c.post("/v1/patching/policies", json={"name": "Always", "auto_approve": ["critical"], "window_start_hour": 0, "window_end_hour": 0})
    from app.core.db import SessionLocal

    c.post("/v1/ops/kill-switch", json={"engaged": True, "reason": "freeze"})
    with SessionLocal() as db:
        assert patching.run_due_policies(db) == 0
    assert c.get(f"/v1/patches?org_id={org_id}").json()[0]["status"] == "pending"
    c.post("/v1/ops/kill-switch", json={"engaged": False, "reason": "thaw"})
    with SessionLocal() as db:
        assert patching.run_due_policies(db) == 1
        assert patching.run_due_policies(db) == 0  # cooldown: once per window
    assert c.get(f"/v1/patches?org_id={org_id}").json()[0]["status"] == "deploying"


def test_heartbeat_records_reboot_required(auth_client):
    c, org_id, _ = auth_client
    dev = c.post("/v1/devices", json={"org_id": org_id, "hostname": "reboot-host", "os": "Ubuntu"}).json()
    agent = {"X-Agent-Token": dev["device_secret"]}
    c.post(f"/v1/devices/{dev['id']}/heartbeat", headers=agent, json={"cpu": 5, "mem": 5, "disk": 5, "reboot_required": True})
    assert c.get(f"/v1/devices/{dev['id']}").json()["reboot_required"] is True
    c.post(f"/v1/devices/{dev['id']}/heartbeat", headers=agent, json={"cpu": 5, "mem": 5, "disk": 5})  # older agents: unchanged
    assert c.get(f"/v1/devices/{dev['id']}").json()["reboot_required"] is True
    assert c.get("/v1/patching/compliance").json()["reboot_required"] == 1


# ---------------------------------------------------------------- thresholds

def test_thresholds_open_after_consecutive_samples_and_auto_resolve(auth_client):
    c, org_id, _ = auth_client
    dev = c.post("/v1/devices", json={"org_id": org_id, "hostname": "hot-host", "os": "Ubuntu", "device_type": "server"}).json()
    agent = {"X-Agent-Token": dev["device_secret"]}
    created = c.post("/v1/thresholds/recommended")
    assert created.status_code == 201 and {t["metric"] for t in created.json()} == {"cpu", "mem", "disk"}
    assert c.post("/v1/thresholds/recommended").json() == []  # idempotent
    beat = lambda cpu, disk=10: c.post(f"/v1/devices/{dev['id']}/heartbeat", headers=agent, json={"cpu": cpu, "mem": 10, "disk": disk})
    alerts = lambda: [a for a in c.get(f"/v1/monitor/alerts?org_id={org_id}").json() if a["kind"].startswith("threshold_")]

    beat(95); beat(97)
    assert alerts() == []  # two samples are not enough for a 3-sample CPU rule
    beat(96)
    open_ = [a for a in alerts() if not a["acked"]]
    assert len(open_) == 1 and open_[0]["kind"] == "threshold_cpu" and "96%" in open_[0]["message"]
    beat(99)
    assert len([a for a in alerts() if not a["acked"]]) == 1  # no duplicate while still breached
    beat(20)
    cpu = [a for a in alerts() if a["kind"] == "threshold_cpu"]
    assert cpu[0]["acked"] is True and "resolved" in cpu[0]["message"]

    beat(10, disk=95)
    disk = [a for a in alerts() if a["kind"] == "threshold_disk"]
    assert disk and disk[0]["severity"] == "critical"  # single-sample disk rule

    t = c.get("/v1/thresholds").json()[0]
    assert c.put(f"/v1/thresholds/{t['id']}", json={**t, "limit": 150}).status_code == 422
    viewer = _login(c, org_id, "viewer-thresholds@proofos.dev", "viewer")
    assert c.post("/v1/thresholds", json={"metric": "cpu", "limit": 50}, headers=viewer).status_code == 403
    foreign = _foreign(c, "Other threshold tenant")
    assert c.get("/v1/thresholds", headers=foreign).json() == []
    assert c.delete(f"/v1/thresholds/{t['id']}", headers=foreign).status_code == 404


# ---------------------------------------------------------------- customers and billing

def test_customers_contracts_billing_and_signed_invoices(auth_client):
    c, org_id, _ = auth_client
    acme = c.post("/v1/customers", json={"name": "Dunder Mifflin", "domain": "dundermifflin.com"})
    assert acme.status_code == 201
    acme = acme.json()
    assert c.post("/v1/customers", json={"name": "dunder mifflin"}).status_code == 409
    globex = c.post("/v1/customers", json={"name": "Globex"}).json()
    assert c.post(f"/v1/customers/{acme['id']}/contacts", json={"name": "Michael Scott", "email": "michael@dundermifflin.com", "role": "Regional Manager"}).status_code == 201

    d1 = c.post("/v1/devices", json={"org_id": org_id, "hostname": "dm-ws-01", "customer_id": acme["id"]}).json()
    d2 = c.post("/v1/devices", json={"org_id": org_id, "hostname": "dm-ws-02"}).json()
    assert c.post(f"/v1/customers/{acme['id']}/devices", json={"device_ids": [d2["id"]]}).json()["assigned"] == 1
    assert c.post("/v1/devices", json={"org_id": org_id, "hostname": "x", "customer_id": 99999}).status_code == 404

    ticket = c.post("/v1/tickets", json={"org_id": org_id, "title": "Printer jam on floor 2", "device_id": d1["id"]}).json()
    assert ticket["customer_id"] == acme["id"]  # inherited from the endpoint
    other_ticket = c.post("/v1/tickets", json={"org_id": org_id, "title": "Globex email", "customer_id": globex["id"]}).json()
    unassigned = c.post("/v1/tickets", json={"org_id": org_id, "title": "Internal task"}).json()
    for tid, minutes, billable in ((ticket["id"], 150, True), (ticket["id"], 30, False), (other_ticket["id"], 60, True), (unassigned["id"], 45, True)):
        assert c.post("/v1/time", json={"org_id": org_id, "ticket_id": tid, "minutes": minutes, "billable": billable}).status_code == 201

    assert c.put(f"/v1/customers/{acme['id']}/contract", json={"kind": "retainer", "monthly_fee": 500, "included_hours": 1, "hourly_rate": 120, "per_device_fee": 15}).status_code == 200
    assert c.put(f"/v1/customers/{globex['id']}/contract", json={"kind": "hourly", "hourly_rate": 100}).status_code == 200

    period = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m")
    preview = c.get(f"/v1/billing/preview?period={period}").json()
    rows = {r["customer"]: r for r in preview["customers"]}
    dm = rows["Dunder Mifflin"]
    assert dm["billable_hours"] == 2.5 and dm["devices"] == 2
    assert [l["amount"] for l in dm["lines"]] == [500.0, 180.0, 30.0]  # retainer + 1.5h overage at 120 + 2 endpoints at 15
    assert dm["total"] == 710.0 and rows["Globex"]["total"] == 100.0
    assert preview["unassigned_billable_hours"] == 0.75
    assert c.get("/v1/billing/preview?period=2026-13").status_code == 422

    invoice = c.post("/v1/billing/invoices", json={"customer_id": acme["id"], "period": period})
    assert invoice.status_code == 201, invoice.text
    invoice = invoice.json()
    assert invoice["total"] == 710.0 and invoice["verified"] is True and invoice["proof_id"]
    assert c.post("/v1/billing/invoices", json={"customer_id": acme["id"], "period": period}).status_code == 409
    assert c.post("/v1/billing/invoices", json={"customer_id": acme["id"], "period": "2999-01"}).status_code == 422
    csv = c.get(f"/v1/billing/invoices/{invoice['id']}/csv")
    assert csv.status_code == 200 and "Monthly retainer" in csv.text and "710.0" in csv.text

    from app.core.db import SessionLocal
    from app.models.models import Invoice
    with SessionLocal() as db:
        db.get(Invoice, invoice["id"]).total = 1.0
        db.commit()
    assert c.get(f"/v1/billing/invoices/{invoice['id']}").json()["verified"] is False  # tampering is detected

    detail = c.get(f"/v1/customers/{acme['id']}").json()
    assert {d["hostname"] for d in detail["devices"]} == {"dm-ws-01", "dm-ws-02"} and detail["contacts"][0]["name"] == "Michael Scott"
    listing = {r["name"]: r for r in c.get("/v1/customers").json()}
    assert listing["Dunder Mifflin"]["devices"] == 2 and listing["Dunder Mifflin"]["open_tickets"] == 1
    assert c.delete(f"/v1/customers/{acme['id']}").status_code == 409  # invoiced customers are kept
    assert c.delete(f"/v1/customers/{globex['id']}").status_code == 200

    engineer = _login(c, org_id, "engineer-billing@proofos.dev", "engineer")
    assert c.get(f"/v1/billing/preview?period={period}", headers=engineer).status_code == 403
    auditor = _login(c, org_id, "auditor-billing@proofos.dev", "auditor")
    assert c.get("/v1/billing/invoices", headers=auditor).status_code == 200
    assert c.post("/v1/billing/invoices", json={"customer_id": acme["id"], "period": "2026-01"}, headers=auditor).status_code == 403
    foreign = _foreign(c, "Other billing tenant")
    assert c.get(f"/v1/customers/{acme['id']}", headers=foreign).status_code == 404
    assert c.get(f"/v1/billing/invoices/{invoice['id']}", headers=foreign).status_code == 404
    assert c.post("/v1/tickets", json={"org_id": org_id, "title": "Cross tenant", "customer_id": acme["id"]}, headers=foreign).status_code == 403


# ---------------------------------------------------------------- AI ticket assist

def test_ticket_assist_uses_evidence_and_records_proof(auth_client, monkeypatch):
    c, org_id, _ = auth_client
    monkeypatch.setattr("app.services.llm.get_llm_client", lambda: None)
    dev = c.post("/v1/devices", json={"org_id": org_id, "hostname": "assist-host", "os": "Windows 11"}).json()
    c.post(f"/v1/devices/{dev['id']}/heartbeat", headers={"X-Agent-Token": dev["device_secret"]}, json={"cpu": 97, "mem": 20, "disk": 30, "reboot_required": True})
    c.post("/v1/knowledge", json={"org_id": org_id, "title": "Fix Outlook crashing on start", "body": "Run outlook /safe"})
    ticket = c.post("/v1/tickets", json={"org_id": org_id, "title": "Outlook crashing constantly", "device_id": dev["id"], "priority": "high"}).json()
    c.post(f"/v1/tickets/{ticket['id']}/comments", json={"body": "Started after this morning's update"})

    r = c.post(f"/v1/ai/tickets/{ticket['id']}/assist")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["engine"].startswith("rule-based") and data["proof_id"]
    assert "assist-host" in data["summary"] and "this morning's update" in data["summary"]
    steps = " ".join(data["next_steps"])
    assert "CPU" in steps and "pending reboot" in steps and "Fix Outlook crashing on start" in steps
    assert data["related_articles"][0]["title"] == "Fix Outlook crashing on start"
    assert "Outlook crashing constantly" in data["reply"]

    class FakeLLM:
        provider = "test-llm"
        def is_configured(self):
            return True
        def chat(self, messages, model=None, max_tokens=None):
            return 'Sure: {"summary": "S", "next_steps": ["a", "b"], "reply": "R"}'
    monkeypatch.setattr("app.services.llm.get_llm_client", lambda: FakeLLM())
    data = c.post(f"/v1/ai/tickets/{ticket['id']}/assist").json()
    assert data == {**data, "summary": "S", "next_steps": ["a", "b"], "reply": "R", "engine": "test-llm"}

    class ThinkingLLM(FakeLLM):
        def chat(self, messages, model=None, max_tokens=None):  # reasoning first, echoing the schema, answer last
            return 'Output must be {"summary": string, "next_steps": [..], "reply": string}. Thinking... {"note": 1} Final: {"summary": "Real", "next_steps": ["x"], "reply": "Hello"}'
    monkeypatch.setattr("app.services.llm.get_llm_client", lambda: ThinkingLLM())
    data = c.post(f"/v1/ai/tickets/{ticket['id']}/assist").json()
    assert data["summary"] == "Real" and data["reply"] == "Hello" and data["engine"] == "test-llm"

    class RamblingLLM(FakeLLM):
        def chat(self, messages, model=None, max_tokens=None):
            return "I could not decide."
    monkeypatch.setattr("app.services.llm.get_llm_client", lambda: RamblingLLM())
    data = c.post(f"/v1/ai/tickets/{ticket['id']}/assist").json()
    assert data["engine"] == "rule-based assistant (AI reply could not be used)" and "assist-host" in data["summary"]

    foreign = _foreign(c, "Other assist tenant")
    assert c.post(f"/v1/ai/tickets/{ticket['id']}/assist", headers=foreign).status_code == 404
