"""The agent runtime: heartbeat, inventory, push channel, verified job execution and result delivery."""
from __future__ import annotations

import concurrent.futures
import json
import logging
import threading
import time

import httpx

from proofos_agent import __version__, executor, inventory, jobs, updater
from proofos_agent.config import Config
from proofos_agent.state import State

log = logging.getLogger("proofos-agent")
CAPABILITIES = ["signed-jobs", "push", "stream-output", "cancel", "spool", "self-update", "lockdown",
                "shell:sh", "shell:bash", "shell:cmd", "shell:powershell", "shell:pwsh", "shell:python"]


class Agent:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.state = State(cfg.state)
        self.http = httpx.Client(base_url=cfg.api.rstrip("/"), timeout=20, verify=cfg.verify(),
            headers={"X-Agent-Token": cfg.token, "User-Agent": f"proofos-agent/{__version__}"})
        self.wake = threading.Event()
        self.stop = threading.Event()
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, cfg.max_concurrency), thread_name_prefix="job")
        self.running: dict[int, executor.Running] = {}
        self._ws = None
        self._ws_lock = threading.Lock()
        self.exit_code = 0

    # ---------------------------------------------------------------- push
    def _ws_url(self) -> str:
        base = self.cfg.api.rstrip("/")
        base = "wss://" + base[8:] if base.startswith("https://") else "ws://" + base.removeprefix("http://")
        return f"{base}/v1/agent/ws?device_id={self.cfg.device_id}"

    def push_loop(self) -> None:
        from websockets.sync.client import connect

        delay = 2
        while not self.stop.is_set():
            try:
                ssl_ctx = None
                if self.cfg.api.startswith("https://"):
                    import ssl

                    ssl_ctx = ssl.create_default_context(cafile=self.cfg.ca_bundle or None)
                with connect(self._ws_url(), additional_headers={"X-Agent-Token": self.cfg.token}, ssl=ssl_ctx,
                             open_timeout=15, close_timeout=5, max_size=2**20) as ws:
                    with self._ws_lock:
                        self._ws = ws
                    ws.send(json.dumps({"type": "hello", "version": __version__, "capabilities": CAPABILITIES}))
                    log.info("push channel connected")
                    delay = 2
                    last_ping = time.monotonic()
                    while not self.stop.is_set():
                        try:
                            raw = ws.recv(timeout=5)
                        except TimeoutError:
                            raw = None
                        if raw:
                            self._on_push(json.loads(raw))
                        if time.monotonic() - last_ping > 25:
                            ws.send(json.dumps({"type": "ping"}))
                            last_ping = time.monotonic()
            except Exception as exc:  # noqa: BLE001 - reconnect forever with backoff; polling covers the gap
                log.info("push channel unavailable (%s); retrying in %ss", type(exc).__name__, delay)
            finally:
                with self._ws_lock:
                    self._ws = None
            self.stop.wait(delay)
            delay = min(delay * 2, 60)

    def _on_push(self, msg: dict) -> None:
        if msg.get("type") == "jobs":
            self.wake.set()
        elif msg.get("type") == "cancel" and isinstance(msg.get("run_id"), int):
            handle = self.running.get(msg["run_id"])
            if handle:
                log.info("cancel requested run=%s", msg["run_id"])
                handle.cancelled.set()

    def _send_output(self, run_id: int, chunk: str) -> None:
        with self._ws_lock:
            ws = self._ws
        if ws is not None:
            try:
                ws.send(json.dumps({"type": "output", "run_id": run_id, "chunk": chunk[:60000]}))
                return
            except Exception:  # noqa: BLE001
                pass
        r = self.http.post(f"/v1/agent/runs/{run_id}/output", json={"chunk": chunk[:60000]})
        if r.status_code == 200 and r.json().get("cancel") and run_id in self.running:
            self.running[run_id].cancelled.set()

    # ---------------------------------------------------------------- jobs
    def fetch_jobs(self) -> None:
        r = self.http.get("/v1/agent/jobs", params={"device_id": self.cfg.device_id})
        r.raise_for_status()
        for job in r.json().get("jobs", []):
            run_id = (job.get("envelope") or {}).get("run_id")
            if run_id in self.running:
                continue
            try:
                env = jobs.check(job, public_key_hex=self.cfg.server_key, device_id=self.cfg.device_id, seen=self.state.seen)
            except jobs.Rejected as exc:
                log.warning("rejected job run=%s: %s", run_id, exc)
                if isinstance(run_id, int) and run_id not in self.state.seen:
                    self.state.mark_seen(run_id)
                    self._deliver(run_id, f"[ProofOS agent refused this job: {exc}]", 126)
                continue
            self.state.mark_seen(env["run_id"])
            self.running[env["run_id"]] = executor.Running()
            self.pool.submit(self._execute, env)

    def _execute(self, env: dict) -> None:
        run_id = env["run_id"]
        handle = self.running[run_id]
        try:
            blocked = jobs.policy_block(env["body"], allow_commands=self.cfg.allow_commands,
                deny_patterns=self.cfg.deny_patterns, locked=self.state.locked)
            if blocked:
                log.warning("run=%s blocked: %s", run_id, blocked)
                self._deliver(run_id, f"[ProofOS agent: {blocked}]", 126)
                return
            start = self.http.post(f"/v1/agent/runs/{run_id}/start")
            if start.status_code == 409:
                log.info("run=%s no longer wanted: %s", run_id, start.text[:200])
                return
            start.raise_for_status()
            log.info("exec run=%s name=%s timeout=%ss", run_id, env.get("name"), env.get("timeout_s"))
            output, code = executor.run(env["body"], timeout=int(env.get("timeout_s") or 600), workdir=str(self.state.work),
                on_output=lambda chunk: self._send_output(run_id, chunk), handle=handle)
            self._deliver(run_id, output, code)
            log.info("run=%s finished exit=%s", run_id, code)
        except Exception as exc:  # noqa: BLE001
            log.exception("run=%s failed in the agent", run_id)
            self._deliver(run_id, f"[ProofOS agent error: {exc}]", 1)
        finally:
            self.running.pop(run_id, None)

    def _deliver(self, run_id: int, output: str, exit_code: int) -> None:
        """Report the result, or keep it on disk until the server is reachable."""
        try:
            r = self.http.post(f"/v1/scripts/runs/{run_id}/complete", json={"output": output, "exit_code": exit_code})
            if r.status_code in {200, 404, 409}:
                return
        except httpx.HTTPError:
            pass
        self.state.spool_result(run_id, output, exit_code)
        log.warning("result for run=%s spooled for later delivery", run_id)

    def flush_spool(self) -> None:
        for path in self.state.spooled():
            data = json.loads(path.read_text(encoding="utf-8"))
            r = self.http.post(f"/v1/scripts/runs/{data['run_id']}/complete", json={"output": data["output"], "exit_code": data["exit_code"]})
            if r.status_code in {200, 404, 409}:
                path.unlink()
                log.info("delivered spooled result run=%s", data["run_id"])
            else:
                break

    # ---------------------------------------------------------------- loop
    def heartbeat(self) -> None:
        data = inventory.inventory()
        self.http.post(f"/v1/devices/{self.cfg.device_id}/heartbeat", json={"cpu": data["cpu"], "disk": data["disk"],
            "mem": data["mem"], "status": "online", "agent_version": __version__,
            "reboot_required": inventory.reboot_required()}).raise_for_status()

    def run_forever(self) -> int:
        log.info("ProofOS agent %s device=%s api=%s", __version__, self.cfg.device_id, self.cfg.api)
        threading.Thread(target=self.push_loop, name="push", daemon=True).start()
        next_beat = next_inventory = next_poll = 0.0
        next_update = time.monotonic() + 300
        backoff = self.cfg.interval
        while not self.stop.is_set():
            now = time.monotonic()
            try:
                if now >= next_beat:
                    self.heartbeat()
                    next_beat = now + self.cfg.interval
                if now >= next_inventory:
                    try:
                        self.http.post(f"/v1/devices/{self.cfg.device_id}/inventory", json=inventory.detailed_inventory(), timeout=60).raise_for_status()
                        next_inventory = now + 3600
                    except Exception as exc:  # noqa: BLE001
                        log.warning("inventory upload failed: %s", exc)
                        next_inventory = now + 300
                if self.wake.is_set() or now >= next_poll:
                    self.wake.clear()
                    self.fetch_jobs()
                    # With a live push channel, polling is only a safety net.
                    next_poll = now + (120 if self._ws is not None else self.cfg.interval)
                self.flush_spool()
                if self.cfg.auto_update and now >= next_update:
                    next_update = now + 6 * 3600
                    if updater.apply_if_newer(self.http, self.cfg.server_key) and not self.running:
                        log.info("update installed; exiting so the service manager restarts the new version")
                        self.exit_code = updater.RESTART_EXIT
                        self.stop.set()
                backoff = self.cfg.interval
            except Exception as exc:  # noqa: BLE001
                log.warning("cycle failed: %s (retry in %ss)", exc, backoff)
                self.wake.wait(backoff)
                backoff = min(backoff * 2, 300)
                continue
            self.wake.wait(1.0 if self.running else 2.0)
        self.pool.shutdown(wait=True, cancel_futures=False)
        return self.exit_code
