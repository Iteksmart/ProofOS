from __future__ import annotations

# Must set env BEFORE importing app
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_proofos.db")
os.environ.setdefault("JWT_SECRET", "test-secret-min-32-chars-long")
os.environ.setdefault("PROOF_SIGNING_SEED_HEX", "00" * 32)

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from app.core.db import Base, engine

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    from app.main import app

    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def auth_client(client):
    r = client.post("/v1/auth/bootstrap", json={"name": "Test Org"})
    assert r.status_code == 201, r.text
    data = r.json()
    token = data["access_token"]
    org_id = data["org"]["id"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client, org_id, token


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["db"] == "ok"


def test_login_rate_limiter_ignores_untrusted_forwarded_header():
    from starlette.requests import Request

    from app.core.security import _login_rate_limit_key

    request = Request({
        "type": "http",
        "method": "POST",
        "path": "/v1/auth/login",
        "headers": [(b"x-forwarded-for", b"198.51.100.1")],
        "client": ("203.0.113.10", 1234),
        "server": ("testserver", 80),
        "scheme": "http",
        "query_string": b"",
    })
    assert _login_rate_limit_key(request) == "203.0.113.10"


def test_websocket_events_are_org_scoped():
    from app.main import _events_for_org

    events = [
        {"org_id": 1, "type": "proof"},
        {"org_id": 2, "type": "proof"},
        {"type": "global"},
    ]
    assert _events_for_org(events, 1) == [events[0]]
    assert _events_for_org(events, None) == []


def test_production_settings_reject_unsafe_origins_and_sqlite():
    from app.core.config import Settings

    settings = Settings(
        _env_file=None,
        api_env="production",
        jwt_secret="x" * 40,
        proof_key_seed_hex="00" * 32,
        agent_token="agent-secret",
        database_url="sqlite:///./unsafe.db",
        api_cors_origins="*",
    )
    with pytest.raises(ValueError) as error:
        settings.validate_production()
    assert "PostgreSQL" in str(error.value)
    assert "wildcard" in str(error.value)


def test_full_flow(auth_client):
    client, org_id, token = auth_client
    r = client.post("/v1/devices", json={"org_id": org_id, "hostname": "ws-01", "os": "Linux", "ip": "10.0.0.1"})
    assert r.status_code == 201, r.text
    dev_id = r.json()["id"]
    agent_headers = {"X-Agent-Token": r.json()["device_secret"]}

    r = client.get(f"/v1/devices?org_id={org_id}")
    assert r.status_code == 200
    assert len(r.json()) == 1

    r = client.post(f"/v1/devices/{dev_id}/heartbeat", json={"cpu": 10.0, "disk": 20.0, "mem": 30.0, "status": "online"}, headers=agent_headers)
    assert r.status_code == 200

    r = client.post("/v1/tickets", json={"org_id": org_id, "title": "printer down", "body": "offline", "priority": "high"})
    assert r.status_code == 201, r.text
    tid = r.json()["id"]

    r = client.patch(f"/v1/tickets/{tid}", json={"status": "in_progress"})
    assert r.status_code == 200, r.text
    r = client.post(f"/v1/tickets/{tid}/close")
    assert r.status_code == 200

    r = client.patch(f"/v1/tickets/{tid}", json={"status": "in_progress"})
    assert r.status_code == 400, r.text

    r = client.post("/v1/scripts", json={"org_id": org_id, "name": "disk-check", "body": "echo hi", "version": "1.0.0"})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]

    r = client.post(f"/v1/scripts/{sid}/runs?device_id={dev_id}")
    assert r.status_code == 201, r.text
    run_id = r.json()["id"]

    r = client.get(f"/v1/scripts/runs/pending?device_id={dev_id}", headers=agent_headers)
    assert r.status_code == 200
    assert len(r.json()) == 1

    r = client.post(f"/v1/scripts/runs/{run_id}/complete", json={"output": "hi", "exit_code": 0}, headers=agent_headers)
    assert r.status_code == 200

    # Regression: GET /v1/scripts/runs must not be shadowed by GET /{script_id}
    r = client.get(f"/v1/scripts/runs?org_id={org_id}")
    assert r.status_code == 200, r.text
    assert any(x["id"] == run_id for x in r.json())

    r = client.post("/v1/automations", json={"org_id": org_id, "name": "notify-new", "trigger": "ticket.opened", "action": "notify"})
    assert r.status_code == 201, r.text

    r = client.post("/v1/monitor", json={"org_id": org_id, "device_id": dev_id, "kind": "ping", "status": "ok", "latency_ms": 5.0})
    assert r.status_code == 201, r.text

    r = client.get("/v1/proof")
    assert r.status_code == 200
    proofs = r.json()
    assert len(proofs) >= 1

    rid = proofs[0]["id"]
    r = client.get(f"/v1/proof/verify/{rid}")
    assert r.status_code == 200
    v = r.json()
    assert v["verified"] is True, v
    assert v["checks"]["signature_valid"] is True

    r = client.get("/v1/proof/chain")
    assert r.status_code == 200
    assert r.json()["chain_ok"] is True

    r = client.post("/v1/ai/ask", json={"org_id": org_id, "query": "offline devices"})
    assert r.status_code == 200
    assert r.json()["engine"] == "heuristic"  # default AI_PROVIDER
    r = client.post("/v1/ai/summarise", json={"org_id": org_id, "scope": "open"})
    assert r.status_code == 200
    assert r.json()["engine"] == "heuristic"

    import app.main as main_mod

    anon = TestClient(main_mod.app)
    r = anon.get(f"/v1/devices?org_id={org_id}")
    assert r.status_code == 401, r.text


def _fake_client(configured: bool, chat_result):
    class FakeClient:
        model = "auto"
        provider = "openrouter"

        def is_configured(self):
            return configured

        def chat(self, messages, model=None):
            if isinstance(chat_result, Exception):
                raise chat_result
            return chat_result

    return FakeClient()


def test_ai_llm_success(auth_client, monkeypatch):
    client, org_id, _ = auth_client
    from app.services import ai as ai_mod

    monkeypatch.setattr(ai_mod, "get_llm_client", lambda: _fake_client(True, "LLM answer"))
    r = client.post("/v1/ai/ask", json={"org_id": org_id, "query": "offline devices"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["engine"] == "openrouter"
    assert body["answer"] == "LLM answer"


def test_ai_llm_fallback(auth_client, monkeypatch):
    client, org_id, _ = auth_client
    from app.services import ai as ai_mod

    monkeypatch.setattr(ai_mod, "get_llm_client", lambda: _fake_client(True, RuntimeError("no gateway")))
    r = client.post("/v1/ai/ask", json={"org_id": org_id, "query": "offline devices"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["engine"] == "heuristic"
    assert "fallback_reason" in body


def test_auth_guard(client):
    r = client.get("/v1/devices?org_id=1")
    assert r.status_code == 401, r.text


def test_production_config_fails_closed():
    from app.core.config import Settings

    bad = Settings(_env_file=None, jwt_secret="change-me", proof_key_seed_hex="", agent_token="", api_env="production")
    with pytest.raises(ValueError):
        bad.validate_production()

    good = Settings(
        _env_file=None,
        jwt_secret="s" * 40,
        proof_key_seed_hex="ab" * 32,
        agent_token="a" * 48,
        api_env="production",
        database_url=f"postgresql+psycopg://user:{'a' * 64}@localhost/proofos",
        api_cors_origins="https://proofos.example.com",
        web_url="https://proofos.example.com",
    )
    good.validate_production()  # must not raise


def test_production_rejects_plain_http_browser_origins():
    from app.core.config import Settings

    settings = Settings(
        _env_file=None,
        jwt_secret="s" * 40,
        proof_key_seed_hex="ab" * 32,
        agent_token="a" * 48,
        api_env="production",
        database_url=f"postgresql+psycopg://user:{'a' * 64}@localhost/proofos",
        api_cors_origins="http://proofos.example.com",
        web_url="https://proofos.example.com",
    )
    with pytest.raises(ValueError, match="HTTPS origin"):
        settings.validate_production()


def test_bootstrap_blocked_in_prod(client, monkeypatch):
    from types import SimpleNamespace

    import app.api.auth as auth_mod

    monkeypatch.setattr(auth_mod, "settings", SimpleNamespace(is_prod=True, allow_bootstrap=False))
    r = client.post("/v1/auth/bootstrap", json={"name": "Blocked"})
    assert r.status_code == 403, r.text


def test_create_org_and_user_require_auth(client):
    r = client.post("/v1/auth/orgs", json={"name": "Anon Org"})
    assert r.status_code == 401, r.text
    r = client.post("/v1/auth/users", json={"org_id": 1, "email": "a@b.com", "password": "password123", "role": "engineer"})
    assert r.status_code == 401, r.text


def test_create_user_admin_only(auth_client):
    client, org_id, _ = auth_client
    r = client.post("/v1/auth/users", json={"org_id": org_id, "email": "eng@proofos.dev", "password": "password123", "role": "engineer"})
    assert r.status_code == 201, r.text
    r = client.post("/v1/auth/login", json={"email": "eng@proofos.dev", "password": "password123"})
    eng_token = r.json()["access_token"]

    r = client.post(
        "/v1/auth/users",
        json={"org_id": org_id, "email": "x@proofos.dev", "password": "password123", "role": "engineer"},
        headers={"Authorization": f"Bearer {eng_token}"},
    )
    assert r.status_code == 403, r.text


def test_admin_cannot_list_users_from_another_org(auth_client):
    client, org_id, _ = auth_client
    assert client.get(f"/v1/auth/users?org_id={org_id + 1}").status_code == 403


def test_agent_token_required(client, monkeypatch):
    from types import SimpleNamespace

    import app.core.security as sec

    monkeypatch.setattr(sec, "settings", SimpleNamespace(agent_token="secret"))
    r = client.post("/v1/devices/1/heartbeat", json={"status": "online"})
    assert r.status_code == 401, r.text
    r = client.post("/v1/devices/1/heartbeat", json={"status": "online"}, headers={"X-Agent-Token": "secret"})
    assert r.status_code == 404, r.text  # auth passed; device 1 missing


def test_proof_org_scoped(auth_client):
    client, org_id, _ = auth_client
    r = client.post("/v1/auth/bootstrap", json={"name": "Org B"})
    assert r.status_code == 201, r.text
    b = r.json()
    org_b = b["org"]["id"]
    token_b = b["access_token"]
    assert org_b != org_id

    r = client.post("/v1/proof/emit", json={"what": "secret.b", "payload": {"x": 1}}, headers={"Authorization": f"Bearer {token_b}"})
    assert r.status_code == 201, r.text
    rid_b = r.json()["id"]

    r = client.get("/v1/proof")  # org A token (client default)
    assert r.status_code == 200
    assert rid_b not in [p["id"] for p in r.json()]

    r = client.get(f"/v1/proof/verify/{rid_b}")
    assert r.status_code == 403, r.text
    r = client.get("/v1/proof/chain")
    assert r.status_code == 200, r.text
    assert r.json()["chain_ok"] is True


def test_security_headers(client):
    r = client.get("/health")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert r.headers.get("Referrer-Policy") == "no-referrer"


def test_ticket_sla_due(auth_client):
    client, org_id, _ = auth_client
    r = client.post("/v1/tickets", json={"org_id": org_id, "title": "sla test", "priority": "urgent"})
    assert r.status_code == 201, r.text
    assert r.json()["due_at"] is not None


def test_device_metrics_history(auth_client):
    client, org_id, _ = auth_client
    r = client.post("/v1/devices", json={"org_id": org_id, "hostname": "ws-m", "os": "Linux", "ip": "10.0.0.9"})
    dev_id = r.json()["id"]
    r = client.post(f"/v1/devices/{dev_id}/heartbeat", json={"cpu": 11.0, "disk": 22.0, "mem": 33.0, "status": "online"}, headers={"X-Agent-Token": r.json()["device_secret"]})
    assert r.status_code == 200
    r = client.get(f"/v1/devices/{dev_id}/metrics")
    assert r.status_code == 200, r.text
    m = r.json()
    assert len(m) == 1
    assert m[0]["cpu"] == 11.0


def test_script_run_get(auth_client):
    client, org_id, _ = auth_client
    r = client.post("/v1/devices", json={"org_id": org_id, "hostname": "ws-r", "os": "Linux", "ip": "10.0.0.9"})
    dev_id = r.json()["id"]
    agent_headers = {"X-Agent-Token": r.json()["device_secret"]}
    r = client.post("/v1/scripts", json={"org_id": org_id, "name": "s-run", "body": "echo hi", "version": "1.0.0"})
    sid = r.json()["id"]
    r = client.post(f"/v1/scripts/{sid}/runs?device_id={dev_id}")
    run_id = r.json()["id"]
    r = client.post(f"/v1/scripts/runs/{run_id}/complete", json={"output": "hi", "exit_code": 0}, headers=agent_headers)
    r = client.get(f"/v1/scripts/runs/{run_id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["output"] == "hi"
    assert body["script_name"] == "s-run"


def test_script_run_requires_admin_or_manager(auth_client):
    client, org_id, _ = auth_client
    device = client.post("/v1/devices", json={"org_id": org_id, "hostname": "ws-role", "os": "Linux", "ip": "10.0.0.9"}).json()
    script = client.post("/v1/scripts", json={"org_id": org_id, "name": "role-check", "body": "echo hi"}).json()
    created = client.post(
        "/v1/auth/users",
        json={"org_id": org_id, "email": "engineer@example.com", "password": "password123", "role": "engineer"},
    )
    assert created.status_code == 201, created.text
    login = client.post("/v1/auth/login", json={"email": "engineer@example.com", "password": "password123"}).json()
    r = client.post(
        f"/v1/scripts/{script['id']}/runs",
        params={"device_id": device["id"]},
        headers={"Authorization": f"Bearer {login['access_token']}"},
    )
    assert r.status_code == 403


def test_automation_condition(auth_client):
    client, org_id, _ = auth_client
    r = client.post(
        "/v1/automations",
        json={"org_id": org_id, "name": "urgent-notify", "trigger": "ticket.opened", "action": "notify",
              "condition": '{"field":"priority","op":"eq","value":"urgent"}'},
    )
    assert r.status_code == 201, r.text
    # matching ticket → fires alert
    r = client.post("/v1/tickets", json={"org_id": org_id, "title": "urgent issue", "priority": "urgent"})
    assert r.status_code == 201, r.text
    # non-matching ticket → no alert
    r = client.post("/v1/tickets", json={"org_id": org_id, "title": "normal issue", "priority": "normal"})
    assert r.status_code == 201, r.text
    r = client.get(f"/v1/monitor/alerts?org_id={org_id}")
    alerts = r.json()
    assert len(alerts) == 1
    assert alerts[0]["kind"] == "ticket.opened"


def test_automation_update(auth_client):
    client, org_id, _ = auth_client
    r = client.post("/v1/automations", json={"org_id": org_id, "name": "aa", "trigger": "ticket.opened", "action": "notify"})
    aid = r.json()["id"]
    r = client.patch(f"/v1/automations/{aid}", json={"name": "renamed", "condition": '{"field":"priority","op":"eq","value":"high"}'})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "renamed"
    assert r.json()["condition"] == '{"field":"priority","op":"eq","value":"high"}'


def test_monitor_run(auth_client):
    client, org_id, _ = auth_client
    r = client.post("/v1/monitor/run", params={"org_id": org_id})
    assert r.status_code == 200, r.text
    assert "checked" in r.json()


def test_mcp_tools(auth_client):
    client, org_id, _ = auth_client
    r = client.get("/v1/mcp/tools")
    assert r.status_code == 200, r.text
    names = [t["name"] for t in r.json()["tools"]]
    for expected in ("device.metrics", "monitor.run", "ticket.create", "ticket.comment", "proof.verify"):
        assert expected in names


def test_device_token_auth(auth_client, monkeypatch):
    import app.core.security as sec

    client, org_id, _ = auth_client
    # A device-scoped credential works; the global token cannot impersonate it.
    monkeypatch.setattr(sec.settings, "agent_token", "global")
    r = client.post("/v1/devices", json={"org_id": org_id, "hostname": "ws-tok", "os": "Linux", "ip": "10.0.0.9"})
    dev = r.json()
    secret = dev["device_secret"]
    dev_id = dev["id"]
    assert secret

    r = client.post(f"/v1/devices/{dev_id}/heartbeat", json={"status": "online"}, headers={"X-Agent-Token": "wrong"})
    assert r.status_code == 401, r.text

    r = client.post(f"/v1/devices/{dev_id}/heartbeat", json={"status": "online"}, headers={"X-Agent-Token": secret})
    assert r.status_code == 200, r.text
    r = client.post(f"/v1/devices/{dev_id}/heartbeat", json={"status": "online"}, headers={"X-Agent-Token": "global"})
    assert r.status_code == 401, r.text


def test_agent_auth_fails_closed_without_token(auth_client):
    client, org_id, _ = auth_client
    r = client.post("/v1/devices", json={"org_id": org_id, "hostname": "ws-auth", "os": "Linux", "ip": "10.0.0.9"})
    dev_id = r.json()["id"]
    denied = client.get(f"/v1/scripts/runs/pending?device_id={dev_id}")
    assert denied.status_code == 401
    accepted = client.get(
        f"/v1/scripts/runs/pending?device_id={dev_id}",
        headers={"X-Agent-Token": r.json()["device_secret"]},
    )
    assert accepted.status_code == 200


def test_tenant_admin_cannot_access_other_org(auth_client):
    client, org_id, _ = auth_client
    other = client.post("/v1/auth/bootstrap", json={"name": "Other Org"}).json()
    other_org = other["org"]["id"]
    other_token = other["access_token"]
    created = client.post(
        "/v1/devices",
        json={"org_id": other_org, "hostname": "other-host", "os": "Linux", "ip": "10.0.0.2"},
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert created.status_code == 201
    assert client.get(f"/v1/auth/orgs/{other_org}").status_code == 403
    assert client.get(f"/v1/devices?org_id={other_org}").status_code == 403
    assert client.get(f"/v1/devices/{created.json()['id']}").status_code == 403

def test_compliance_export(auth_client):
    client, org_id, _ = auth_client
    r = client.post("/v1/tickets", json={"org_id": org_id, "title": "export test", "priority": "normal"})
    assert r.status_code == 201, r.text

    r = client.get("/v1/proof/export")
    assert r.status_code == 200, r.text
    assert "text/csv" in r.headers["content-type"]
    assert "payload_digest" in r.text  # header row present

    r = client.get("/v1/proof/export?fmt=json")
    assert r.status_code == 200, r.text
    assert r.json()["count"] >= 1

    r = client.get("/v1/proof/report")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_records"] >= 1
    assert body["chain_ok"] is True


def test_notifier_noop():
    from app.services.notifier import send_alert

    # Nothing configured in test env → no channels used, no exception.
    assert send_alert({"message": "x"}) == []


def test_device_type(auth_client):
    client, org_id, _ = auth_client
    r = client.post("/v1/devices", json={"org_id": org_id, "hostname": "sw-1", "os": "Cisco IOS", "ip": "10.0.0.2", "device_type": "switch"})
    assert r.status_code == 201, r.text
    assert r.json()["device_type"] == "switch"


def test_device_command(auth_client):
    client, org_id, _ = auth_client
    r = client.post("/v1/devices", json={"org_id": org_id, "hostname": "ws-cmd", "os": "Linux", "ip": "10.0.0.9", "device_type": "workstation"})
    dev_id = r.json()["id"]
    agent_headers = {"X-Agent-Token": r.json()["device_secret"]}
    r = client.post(f"/v1/devices/{dev_id}/command", json={"body": "echo hello", "description": "test"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "queued"
    run_id = r.json()["run_id"]

    r = client.get(f"/v1/scripts/runs/pending?device_id={dev_id}", headers=agent_headers)
    assert r.status_code == 200
    assert any(j["id"] == run_id for j in r.json())


def test_ai_propose_and_approve(auth_client):
    client, org_id, _ = auth_client
    r = client.post("/v1/devices", json={"org_id": org_id, "hostname": "ws-p", "os": "Linux", "ip": "10.0.0.9", "device_type": "server"})
    dev_id = r.json()["id"]

    r = client.post("/v1/ai/propose", json={"org_id": org_id, "query": "disk cleanup"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["requires_approval"] is True
    aid = body["approval_id"]

    r = client.get(f"/v1/approvals?org_id={org_id}")
    assert any(a["id"] == aid and a["status"] == "pending" for a in r.json())

    r = client.post(f"/v1/approvals/{aid}/approve")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"

    r = client.get(f"/v1/scripts/runs?org_id={org_id}")
    assert any(x["device_id"] == dev_id for x in r.json())


def test_approval_deny(auth_client):
    client, org_id, _ = auth_client
    r = client.post("/v1/devices", json={"org_id": org_id, "hostname": "ws-d", "os": "Linux", "ip": "10.0.0.9", "device_type": "workstation"})
    r = client.post("/v1/ai/propose", json={"org_id": org_id, "query": "performance check"})
    aid = r.json()["approval_id"]
    r = client.post(f"/v1/approvals/{aid}/deny")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "denied"


def test_audit_run(auth_client):
    client, org_id, _ = auth_client
    r = client.post("/v1/audits/run", params={"org_id": org_id, "kind": "full"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["audit"]["id"]
    assert 0 <= body["score"] <= 100
    assert isinstance(body["findings"], list)


def test_audit_report_pdf(auth_client):
    client, org_id, _ = auth_client
    r = client.post("/v1/audits/run", params={"org_id": org_id, "kind": "security"})
    aid = r.json()["audit"]["id"]
    r = client.get(f"/v1/audits/{aid}/report.pdf")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")


def test_onboarding(auth_client):
    client, org_id, _ = auth_client
    r = client.post("/v1/onboarding/init", params={"org_id": org_id})
    assert r.status_code == 201, r.text
    assert r.json()["steps"] == 8
    r = client.get(f"/v1/onboarding?org_id={org_id}")
    steps = r.json()
    assert len(steps) == 8
    r = client.post(f"/v1/onboarding/{steps[0]['id']}/toggle")
    assert r.status_code == 200, r.text
    assert r.json()["done"] is True


def test_consulting(auth_client):
    client, org_id, _ = auth_client
    r = client.post("/v1/consulting/profile", params={"org_id": org_id}, json={"contact_name": "Jane", "industry": "Healthcare", "status": "active"})
    assert r.status_code == 200, r.text
    assert r.json()["contact_name"] == "Jane"
    r = client.get(f"/v1/consulting/profile?org_id={org_id}")
    assert r.json()["industry"] == "Healthcare"

    r = client.post("/v1/consulting/projects", json={"org_id": org_id, "name": "Network Refresh", "description": "Replace switches", "status": "active"})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    r = client.get(f"/v1/consulting/projects?org_id={org_id}")
    assert any(p["id"] == pid for p in r.json())
    r = client.patch(f"/v1/consulting/projects/{pid}", json={"status": "done"})
    assert r.json()["status"] == "done"


def test_rotate_secret(auth_client):
    client, org_id, _ = auth_client
    r = client.post("/v1/devices", json={"org_id": org_id, "hostname": "ws-rot", "os": "Linux", "ip": "10.0.0.9"})
    dev_id = r.json()["id"]
    old = r.json()["device_secret"]
    r = client.post(f"/v1/devices/{dev_id}/rotate-secret")
    assert r.status_code == 200, r.text
    assert r.json()["device_secret"] != old


def test_refresh_status(auth_client):
    client, org_id, _ = auth_client
    client.post("/v1/devices", json={"org_id": org_id, "hostname": "ws-rs", "os": "Linux", "ip": "10.0.0.9"})
    r = client.post("/v1/devices/refresh-status", params={"org_id": org_id})
    assert r.status_code == 200, r.text
    assert "changed" in r.json()


def test_status_sync_marks_offline(auth_client):
    from datetime import datetime, timedelta, timezone

    from app.core.db import SessionLocal
    from app.models.models import Device
    from app.services.status_sync import sync_device_statuses

    client, org_id, _ = auth_client
    r = client.post("/v1/devices", json={"org_id": org_id, "hostname": "ws-sync", "os": "Linux", "ip": "10.0.0.9"})
    dev_id = r.json()["id"]
    client.post(f"/v1/devices/{dev_id}/heartbeat", json={"status": "online"}, headers={"X-Agent-Token": r.json()["device_secret"]})

    db = SessionLocal()
    try:
        dev = db.query(Device).filter(Device.id == dev_id).first()
        dev.last_seen = datetime.now(timezone.utc) - timedelta(minutes=20)
        db.commit()
        result = sync_device_statuses(db, org_id)
        assert result["changed"] >= 1
        db.refresh(dev)
        assert dev.status == "offline"
    finally:
        db.close()


def test_secret_vault(auth_client):
    client, org_id, _ = auth_client
    r = client.post("/v1/secrets", json={"org_id": org_id, "name": "prod-db-pw", "value": "hunter2", "category": "database"})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert "value" not in r.json()  # never returned in list/get payloads
    r = client.get(f"/v1/secrets?org_id={org_id}")
    assert all("value" not in s for s in r.json())
    r = client.post(f"/v1/secrets/{sid}/reveal")
    assert r.status_code == 200, r.text
    assert r.json()["value"] == "hunter2"


def test_cmdb(auth_client):
    client, org_id, _ = auth_client
    r = client.post("/v1/cmdb", json={"org_id": org_id, "name": "core-switch-01", "ci_type": "switch", "attributes": '{"location":"DC1"}'})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    r = client.get(f"/v1/cmdb?org_id={org_id}&ci_type=switch")
    assert any(c["id"] == cid for c in r.json())


def test_knowledge(auth_client):
    client, org_id, _ = auth_client
    r = client.post("/v1/knowledge", json={"org_id": org_id, "title": "How to reset a switch", "body": "Console in and reload", "category": "network", "tags": "switch,reset"})
    assert r.status_code == 201, r.text
    r = client.get(f"/v1/knowledge?org_id={org_id}&q=switch")
    assert any("reset" in a["title"] for a in r.json())


def test_time_tracking(auth_client):
    client, org_id, _ = auth_client
    r = client.post("/v1/time", json={"org_id": org_id, "minutes": 90, "notes": "onboarding", "billable": True})
    assert r.status_code == 201, r.text
    r = client.get(f"/v1/time/summary?org_id={org_id}")
    assert r.json()["total_minutes"] == 90
    assert r.json()["total_hours"] == 1.5


def test_change_management(auth_client):
    client, org_id, _ = auth_client
    r = client.post("/v1/changes", json={"org_id": org_id, "title": "Upgrade core switch firmware", "risk": "high", "impact": "medium", "plan": "Friday window"})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    r = client.patch(f"/v1/changes/{cid}", json={"status": "approved"})
    assert r.json()["status"] == "approved"


def test_anomalies(auth_client):
    client, org_id, _ = auth_client
    r = client.get(f"/v1/analytics/anomalies?org_id={org_id}")
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


def test_automation_simulate(auth_client):
    client, org_id, _ = auth_client
    client.post("/v1/automations", json={"org_id": org_id, "name": "notify-new", "trigger": "ticket.opened", "action": "notify"})
    r = client.post("/v1/automations/simulate", json={"org_id": org_id, "trigger": "ticket.opened", "context": {"priority": "urgent"}})
    assert r.status_code == 200, r.text
    plan = r.json()
    assert any(p["name"] == "notify-new" and p["would_fire"] is True for p in plan)
    # dry-run must have no side effects
    r = client.get(f"/v1/monitor/alerts?org_id={org_id}")
    assert len(r.json()) == 0


def test_automation_remediate_creates_approval(auth_client):
    from app.core.db import SessionLocal
    from app.models.models import Approval
    from app.services.automation_engine import evaluate

    client, org_id, _ = auth_client
    r = client.post("/v1/scripts", json={"org_id": org_id, "name": "fix-disk", "body": "df -h", "version": "1.0.0"})
    sid = r.json()["id"]
    r = client.post("/v1/devices", json={"org_id": org_id, "hostname": "ws-re", "os": "Linux", "ip": "10.0.0.9"})
    dev_id = r.json()["id"]
    client.post("/v1/automations", json={"org_id": org_id, "name": "auto-fix", "trigger": "device.offline", "action": "remediate", "remediation_script_id": sid})

    db = SessionLocal()
    try:
        evaluate(db, org_id, "device.offline", {"device_id": dev_id})
        a = db.query(Approval).filter(Approval.requester_kind == "automation").first()
        assert a is not None
        assert a.kind == "script"
    finally:
        db.close()


def test_integration_metrics(auth_client):
    client, org_id, _ = auth_client
    r = client.post("/v1/integrations/metrics", json={"org_id": org_id, "source": "prometheus", "host": "db-1", "metrics": [{"name": "cpu_usage", "value": 42.5}, {"name": "mem_usage", "value": 60}]})
    assert r.status_code == 201, r.text
    assert r.json()["ingested"] == 2
    r = client.get(f"/v1/integrations/metrics?org_id={org_id}")
    assert len(r.json()) == 2


def test_ticket_severity(auth_client):
    client, org_id, _ = auth_client
    r = client.post("/v1/tickets", json={"org_id": org_id, "title": "critical outage down", "priority": "normal"})
    assert r.status_code == 201, r.text
    assert r.json()["severity"] == "P1"
    r = client.post("/v1/tickets", json={"org_id": org_id, "title": "minor thing", "priority": "low"})
    assert r.json()["severity"] == "P4"


def test_automation_autonomy_auto(auth_client):
    from app.core.db import SessionLocal
    from app.models.models import ScriptRun
    from app.services.automation_engine import evaluate

    client, org_id, _ = auth_client
    r = client.post("/v1/scripts", json={"org_id": org_id, "name": "auto-fix", "body": "echo hi", "version": "1.0.0"})
    sid = r.json()["id"]
    r = client.post("/v1/devices", json={"org_id": org_id, "hostname": "ws-auto", "os": "Linux", "ip": "10.0.0.9"})
    dev_id = r.json()["id"]
    client.post("/v1/automations", json={"org_id": org_id, "name": "auto", "trigger": "device.offline", "action": "remediate", "autonomy": "auto", "remediation_script_id": sid})

    db = SessionLocal()
    try:
        evaluate(db, org_id, "device.offline", {"device_id": dev_id})
        run = db.query(ScriptRun).filter(ScriptRun.device_id == dev_id).first()
        assert run is not None
    finally:
        db.close()


def test_proof_anchor(auth_client):
    client, org_id, _ = auth_client
    client.post("/v1/tickets", json={"org_id": org_id, "title": "anchor test"})
    r = client.get("/v1/proof")
    rid = r.json()[0]["id"]
    r = client.post(f"/v1/proof/anchor/{rid}")
    assert r.status_code == 200, r.text
    assert r.json()["anchored"] is True
    assert r.json()["commitment"]


def test_agent_card(client):
    r = client.get("/.well-known/agent.json")
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "ProofOS"


def test_remediation_stats(auth_client):
    client, org_id, _ = auth_client
    r = client.get(f"/v1/analytics/remediation-stats?org_id={org_id}")
    assert r.status_code == 200, r.text
    assert "total" in r.json()


def test_itechsmart_integration(auth_client):
    import pytest as _pytest

    from app.services import itechsmart

    probe = itechsmart.probe()
    if not any(v.get("ok") for v in probe.values()):
        _pytest.skip("iTechSmart services not running locally")

    client, org_id, _ = auth_client
    r = client.get("/v1/itechsmart/status")
    assert r.status_code == 200, r.text
    assert "mcp" in r.json() and "prooflink_plus" in r.json()

    r = client.get("/v1/itechsmart/tools")
    if probe.get("mcp", {}).get("ok"):
        assert r.status_code == 200, r.text
        assert isinstance(r.json().get("tools"), list)
    else:
        assert r.status_code == 502, r.text

    r = client.get("/v1/itechsmart/chain")
    if probe.get("prooflink_plus", {}).get("ok"):
        assert r.status_code == 200, r.text
        assert "receipts" in r.json()
    else:
        assert r.status_code == 502, r.text


def test_itechsmart_mcp_call_requires_key(auth_client, monkeypatch):
    from app.services import itechsmart

    monkeypatch.setattr(itechsmart.settings, "itechsmart_api_key", "")
    result = itechsmart.mcp_call("query_uaio_status", {})
    assert result.get("ok") is False
    assert "ITECHSMART_API_KEY" in result.get("error", "")


def test_itechsmart_endpoints_require_privileged_role(auth_client):
    client, org_id, _ = auth_client
    created = client.post("/v1/auth/users", json={
        "org_id": org_id,
        "email": "viewer@proofos.dev",
        "password": "test-password-123",
        "role": "viewer",
    })
    assert created.status_code == 201, created.text
    login = client.post("/v1/auth/login", json={
        "email": "viewer@proofos.dev",
        "password": "test-password-123",
    })
    assert login.status_code == 200, login.text
    client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
    assert client.get("/v1/itechsmart/status").status_code == 403
    assert client.post("/v1/itechsmart/mcp/call", json={"tool": "anything"}).status_code == 403


def test_vm_register_and_control(auth_client):
    client, org_id, _ = auth_client
    r = client.post("/v1/devices", json={"org_id": org_id, "hostname": "hv-host-01", "os": "Windows Server", "ip": "10.0.0.10", "device_type": "server"})
    host_id = r.json()["id"]
    r = client.post("/v1/vms", json={"org_id": org_id, "host_id": host_id, "name": "dc-01", "hypervisor": "hyper-v", "vcpu": 4, "memory_mb": 8192})
    assert r.status_code == 201, r.text
    vm_id = r.json()["id"]
    r = client.get(f"/v1/vms?org_id={org_id}")
    assert any(v["id"] == vm_id for v in r.json())
    for action in ("start", "stop", "restart"):
        r = client.post(f"/v1/vms/{vm_id}/{action}")
        assert r.status_code == 200, r.text
        assert r.json()["run_id"]


def test_remote_session(auth_client):
    client, org_id, _ = auth_client
    r = client.post("/v1/devices", json={"org_id": org_id, "hostname": "ws-remote", "os": "Linux", "ip": "10.0.0.9"})
    dev_id = r.json()["id"]
    r = client.post(f"/v1/remote/devices/{dev_id}/remote-session", json={"kind": "console"})
    assert r.status_code == 201, r.text
    sid = r.json()["session_id"]
    assert r.json()["ws_url"]
    r = client.get(f"/v1/remote?org_id={org_id}")
    assert any(s["id"] == sid and s["status"] == "active" for s in r.json())
    r = client.post(f"/v1/remote/{sid}/end")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ended"


def test_remote_kvm_session(auth_client):
    client, org_id, _ = auth_client
    r = client.post("/v1/devices", json={"org_id": org_id, "hostname": "ws-kvm", "os": "Linux", "ip": "10.0.0.9"})
    dev_id = r.json()["id"]
    r = client.post(f"/v1/remote/devices/{dev_id}/remote-session", json={"kind": "kvm", "provider": "vnc"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["kind"] == "kvm"
    assert body["connect_url"].startswith("vnc://10.0.0.9:")


def test_remote_meshcentral_session(auth_client):
    client, org_id, _ = auth_client
    r = client.post("/v1/devices", json={"org_id": org_id, "hostname": "ws-mc", "os": "Linux", "ip": "10.0.0.9"})
    dev_id = r.json()["id"]
    r = client.post(f"/v1/remote/devices/{dev_id}/remote-session", json={"kind": "kvm", "provider": "meshcentral"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["connect_url"].startswith("https://localhost:8096/?viewmode=10&gotonode=")


def test_patch_register_and_deploy(auth_client):
    client, org_id, _ = auth_client
    r = client.post("/v1/devices", json={"org_id": org_id, "hostname": "ws-patch", "os": "Linux", "ip": "10.0.0.9"})
    dev_id = r.json()["id"]
    r = client.post("/v1/patches", json={"org_id": org_id, "device_id": dev_id, "name": "openssl", "category": "security", "severity": "critical", "available_version": "3.0.9"})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    r = client.get(f"/v1/patches?org_id={org_id}&category=security")
    assert any(p["id"] == pid for p in r.json())
    r = client.post(f"/v1/patches/{pid}/deploy")
    assert r.status_code == 200, r.text
    assert r.json()["run_id"]
    r = client.post("/v1/patches/scan", params={"org_id": org_id, "device_id": dev_id})
    assert r.status_code == 200
    assert r.json()["run_id"]


def test_sso_config_and_metadata(auth_client):
    client, org_id, _ = auth_client
    r = client.post("/v1/sso/config", params={"org_id": org_id}, json={"provider": "saml", "entity_id": "https://idp.example.com", "metadata_url": "https://idp.example.com/metadata", "enabled": True})
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is True
    r = client.get(f"/v1/sso/config?org_id={org_id}")
    assert r.json()["entity_id"] == "https://idp.example.com"
    r = client.get("/v1/sso/sp-metadata")
    assert r.status_code == 200, r.text
    assert "EntityDescriptor" in r.text


def test_root_cause_and_apm(auth_client):
    client, org_id, _ = auth_client
    r = client.post("/v1/devices", json={"org_id": org_id, "hostname": "ws-rc", "os": "Linux", "ip": "10.0.0.9"})
    dev_id = r.json()["id"]
    r = client.get(f"/v1/analytics/root-cause?org_id={org_id}&device_id={dev_id}")
    assert r.status_code == 200, r.text
    assert "events" in r.json() and "suggestion" in r.json()
    r = client.get(f"/v1/analytics/apm?org_id={org_id}")
    assert r.status_code == 200, r.text
    assert "spans" in r.json()


def test_google_sso_framework(auth_client, monkeypatch):
    # Keep this test independent of the developer's repository-level .env file.
    from app.services import google_sso

    monkeypatch.setattr(google_sso.settings, "google_client_id", "")
    monkeypatch.setattr(google_sso.settings, "google_client_secret", "")
    client, org_id, _ = auth_client
    r = client.get("/v1/sso/google")
    assert r.status_code == 200, r.text
    assert r.json()["configured"] is False  # no credentials in test env
    r = client.get("/v1/sso/google/login")
    assert r.status_code == 400, r.text  # not configured
    r = client.get("/v1/sso/google/callback")
    assert r.status_code == 400, r.text  # missing code


def test_google_sso_build_url(monkeypatch):
    from app.services import google_sso

    monkeypatch.setattr(google_sso.settings, "google_client_id", "abc123")
    monkeypatch.setattr(google_sso.settings, "google_redirect_uri", "http://localhost:8000/cb")
    url = google_sso.build_auth_url("mystate")
    assert "accounts.google.com" in url
    assert "client_id=abc123" in url
    assert "state=mystate" in url
    assert "redirect_uri=http" in url


def test_saml_acs_not_configured(auth_client):
    client, org_id, _ = auth_client
    r = client.post("/v1/sso/acs")
    assert r.status_code == 400, r.text  # SAML_IDP_METADATA_URL unset in test env
    assert "SAML_IDP_METADATA_URL" in r.json()["detail"]


def test_push_register_and_status(auth_client):
    client, org_id, _ = auth_client
    users = client.get(f"/v1/auth/users?org_id={org_id}").json()
    user_id = users[0]["id"]
    r = client.post("/v1/push/register", json={"org_id": org_id, "user_id": user_id, "fcm_token": "e2e-fcm-token-123456789", "platform": "web"})
    assert r.status_code == 201, r.text
    r = client.get(f"/v1/push?org_id={org_id}")
    assert any(p["fcm_token"] == "e2e-fcm-token-123456789" for p in r.json())
    r = client.post(f"/v1/push/test?org_id={org_id}")
    assert r.status_code == 400, r.text  # FCM not configured in test env


def test_bootstrap_random_password(client):
    r = client.post("/v1/auth/bootstrap", json={"name": "Pw Org"})
    assert r.status_code == 201, r.text
    data = r.json()
    assert "initial_password" in data
    assert data["initial_password"] != "admin12345"
    assert len(data["initial_password"]) >= 16


def test_bootstrap_accepts_chosen_admin_credentials(client):
    r = client.post(
        "/v1/auth/bootstrap",
        json={"name": "Chosen Credentials Workspace", "email": "owner@example.com", "password": "chosen-local-password-2026"},
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["org"]["name"] == "Chosen Credentials Workspace"
    assert data["user"]["email"] == "owner@example.com"
    assert "initial_password" not in data
    signed_in = client.post("/v1/auth/login", json={"email": "owner@example.com", "password": "chosen-local-password-2026"})
    assert signed_in.status_code == 200, signed_in.text


def test_admin_can_rename_own_workspace(auth_client):
    client, org_id, _ = auth_client
    r = client.patch(f"/v1/auth/orgs/{org_id}", json={"name": "Renamed Test Workspace"})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Renamed Test Workspace"
    assert client.get(f"/v1/auth/orgs/{org_id}").json()["name"] == "Renamed Test Workspace"


def test_password_reset_link_changes_password_once(client, monkeypatch):
    from app.core.security import create_password_reset_token
    from app.services import password_reset

    created = client.post(
        "/v1/auth/bootstrap",
        json={"name": "Reset Link Workspace", "email": "reset@example.com", "password": "starting-password-2026"},
    )
    assert created.status_code == 201, created.text
    issued = {}
    monkeypatch.setattr(password_reset, "email_delivery_configured", lambda: True)
    monkeypatch.setattr(password_reset, "send_password_reset_email", lambda user: issued.setdefault("token", create_password_reset_token(user)))

    request = client.post("/v1/auth/password/reset-request", json={"email": "reset@example.com"})
    assert request.status_code == 200, request.text
    assert "token" not in request.json()
    changed = client.post(
        "/v1/auth/password/reset",
        json={"token": issued["token"], "new_password": "replacement-password-2026"},
    )
    assert changed.status_code == 200, changed.text
    assert client.post("/v1/auth/login", json={"email": "reset@example.com", "password": "replacement-password-2026"}).status_code == 200
    assert client.post(
        "/v1/auth/password/reset",
        json={"token": issued["token"], "new_password": "replayed-password-2026"},
    ).status_code == 400


def test_bootstrap_cannot_reissue_admin_token_for_existing_org(client):
    first = client.post("/v1/auth/bootstrap", json={"name": "Protected Workspace"})
    assert first.status_code == 201, first.text
    second = client.post("/v1/auth/bootstrap", json={"name": "protected workspace"})
    assert second.status_code == 409, second.text
    assert "access_token" not in second.json()


def test_password_change_requires_current_password_for_password_sessions(client):
    created = client.post("/v1/auth/bootstrap", json={"name": "Password Change Workspace"}).json()
    token = created["access_token"]
    email = created["user"]["email"]
    first_password = created["initial_password"]
    changed = client.post(
        "/v1/auth/password",
        json={"current_password": first_password, "new_password": "strong-new-password-2026"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert changed.status_code == 200, changed.text
    signed_in = client.post("/v1/auth/login", json={"email": email, "password": "strong-new-password-2026"})
    assert signed_in.status_code == 200, signed_in.text
    token2 = signed_in.json()["access_token"]
    denied = client.post(
        "/v1/auth/password",
        json={"new_password": "another-strong-password-2026"},
        headers={"Authorization": f"Bearer {token2}"},
    )
    assert denied.status_code == 400, denied.text
    changed2 = client.post(
        "/v1/auth/password",
        json={"current_password": "strong-new-password-2026", "new_password": "another-strong-password-2026"},
        headers={"Authorization": f"Bearer {token2}"},
    )
    assert changed2.status_code == 200, changed2.text


def test_kill_switch_blocks_execution(auth_client):
    client, org_id, _ = auth_client
    r = client.post("/v1/devices", json={"org_id": org_id, "hostname": "ks-host", "os": "Linux", "ip": "10.0.0.9"})
    dev_id = r.json()["id"]
    r = client.post("/v1/scripts", json={"org_id": org_id, "name": "ks-script", "body": "echo hi"})
    sid = r.json()["id"]
    # engage
    r = client.post("/v1/ops/kill-switch", json={"engaged": True, "reason": "test"})
    assert r.status_code == 200, r.text
    assert r.json()["engaged"] is True
    # blocked
    r = client.post(f"/v1/scripts/{sid}/run", params={"device_id": dev_id})
    assert r.status_code == 409, r.text
    # disengage
    r = client.post("/v1/ops/kill-switch", json={"engaged": False, "reason": "test done"})
    assert r.status_code == 200
    # allowed again
    r = client.post(f"/v1/scripts/{sid}/run", params={"device_id": dev_id})
    assert r.status_code == 201, r.text


def test_dlp_detection():
    from app.services import dlp

    hits = dlp.detect("SSN is 123-45-6789 and card 4111 1111 1111 1111")
    patterns = {h["pattern"] for h in hits}
    assert "ssn" in patterns
    assert "credit_card" in patterns
    assert "123-45-6789" not in str(hits)  # redacted, never stored raw


def test_enclave_lifecycle(auth_client):
    client, org_id, _ = auth_client
    r = client.post("/v1/enclaves/policies", params={"org_id": org_id}, json={"name": "BYOD baseline", "blocked_apps": '["dropbox"]', "network_allowlist": '["acme.com","10.0.0.0/8"]'})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    r = client.post("/v1/devices", json={"org_id": org_id, "hostname": "byod-laptop", "os": "macOS 15", "ip": "10.0.5.10"})
    did = r.json()["id"]
    r = client.post("/v1/enclaves", json={"org_id": org_id, "device_id": did, "name": "Contractor Workspace", "policy_id": pid})
    assert r.status_code == 201, r.text
    enclave_id = r.json()["enclave"]["id"]
    assert r.json()["enclave_key"]
    r = client.get(f"/v1/enclaves?org_id={org_id}")
    assert any(e["id"] == enclave_id for e in r.json())
    # report a DLP event — sensitive data in detail auto-escalates to critical
    r = client.post(f"/v1/enclaves/{enclave_id}/events", json={"kind": "dlp_blocked", "detail": "attempted to copy SSN 111-22-3333 out of enclave", "source": "clipboard"})
    assert r.status_code == 201, r.text
    assert r.json()["severity"] == "critical"
    r = client.get(f"/v1/enclaves/{enclave_id}/events")
    assert len(r.json()) == 1
    r = client.post("/v1/enclaves/scan", json={"text": "api key is AKIAIOSFODNN7EXAMPLE"})
    assert r.json()["blocked"] is True
    r = client.patch(f"/v1/enclaves/{enclave_id}", json={"status": "suspended"})
    assert r.status_code == 200
    assert r.json()["status"] == "suspended"
