"""Dev seed: create a fully-populated demo client via the API. Idempotent-ish.

Run with:  python seed.py
Creates org "Acme Corp" + demo admin `demo@acme.dev / DemoPassword123` and populates
devices, tickets, monitoring, scripts, automations, approvals, CMDB, knowledge,
secrets, changes, time, VMs, patches, onboarding, consulting, and metrics.
Every API call emits a proof record, so the ledger is rich too.
"""
from __future__ import annotations

import os
import sys
import time

import httpx

API = os.getenv("API_URL", "http://localhost:8000")
ORG_NAME = os.getenv("ORG_NAME", "Acme Corp")
DEMO_ADMIN = "demo@acme.dev"
DEMO_PASSWORD = "DemoPassword123"
AGENT_TOKEN = os.getenv("AGENT_TOKEN", "demo-agent-token")


def post(path, h, json=None, params=None):
    try:
        r = httpx.post(f"{API}{path}", headers=h, json=json, params=params, timeout=15)
        return r.status_code, r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    except Exception as e:  # noqa: BLE001
        print(f"  ! {path} -> {e}")
        return None, {}


def get(path, h, params=None):
    try:
        r = httpx.get(f"{API}{path}", headers=h, params=params, timeout=15)
        return r.status_code, r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    except Exception as e:  # noqa: BLE001
        print(f"  ! {path} -> {e}")
        return None, {}


def patch(path, h, json=None):
    try:
        r = httpx.patch(f"{API}{path}", headers=h, json=json, timeout=15)
        return r.status_code, r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    except Exception as e:  # noqa: BLE001
        print(f"  ! {path} -> {e}")
        return None, {}


def main() -> None:
    # Create the demo workspace with a known admin, or sign in if it already exists.
    r = httpx.post(f"{API}/v1/auth/bootstrap", json={"name": ORG_NAME, "email": DEMO_ADMIN, "password": DEMO_PASSWORD}, timeout=15)
    if r.status_code in (200, 201):
        boot = r.json()
        token = boot["access_token"]
        org_id = boot["org"]["id"]
    elif r.status_code == 409:
        lr = httpx.post(f"{API}/v1/auth/login", json={"email": DEMO_ADMIN, "password": DEMO_PASSWORD}, timeout=15)
        lr.raise_for_status()
        token = lr.json()["access_token"]
        me = httpx.get(f"{API}/v1/auth/me", headers={"Authorization": f"Bearer {token}"}, timeout=10).json()
        org_id = me["org_id"]
    else:
        r.raise_for_status()
    h = {"Authorization": f"Bearer {token}"}
    print(f"[OK] org={org_id} ({ORG_NAME})")

    # --- users ---
    for email, role in [
        (DEMO_ADMIN, "admin"),
        ("engineer@acme.dev", "engineer"),
        ("auditor@acme.dev", "auditor"),
        ("viewer@acme.dev", "viewer"),
    ]:
        sc, _ = post("/v1/auth/users", h, {"org_id": org_id, "email": email, "password": "password123", "role": role})
        print(f"  user {email} [{role}] -> {sc}")

    # --- devices (6 types) ---
    devices = [
        ("acme-dc-01", "Windows Server 2022", "10.0.0.10", "server"),
        ("acme-dc-02", "Windows Server 2022", "10.0.0.11", "server"),
        ("acme-app-01", "Ubuntu 24.04", "10.0.1.20", "server"),
        ("acme-db-01", "Ubuntu 22.04", "10.0.1.30", "server"),
        ("acme-ws-jane", "Windows 11", "10.0.2.101", "workstation"),
        ("acme-ws-bob", "macOS 15", "10.0.2.102", "workstation"),
        ("acme-core-sw", "Cisco IOS", "10.0.0.1", "switch"),
        ("acme-ap-lobby", "OpenWrt", "10.0.3.5", "access_point"),
    ]
    dev_ids = []
    dev_secrets = []
    for hostname, os_name, ip, dtype in devices:
        sc, d = post("/v1/devices", h, {"org_id": org_id, "hostname": hostname, "os": os_name, "ip": ip, "device_type": dtype})
        if sc in (200, 201):
            dev_ids.append(d["id"])
            dev_secrets.append(d.get("device_secret", ""))
            print(f"  device {hostname} [{dtype}] id={d['id']}")
    # heartbeat most (online), leave last two offline
    for i, did in enumerate(dev_ids):
        if i >= len(dev_ids) - 2:
            continue
        cpu, disk, mem = [(11 + i * 9) % 90, (30 + i * 7) % 95, (40 + i * 5) % 92]
        ah = {"X-Agent-Token": dev_secrets[i]}
        post(f"/v1/devices/{did}/heartbeat", ah, {"cpu": cpu, "disk": disk, "mem": mem, "status": "online"})
    print("  heartbeats posted")

    # --- tickets ---
    tickets = [
        ("Email server down — no mail flow", "Users report mail is not sending since 8am.", "urgent", "open"),
        ("VPN certificate expiring in 30 days", "Wildcard VPN cert expires 2026-12-05.", "high", "in_progress"),
        ("Printer offline on 2nd floor", "Lobby printer unreachable.", "normal", "open"),
        ("New hire laptop setup", "Provision laptop + accounts for new PM.", "low", "pending"),
        ("Database backups failing nightly", "Postgres pg_dump job exit code 1.", "urgent", "in_progress"),
        ("Switch firmware upgrade", "Schedule core-sw firmware upgrade window.", "normal", "resolved"),
        ("Wi-Fi dead zones reported", "Clients drop in east wing.", "high", "open"),
        ("MFA rollout for finance team", "Enroll 12 finance users in MFA.", "normal", "closed"),
    ]
    ticket_ids = []
    for title, body, pri, status in tickets:
        sc, t = post("/v1/tickets", h, {"org_id": org_id, "title": title, "body": body, "priority": pri})
        if sc in (200, 201):
            ticket_ids.append(t["id"])
            if status != "open":
                post(f"/v1/tickets/{t['id']}", h, {"status": status}) if False else None
    # comments on first ticket
    if ticket_ids:
        post(f"/v1/tickets/{ticket_ids[0]}/comments", h, {"body": "Investigating SMTP relay config.", "author": "engineer@acme.dev"})
    print(f"  tickets: {len(ticket_ids)}")

    # --- monitor checks (a couple failing to raise alerts) ---
    for i, did in enumerate(dev_ids[:6]):
        status = "ok" if i not in (0, 2) else "down"
        post("/v1/monitor", h, {"org_id": org_id, "device_id": did, "kind": "port", "target": f"{devices[i][2]}:443", "status": status, "latency_ms": 12 + i * 5, "threshold_ms": 200})
    print("  monitor checks created (2 failing)")

    # --- scripts + runs ---
    scripts = [
        ("disk-cleanup", "df -h && apt-get autoremove -y", "1.0.0"),
        ("restart-nginx", "systemctl restart nginx", "1.0.0"),
        ("check-uptime", "uptime && who", "1.0.0"),
        ("backup-db", "pg_dump acme | gzip > /backups/acme.sql.gz", "1.1.0"),
    ]
    script_ids = []
    for name, body, ver in scripts:
        sc, s = post("/v1/scripts", h, {"org_id": org_id, "name": name, "body": body, "version": ver})
        if sc in (200, 201):
            script_ids.append(s["id"])
    for i, sid in enumerate(script_ids):
        if dev_ids:
            sc, run = post(f"/v1/scripts/{sid}/runs", h, params={"device_id": dev_ids[i % len(dev_ids)]})
            if sc in (200, 201) and run.get("id"):
                post(f"/v1/scripts/runs/{run['id']}/complete", {"X-Agent-Token": AGENT_TOKEN}, {"output": f"OK (exit 0) — run {i}", "exit_code": 0})
    print(f"  scripts: {len(script_ids)} + runs")

    # --- automations ---
    autos = [
        ("Urgent ticket → notify + approval", "ticket.opened", "notify", '{"field":"priority","op":"eq","value":"urgent"}', "manual"),
        ("Offline device → alert", "device.offline", "alert", "", "semi"),
        ("Failed script → auto-retry", "script.failed", "remediate", "", "auto"),
        ("High CPU → open ticket", "metric.anomaly", "ticket", "", "semi"),
    ]
    for name, trigger, action, cond, autonomy in autos:
        post("/v1/automations", h, {"org_id": org_id, "name": name, "trigger": trigger, "action": action, "condition": cond, "autonomy": autonomy})
    print("  automations: 4")

    # --- pending approval (via AI propose) ---
    sc, ap = post("/v1/ai/propose", h, {"org_id": org_id, "query": "restart the email server to fix mail flow"})
    print(f"  AI proposal -> {sc} (approval pending)")

    # --- CMDB ---
    for name, ctype, attrs in [
        ("acme-core-sw", "switch", '{"location":"DC1","serial":"SW-001"}'),
        ("acme-db-01", "server", '{"location":"DC1","env":"prod"}'),
        ("Acme CRM", "application", '{"owner":"sales","version":"4.2"}'),
        ("pg-primary", "database", '{"engine":"postgres16","replicas":2}'),
        ("corp-wifi", "network", '{"ssid":"acme-corp","vlan":20}'),
    ]:
        post("/v1/cmdb", h, {"org_id": org_id, "name": name, "ci_type": ctype, "status": "operational", "attributes": attrs})
    print("  cmdb: 5")

    # --- knowledge ---
    for title, body, cat, tags in [
        ("Reset VPN credentials", "Steps to reset the corporate VPN password.", "how-to", "vpn,auth"),
        ("Onboarding checklist", "Standard new-hire IT provisioning checklist.", "runbook", "onboarding,hr"),
        ("Troubleshoot Wi-Fi drops", "Common causes and fixes for Wi-Fi disconnects.", "troubleshooting", "wifi,network"),
        ("Change freeze policy", "Quarterly change-freeze windows and exceptions.", "policy", "change,itil"),
    ]:
        post("/v1/knowledge", h, {"org_id": org_id, "title": title, "body": body, "category": cat, "tags": tags})
    print("  knowledge: 4")

    # --- secrets (vault) ---
    for name, value, cat in [
        ("db-primary-pass", "s3cr3t-db-2026!", "database"),
        ("vpn-radius-secret", "radius-shared-key", "network"),
        ("smtp-api-key", "sk_live_9f8e7d6c", "api"),
        ("wifi-wpa2-psk", "corp-wifi-passphrase", "network"),
    ]:
        post("/v1/secrets", h, {"org_id": org_id, "name": name, "value": value, "category": cat})
    print("  secrets: 4")

    # --- changes ---
    for title, risk, impact, plan, status in [
        ("Upgrade core-sw firmware", "medium", "medium", "Upgrade during Sunday maintenance window.", "submitted"),
        ("Migrate CRM to Postgres 16", "high", "high", "Full backup + staged cutover.", "draft"),
        ("Enable MFA org-wide", "low", "medium", "Phased rollout by department.", "approved"),
    ]:
        sc, c = post("/v1/changes", h, {"org_id": org_id, "title": title, "risk": risk, "impact": impact, "plan": plan})
        if sc in (200, 201) and status != "draft":
            patch(f"/v1/changes/{c['id']}", h, {"status": status})
    print("  changes: 3")

    # --- time ---
    for minutes, notes, billable in [
        (90, "Email outage triage", True),
        (45, "Onboarding new hire", True),
        (120, "Switch firmware prep", True),
        (30, "MFA rollout planning", True),
        (60, "Internal meeting", False),
        (75, "Wi-Fi survey", True),
    ]:
        post("/v1/time", h, {"org_id": org_id, "minutes": minutes, "notes": notes, "billable": billable})
    print("  time: 6")

    # --- VMs ---
    host_id = dev_ids[0] if dev_ids else 1
    for name, hyp, state, vcpu, mem in [
        ("dc-vm-01", "hyper-v", "running", 4, 8192),
        ("web-vm-01", "libvirt", "running", 2, 4096),
        ("qa-vm-01", "vmware", "stopped", 2, 4096),
    ]:
        post("/v1/vms", h, {"org_id": org_id, "host_id": host_id, "name": name, "hypervisor": hyp, "state": state, "vcpu": vcpu, "memory_mb": mem})
    print("  vms: 3")

    # --- patches ---
    for did, name, cat, sev, avail in [
        (dev_ids[0], "KB5034123 (Windows update)", "os", "important", "2026-11"),
        (dev_ids[2], "openssl", "security", "critical", "3.0.15"),
        (dev_ids[4], "Chrome", "third_party", "moderate", "131.0"),
        (dev_ids[1], "nginx", "security", "critical", "1.26.2"),
    ]:
        post("/v1/patches", h, {"org_id": org_id, "device_id": did, "name": name, "category": cat, "severity": sev, "available_version": avail})
    print("  patches: 4")

    # --- onboarding ---
    sc, _ = post("/v1/onboarding/init", h, params={"org_id": org_id})
    steps, _ = get("/v1/onboarding", h, params={"org_id": org_id})
    if isinstance(steps, list):
        for i, s in enumerate(steps[:5]):
            post(f"/v1/onboarding/{s['id']}/toggle", h)
    print(f"  onboarding: {len(steps) if isinstance(steps, list) else 0} steps")

    # --- consulting ---
    post("/v1/consulting/profile", h, params={"org_id": org_id}, json={"contact_name": "Acme IT Director", "contact_email": "it@acme.dev", "phone": "555-0100", "industry": "Manufacturing", "status": "active", "notes": "Quarterly business review."})
    for name, desc, status in [
        ("Zero-trust rollout", "Implement zero-trust network segmentation.", "active"),
        ("Cloud migration assessment", "Assess workload migration to AWS.", "planning"),
        ("DR plan refresh", "Update disaster recovery runbook + test.", "done"),
    ]:
        post("/v1/consulting/projects", h, {"org_id": org_id, "name": name, "description": desc, "status": status})
    print("  consulting: profile + 3 projects")

    # --- metrics (for analytics/anomaly) ---
    for host, vals in [("acme-db-01", [{"name": "cpu", "value": 82.0}, {"name": "mem", "value": 71.0}]), ("acme-app-01", [{"name": "cpu", "value": 34.0}])]:
        post("/v1/integrations/metrics", h, {"org_id": org_id, "source": "prometheus", "host": host, "metrics": vals})
    print("  metrics ingested")

    # --- audit (populate score + findings) ---
    sc, audit = post("/v1/audits/run", h, params={"org_id": org_id, "kind": "full"})
    print(f"  audit -> {sc}")

    chain, _ = get("/v1/proof/chain", h)
    if isinstance(chain, dict):
        print(f"  proof chain: {chain.get('count', '?')} records")
    print(f"\nDEMO READY - login as {DEMO_ADMIN} / {DEMO_PASSWORD}")


if __name__ == "__main__":
    main()
