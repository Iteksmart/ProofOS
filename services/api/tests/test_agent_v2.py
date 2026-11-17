"""Agent v2 protocol: signed jobs, push notices, streaming output, cancellation and releases."""
from __future__ import annotations

import base64
import hashlib
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.core.proof import canonical


def _device(c, org_id, name="agent-v2"):
    d = c.post("/v1/devices", json={"org_id": org_id, "hostname": name, "os": "Ubuntu 24.04"}).json()
    return d, {"X-Agent-Token": d["device_secret"]}


def _verify(key_hex, obj, sig):
    Ed25519PublicKey.from_public_bytes(bytes.fromhex(key_hex)).verify(base64.b64decode(sig), canonical(obj))


def test_jobs_are_signed_scoped_and_lifecycle_tracked(auth_client):
    c, org_id, _ = auth_client
    dev, agent = _device(c, org_id)
    other, other_agent = _device(c, org_id, "agent-v2-other")
    key = c.get("/v1/agent/server-key").json()["public_key"]
    run = c.post(f"/v1/devices/{dev['id']}/command", json={"body": "uname -a", "description": "test"}).json()

    jobs = c.get(f"/v1/agent/jobs?device_id={dev['id']}", headers=agent).json()["jobs"]
    assert len(jobs) == 1
    env = jobs[0]["envelope"]
    _verify(key, env, jobs[0]["signature"])  # raises if the signature is wrong
    assert env["purpose"] == "proofos.agent.job.v1" and env["device_id"] == dev["id"] and env["run_id"] == run["run_id"]
    assert env["body"] == "uname -a" and env["body_sha256"] == hashlib.sha256(b"uname -a").hexdigest()
    assert c.get(f"/v1/agent/jobs?device_id={dev['id']}", headers=other_agent).status_code == 401
    assert c.get(f"/v1/agent/jobs?device_id={other['id']}", headers=other_agent).json()["jobs"] == []
    assert c.post(f"/v1/agent/runs/{run['run_id']}/start", headers=other_agent).status_code == 401

    assert c.post(f"/v1/agent/runs/{run['run_id']}/start", headers=agent).json()["status"] == "running"
    assert c.get(f"/v1/agent/jobs?device_id={dev['id']}", headers=agent).json()["jobs"] == []  # not handed out twice
    assert c.post(f"/v1/agent/runs/{run['run_id']}/output", headers=agent, json={"chunk": "Linux host 6.8\n"}).json() == {"cancel": False}
    live = c.get(f"/v1/scripts/runs/{run['run_id']}").json()
    assert live["status"] == "running" and live["output"] == "Linux host 6.8\n" and live["started_at"]

    assert c.post(f"/v1/scripts/runs/{run['run_id']}/complete", headers=agent, json={"output": "Linux host 6.8\n", "exit_code": 0}).status_code == 200
    done = c.get(f"/v1/scripts/runs/{run['run_id']}").json()
    assert done["status"] == "completed" and done["exit_code"] == 0
    assert c.post(f"/v1/agent/runs/{run['run_id']}/output", headers=agent, json={"chunk": "late"}).status_code == 409


def test_cancel_pending_and_running_runs(auth_client):
    c, org_id, _ = auth_client
    dev, agent = _device(c, org_id, "agent-cancel")
    queued = c.post(f"/v1/devices/{dev['id']}/command", json={"body": "sleep 600", "description": "t"}).json()["run_id"]
    assert c.post(f"/v1/scripts/runs/{queued}/cancel").json()["status"] == "cancelled"
    assert c.post(f"/v1/agent/runs/{queued}/start", headers=agent).status_code == 409
    assert c.get(f"/v1/agent/jobs?device_id={dev['id']}", headers=agent).json()["jobs"] == []

    running = c.post(f"/v1/devices/{dev['id']}/command", json={"body": "sleep 600", "description": "t"}).json()["run_id"]
    c.post(f"/v1/agent/runs/{running}/start", headers=agent)
    assert c.post(f"/v1/scripts/runs/{running}/cancel").json()["status"] == "cancelling"
    assert c.post(f"/v1/agent/runs/{running}/output", headers=agent, json={"chunk": "x"}).json() == {"cancel": True}
    c.post(f"/v1/scripts/runs/{running}/complete", headers=agent, json={"output": "x\n[cancelled by operator]", "exit_code": 130})
    assert c.get(f"/v1/scripts/runs/{running}").json()["status"] == "cancelled"
    assert c.post(f"/v1/scripts/runs/{running}/cancel").status_code == 409


def test_push_channel_wakes_agent_and_streams_output(auth_client):
    c, org_id, _ = auth_client
    dev, agent = _device(c, org_id, "agent-push")
    import pytest
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as refused:
        with c.websocket_connect(f"/v1/agent/ws?device_id={dev['id']}", headers={"X-Agent-Token": "wrong"}) as bad:
            bad.receive_text()
    assert refused.value.code == 1008
    with c.websocket_connect(f"/v1/agent/ws?device_id={dev['id']}", headers=agent) as ws:
        assert json.loads(ws.receive_text()) == {"type": "jobs"}  # initial sweep
        ws.send_text(json.dumps({"type": "hello", "version": "2.0.0", "capabilities": ["signed-jobs"]}))
        ws.send_text(json.dumps({"type": "ping"}))
        assert json.loads(ws.receive_text()) == {"type": "pong"}
        run = c.post(f"/v1/devices/{dev['id']}/command", json={"body": "df -h", "description": "t"}).json()["run_id"]
        assert json.loads(ws.receive_text()) == {"type": "jobs"}  # pushed on commit, no polling
        c.post(f"/v1/agent/runs/{run}/start", headers=agent)
        ws.send_text(json.dumps({"type": "output", "run_id": run, "chunk": "Filesystem Size\n"}))
        ws.send_text(json.dumps({"type": "ping"}))
        assert json.loads(ws.receive_text()) == {"type": "pong"}  # output handled before the ping reply
        assert c.get(f"/v1/scripts/runs/{run}").json()["output"] == "Filesystem Size\n"
        c.post(f"/v1/scripts/runs/{run}/cancel")
        assert json.loads(ws.receive_text()) == {"type": "cancel", "run_id": run}
    assert c.get(f"/v1/devices/{dev['id']}").json()["agent_version"] == "2.0.0"


def test_release_is_signed_and_matches_download(client):
    key = client.get("/v1/agent/server-key").json()["public_key"]
    info = client.get("/v1/agent/release").json()
    manifest = {k: info[k] for k in ("purpose", "version", "sha256", "size")}
    _verify(key, manifest, info["signature"])
    data = client.get("/v1/agent/download").content
    assert hashlib.sha256(data).hexdigest() == info["sha256"] and len(data) == info["size"] and info["version"] == "2.1.0"


def test_published_agent_matches_source():
    import pathlib
    import runpy

    build = runpy.run_path(str(pathlib.Path(__file__).resolve().parents[3] / "apps" / "agent" / "build.py"))
    assert build["PUBLISHED"].read_bytes() == build["build"](), "run python apps/agent/build.py"


def test_fleet_view_policy_bulk_exec_and_update(auth_client):
    c, org_id, _ = auth_client
    a, a_agent = _device(c, org_id, "fleet-a")
    b, b_agent = _device(c, org_id, "fleet-b")
    bare, _ = _device(c, org_id, "fleet-noagent")
    c.post(f"/v1/devices/{a['id']}/heartbeat", headers=a_agent, json={"agent_version": "2.1.0", "agent_locked": False, "agent_spooled": 0})
    c.post(f"/v1/devices/{b['id']}/heartbeat", headers=b_agent, json={"agent_version": "2.0.0", "agent_locked": True, "agent_spooled": 3})

    with c.websocket_connect(f"/v1/agent/ws?device_id={a['id']}", headers=a_agent) as ws:
        assert json.loads(ws.receive_text()) == {"type": "jobs"}
        ws.send_text(json.dumps({"type": "hello", "version": "2.1.0"}))
        ws.send_text(json.dumps({"type": "ping"}))
        json.loads(ws.receive_text())
        fleet = c.get("/v1/agent/fleet").json()
        rows = {r["hostname"]: r for r in fleet["agents"]}
        assert fleet["latest_version"] == "2.1.0"
        assert rows["fleet-a"]["push_connected"] and rows["fleet-a"]["health"] == "healthy" and not rows["fleet-a"]["outdated"]
        assert rows["fleet-b"]["outdated"] and rows["fleet-b"]["locked"] and rows["fleet-b"]["spooled"] == 3 and rows["fleet-b"]["health"] == "restricted"
        assert rows["fleet-noagent"]["health"] == "not_installed"

        update = c.post("/v1/agent/fleet/update", json={"device_ids": [a["id"], b["id"]]}).json()
        assert update == {"notified": [a["id"]], "not_connected": [b["id"]]}
        assert json.loads(ws.receive_text()) == {"type": "update"}

        result = c.post("/v1/agent/fleet/exec", json={"device_ids": [a["id"], b["id"]], "body": "uptime"}).json()["results"]
        assert all(r["ok"] for r in result)
        assert json.loads(ws.receive_text()) == {"type": "jobs"}

    # Server policy blocks every queue path and cancels jobs already queued.
    assert c.post("/v1/agent/fleet/policy", json={"device_ids": [b["id"]], "exec_enabled": False}).json()["updated"] == 1
    assert c.get(f"/v1/agent/jobs?device_id={b['id']}", headers=b_agent).json()["jobs"] == []
    blocked = c.post("/v1/agent/fleet/exec", json={"device_ids": [a["id"], b["id"]], "body": "whoami"}).json()["results"]
    assert [r["ok"] for r in blocked] == [True, False] and "disabled" in blocked[1]["error"]
    assert c.post(f"/v1/devices/{b['id']}/command", json={"body": "id", "description": "t"}).status_code == 409
    assert c.get("/v1/agent/fleet").json()["summary"]["restricted"] == 1

    assert c.post("/v1/agent/fleet/exec", json={"device_ids": [999999], "body": "x"}).status_code == 404
    other = c.post("/v1/auth/bootstrap", json={"name": "Other fleet tenant"}).json()
    assert c.get("/v1/agent/fleet", headers={"Authorization": f"Bearer {other['access_token']}"}).json()["agents"] == []
    assert c.post("/v1/agent/fleet/policy", headers={"Authorization": f"Bearer {other['access_token']}"}, json={"device_ids": [a["id"]], "exec_enabled": False}).status_code == 404
