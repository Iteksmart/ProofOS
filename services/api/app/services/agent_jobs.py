"""Signed job envelopes for ProofOS agents, the push hub, and agent releases.

Every job an agent runs is wrapped in an envelope signed with the platform's
Ed25519 key. The agent pins that public key at enrollment and refuses any job
whose signature, device, expiry or command hash does not check out, so a
network attacker or a tampered queue cannot make an endpoint execute anything.
"""
from __future__ import annotations

import asyncio
import base64
import datetime as dt
import hashlib
import json
import logging
import pathlib
import secrets
import threading

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.proof import canonical, get_signing_key, public_key_hex
from app.models.models import Script, ScriptRun

log = logging.getLogger("proofos.agent")

JOB_PURPOSE = "proofos.agent.job.v1"
RELEASE_PURPOSE = "proofos.agent.release.v1"
JOB_TTL = dt.timedelta(hours=24)  # queued jobs older than this are never executed
DEFAULT_TIMEOUT = 600
MAX_STORED_OUTPUT = 20000
DIST = pathlib.Path(__file__).resolve().parent.parent / "agent_dist" / "proofos-agent.pyz"


def sign(obj: dict) -> str:
    return base64.b64encode(get_signing_key().sign(canonical(obj))).decode()


def _aware(value: dt.datetime) -> dt.datetime:
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


def timeout_for(script: Script) -> int:
    """Long-running maintenance gets more time; everything else the default."""
    if script.name.startswith(("patch-deploy:", "patch-scan", "software-")):
        return 3600
    return DEFAULT_TIMEOUT


def envelope(run: ScriptRun, script: Script) -> dict:
    issued = _aware(run.created_at)
    env = {
        "purpose": JOB_PURPOSE,
        "run_id": run.id,
        "device_id": run.device_id,
        "org_id": run.org_id,
        "name": script.name,
        "body": script.body,
        "body_sha256": hashlib.sha256(script.body.encode()).hexdigest(),
        "timeout_s": timeout_for(script),
        "issued_at": issued.isoformat(),
        "expires_at": (issued + JOB_TTL).isoformat(),
        "nonce": secrets.token_hex(8),
    }
    return {"envelope": env, "signature": sign(env), "key_id": "ed25519:proofos-1"}


def pending_jobs(db: Session, device_id: int) -> list[dict]:
    now = dt.datetime.now(dt.timezone.utc)
    jobs = []
    for run in db.query(ScriptRun).filter(ScriptRun.device_id == device_id, ScriptRun.status == "pending").order_by(ScriptRun.id).all():
        if _aware(run.created_at) + JOB_TTL < now:
            run.status, run.completed_at = "expired", now
            continue
        script = db.get(Script, run.script_id)
        if script:
            jobs.append(envelope(run, script))
    db.commit()
    return jobs


def append_output(db: Session, run: ScriptRun, chunk: str) -> None:
    from app.core.pubsub import publish

    room = MAX_STORED_OUTPUT - len(run.output or "")
    if room > 0:
        run.output = (run.output or "") + chunk[:room]
    db.commit()
    publish({"type": "run.output", "org_id": run.org_id, "run_id": run.id, "device_id": run.device_id, "chunk": chunk[:8000]})


def release() -> dict | None:
    if not DIST.exists():
        return None
    data = DIST.read_bytes()
    version = ""
    import zipfile
    import io

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for line in zf.read("proofos_agent/__init__.py").decode().splitlines():
            if line.startswith("__version__"):
                version = line.split("=", 1)[1].strip().strip("\"'")
    manifest = {"purpose": RELEASE_PURPOSE, "version": version, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    return {**manifest, "signature": sign(manifest), "public_key": public_key_hex(), "url": "/v1/agent/download"}


class AgentHub:
    """Live WebSocket connections from agents, keyed by device id."""

    def __init__(self) -> None:
        self._sockets: dict[int, object] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()

    def attach(self, device_id: int, ws, loop: asyncio.AbstractEventLoop) -> None:
        with self._lock:
            self._sockets[device_id] = ws
            self._loop = loop

    def detach(self, device_id: int, ws) -> None:
        with self._lock:
            if self._sockets.get(device_id) is ws:
                del self._sockets[device_id]

    def connected(self, device_id: int) -> bool:
        return device_id in self._sockets

    def notify(self, device_id: int, message: dict) -> bool:
        """Thread-safe: callable from sync request handlers."""
        ws, loop = self._sockets.get(device_id), self._loop
        if ws is None or loop is None or loop.is_closed():
            return False
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        coro = ws.send_text(json.dumps(message))
        if running is loop:
            loop.create_task(coro)
        else:
            asyncio.run_coroutine_threadsafe(coro, loop)
        return True


hub = AgentHub()


@event.listens_for(Session, "after_flush")
def _collect_new_runs(session, flush_context) -> None:
    for obj in session.new:
        if isinstance(obj, ScriptRun) and obj.status == "pending":
            session.info.setdefault("agent_wake", set()).add(obj.device_id)


@event.listens_for(Session, "after_commit")
def _wake_agents(session) -> None:
    for device_id in session.info.pop("agent_wake", set()):
        if hub.notify(device_id, {"type": "jobs"}):
            log.info("pushed job notice to device %s", device_id)


@event.listens_for(Session, "after_rollback")
def _forget(session) -> None:
    session.info.pop("agent_wake", None)
