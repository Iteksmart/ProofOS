"""Agent-side guarantees: nothing runs unless it is signed, current, addressed here and allowed locally."""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import pathlib
import sys
import threading
import time

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from proofos_agent import executor, jobs, service, updater  # noqa: E402
from proofos_agent.state import State  # noqa: E402

KEY = Ed25519PrivateKey.generate()
PUB = KEY.public_key().public_bytes_raw().hex()
NOW = dt.datetime(2026, 11, 17, 12, tzinfo=dt.timezone.utc)


def signed(body="echo hi", device_id=7, run_id=1, expires=NOW + dt.timedelta(hours=1), key=KEY, **override):
    env = {"purpose": jobs.JOB_PURPOSE, "run_id": run_id, "device_id": device_id, "org_id": 1, "name": "t", "body": body,
           "body_sha256": hashlib.sha256(body.encode()).hexdigest(), "timeout_s": 60, "issued_at": NOW.isoformat(),
           "expires_at": expires.isoformat(), "nonce": "ab", **override}
    return {"envelope": env, "signature": base64.b64encode(key.sign(jobs.canonical(env))).decode()}


def check(job, seen=frozenset()):
    return jobs.check(job, public_key_hex=PUB, device_id=7, seen=set(seen), now=NOW)


def test_valid_job_passes():
    assert check(signed())["body"] == "echo hi"


@pytest.mark.parametrize("job, reason", [
    (signed(key=Ed25519PrivateKey.generate()), "signature"),
    (signed(device_id=8), "another device"),
    (signed(expires=NOW - dt.timedelta(seconds=1)), "expired"),
    (signed(purpose="proofos.agent.release.v1"), "not an agent job"),
    (signed(body_sha256="0" * 64), "signed hash"),
    ({"envelope": "x", "signature": 1}, "malformed"),
])
def test_rejections(job, reason):
    with pytest.raises(jobs.Rejected, match=reason):
        check(job)


def test_tampered_body_or_replay_is_rejected():
    job = signed()
    job["envelope"]["body"] = "rm -rf /"
    with pytest.raises(jobs.Rejected, match="signature"):
        check(job)
    with pytest.raises(jobs.Rejected, match="replay"):
        check(signed(run_id=5), seen={5})


def test_local_policy_wins():
    assert jobs.policy_block("ls", allow_commands=True, deny_patterns=[], locked=False) is None
    assert "locked" in jobs.policy_block("ls", allow_commands=True, deny_patterns=[], locked=True)
    assert "disabled" in jobs.policy_block("ls", allow_commands=False, deny_patterns=[], locked=False)
    assert "deny rule" in jobs.policy_block("Format-Volume -DriveLetter C", allow_commands=True, deny_patterns=[r"format-volume"], locked=False)


def test_state_persists_seen_runs_and_lockdown(tmp_path):
    state = State(tmp_path)
    state.mark_seen(41)
    state.set_lockdown(True)
    again = State(tmp_path)
    assert 41 in again.seen and again.locked
    again.set_lockdown(False)
    assert not State(tmp_path).locked
    state.spool_result(9, "out", 0)
    assert [p.name for p in State(tmp_path).spooled()] == ["9.json"]


def test_interpreter_directive():
    assert executor.interpreter_of("#proofos:shell=powershell\nGet-Date") == ("powershell", "Get-Date")
    assert executor.interpreter_of("#proofos:shell=evil\nx")[1].startswith("#proofos")
    assert executor.interpreter_of("ls")[0] == ("cmd" if sys.platform.startswith("win") else "sh")


def test_executor_streams_and_cancels(tmp_path):
    chunks = []
    out, code = executor.run(f'"{sys.executable}" -c "print(1); print(2)"', timeout=30, workdir=str(tmp_path), on_output=chunks.append)
    assert code == 0 and out.split() == ["1", "2"] and "".join(chunks).split() == ["1", "2"]

    handle = executor.Running()
    threading.Timer(1.0, handle.cancelled.set).start()
    started = time.monotonic()
    body = f'"{sys.executable}" -c "import time; [time.sleep(0.2) for _ in range(300)]"'
    out, code = executor.run(body, timeout=60, workdir=str(tmp_path), on_output=lambda c: None, handle=handle)
    assert code == 130 and "cancelled" in out and time.monotonic() - started < 10

    out, code = executor.run(f'"{sys.executable}" -c "import sys; sys.exit(3)"', timeout=30, workdir=str(tmp_path), on_output=lambda c: None)
    assert code == 3


def test_update_requires_server_signature(tmp_path, monkeypatch):
    target = tmp_path / "proofos-agent.pyz"
    target.write_bytes(b"old")
    payload = b"new build"
    manifest = {"purpose": jobs.RELEASE_PURPOSE, "version": "99.0.0", "sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload)}

    def server(sig_key):
        sig = base64.b64encode(sig_key.sign(jobs.canonical(manifest))).decode()
        return httpx.Client(base_url="http://srv", transport=httpx.MockTransport(lambda r: httpx.Response(200,
            json={**manifest, "signature": sig}) if r.url.path.endswith("/release") else httpx.Response(200, content=payload)))

    assert updater.apply_if_newer(server(Ed25519PrivateKey.generate()), PUB, target) is False
    assert target.read_bytes() == b"old"
    assert updater.apply_if_newer(server(KEY), PUB, target) is True
    assert target.read_bytes() == payload


def test_service_definitions_render():
    pyz, cfg = pathlib.Path("/opt/proofos-agent/proofos-agent.pyz"), pathlib.Path("/etc/proofos-agent/config.json")
    assert "Restart=always" in service.systemd_unit("/usr/bin/python3", pyz, cfg)
    assert "<key>KeepAlive</key><true/>" in service.launchd_plist("/usr/bin/python3", pyz, cfg)
    xml = service.windows_task_xml(r"C:\Python\pythonw.exe", pyz, cfg)
    assert "S-1-5-18" in xml and "<RestartOnFailure>" in xml and "&quot;" not in xml.split("<Arguments>")[0]
