"""ProofOS RMM agent — inventory, heartbeat, script poll/exec.

Usage:
  python agent.py --api http://localhost:8000 --device-id 1 [--interval 15]
"""
from __future__ import annotations

import argparse
import logging
import os
import platform
import socket
import subprocess
import time

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("proofos-agent")

AGENT_VERSION = "1.0.0"
MAX_OUTPUT = 20000


def inventory() -> dict:
    try:
        import psutil

        cpu = float(psutil.cpu_percent(interval=0.1))
        mem = float(psutil.virtual_memory().percent)
        try:
            disk = float(psutil.disk_usage("C:/" if platform.system() == "Windows" else "/").percent)
        except OSError:
            disk = 0.0
    except Exception:
        cpu = mem = disk = 0.0
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except OSError:
        ip = ""
    return {
        "hostname": socket.gethostname(),
        "os": platform.system() + " " + platform.release(),
        "ip": ip,
        "status": "online",
        "cpu": cpu,
        "disk": disk,
        "mem": mem,
    }


def heartbeat(client: httpx.Client, device_id: int) -> bool:
    data = inventory()
    r = client.post(
        f"/v1/devices/{device_id}/heartbeat",
        json={
            "cpu": data["cpu"],
            "disk": data["disk"],
            "mem": data["mem"],
            "status": data["status"],
            "agent_version": AGENT_VERSION,
        },
    )
    return r.status_code == 200


def poll_scripts(client: httpx.Client, device_id: int) -> list:
    r = client.get("/v1/scripts/runs/pending", params={"device_id": device_id}, timeout=10)
    r.raise_for_status()
    jobs = r.json()
    return jobs if isinstance(jobs, list) else []


def exec_script(script_body: str, timeout: int = 120) -> tuple[str, int]:
    if not script_body.strip():
        return "", 0
    try:
        proc = subprocess.run(
            script_body,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = ((proc.stdout or "") + (proc.stderr or ""))[:MAX_OUTPUT]
        return out, proc.returncode
    except subprocess.TimeoutExpired:
        return f"timeout after {timeout}s", 124
    except Exception as e:
        return f"exec error: {e}", 1


def complete(client: httpx.Client, run_id: int, output: str, exit_code: int) -> bool:
    r = client.post(
        f"/v1/scripts/runs/{run_id}/complete",
        json={"output": output, "exit_code": exit_code},
        timeout=10,
    )
    return r.status_code == 200


def loop(api: str, device_id: int, interval: int = 15, token: str = "") -> None:
    headers = {"X-Agent-Token": token} if token else {}
    client = httpx.Client(base_url=api.rstrip("/"), timeout=15, headers=headers)
    log.info("agent start device=%s api=%s interval=%s", device_id, api, interval)
    delay = interval
    while True:
        try:
            ok = heartbeat(client, device_id)
            if not ok:
                log.warning("heartbeat non-200 (device may not exist)")
            for job in poll_scripts(client, device_id):
                body = job.get("body", "")
                log.info("exec run=%s script=%s", job.get("id"), job.get("name"))
                out, code = exec_script(body)
                if complete(client, job["id"], out, code):
                    log.info("run %s done code=%s", job["id"], code)
                else:
                    log.warning("complete failed run=%s", job["id"])
            delay = interval
        except Exception as e:
            log.warning("loop error: %s (backoff %ss)", e, delay)
            delay = min(delay * 2, 120)
        time.sleep(delay)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--device-id", type=int, default=1)
    ap.add_argument("--interval", type=int, default=15)
    ap.add_argument("--token", default=os.getenv("AGENT_TOKEN", ""), help="Agent auth token (X-Agent-Token)")
    args = ap.parse_args()
    print("ProofOS agent", inventory())
    loop(args.api, args.device_id, args.interval, args.token)


if __name__ == "__main__":
    main()
