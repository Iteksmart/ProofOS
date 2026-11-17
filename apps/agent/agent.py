"""ProofOS RMM agent — inventory, heartbeat, script poll/exec.

Usage:
  python agent.py --api http://localhost:8000 --device-id 1 [--interval 15]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import platform
import socket
import subprocess
import sys
import time

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("proofos-agent")

AGENT_VERSION = "1.1.0"
MAX_OUTPUT = 20000


def software_inventory() -> list[dict]:
    """Use native package databases; never invoke Win32_Product (it repairs MSI)."""
    packages = {}
    if platform.system() == "Windows":
        import winreg
        path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                try:
                    with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | view) as root:
                        for index in range(winreg.QueryInfoKey(root)[0]):
                            try:
                                with winreg.OpenKey(root, winreg.EnumKey(root, index)) as item:
                                    def value(name):
                                        try:
                                            return str(winreg.QueryValueEx(item, name)[0])
                                        except OSError:
                                            return ""
                                    name, version = value("DisplayName"), value("DisplayVersion")
                                    if name:
                                        packages[(name, version)] = {"name": name[:500], "version": version[:255], "publisher": value("Publisher")[:500]}
                            except OSError:
                                continue
                except OSError:
                    continue
    else:
        import shutil
        if shutil.which("dpkg-query"):
            cmd = ["dpkg-query", "-W", "-f=${Package}\t${Version}\t${source:Package}\t${source:Version}\n"]
        elif shutil.which("rpm"):
            cmd = ["rpm", "-qa", "--qf", "%{NAME}\t%{VERSION}-%{RELEASE}\n"]
        elif platform.system() == "Darwin":
            cmd = ["system_profiler", "SPApplicationsDataType", "-json"]
        else:
            raise RuntimeError("No supported native software inventory provider")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=True)
        if platform.system() == "Darwin":
            for app in json.loads(result.stdout).get("SPApplicationsDataType", []):
                name, version = app.get("_name", ""), app.get("version", "")
                if name:
                    packages[(name, version)] = {"name": name[:500], "version": version[:255], "publisher": ""}
        else:
            for line in result.stdout.splitlines():
                fields = line.split("\t")
                name, version = fields[0], fields[1] if len(fields) > 1 else ""
                if name:
                    packages[(name, version)] = {"name": name[:500], "version": version[:255], "publisher": "",
                        "source": (fields[2] if len(fields) > 2 else "")[:255], "source_version": (fields[3] if len(fields) > 3 else "")[:255]}
    return sorted(packages.values(), key=lambda p: p["name"].lower())


def os_release() -> dict:
    """Distribution id and version from /etc/os-release, used to match OSV advisories."""
    try:
        with open("/etc/os-release", encoding="utf-8") as handle:
            pairs = dict(line.rstrip("\n").split("=", 1) for line in handle if "=" in line)
    except OSError:
        return {}
    return {key.lower(): pairs[key].strip('"')[:100] for key in ("ID", "VERSION_ID") if key in pairs}


def detailed_inventory() -> dict:
    import psutil
    data = {"hostname": socket.gethostname(), "os": platform.platform(), "hardware": {
        "processor": platform.processor(), "architecture": platform.machine(),
        "physical_cores": psutil.cpu_count(logical=False), "logical_cores": psutil.cpu_count(),
        "memory_bytes": psutil.virtual_memory().total,
        "boot_time": dt.datetime.fromtimestamp(psutil.boot_time(), dt.timezone.utc).isoformat()},
        "disks": [], "networks": [], "software": [], "errors": [], "software_status": "unavailable", "os_release": os_release()}
    if platform.system() == "Linux":
        from pathlib import Path
        for field, filename in (("manufacturer", "sys_vendor"), ("model", "product_name")):
            try:
                data["hardware"][field] = Path(f"/sys/class/dmi/id/{filename}").read_text().strip()[:255]
            except OSError:
                pass
    elif platform.system() == "Windows":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS") as key:
                for field, name in (("manufacturer", "SystemManufacturer"), ("model", "SystemProductName")):
                    data["hardware"][field] = str(winreg.QueryValueEx(key, name)[0])[:255]
        except OSError:
            data["errors"].append("System manufacturer/model unavailable")
    for disk in psutil.disk_partitions()[:256]:
        try:
            usage = psutil.disk_usage(disk.mountpoint)
            data["disks"].append({"device": disk.device[:255], "mountpoint": disk.mountpoint[:1024],
                "filesystem": disk.fstype[:100], "total_bytes": usage.total, "free_bytes": usage.free})
        except OSError:
            continue
    for name, addresses in psutil.net_if_addrs().items():
        for address in addresses:
            data["networks"].append({"name": name[:255], "address": address.address[:255], "family": str(address.family)[:40]})
    data["networks"] = data["networks"][:1024]
    try:
        software = software_inventory()
        data["software"] = software[:5000]
        data["software_status"] = "partial" if len(software) > 5000 else "complete"
    except Exception as exc:
        data["errors"].append(f"Software collection unavailable: {type(exc).__name__}")
    return data


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


def reboot_required() -> bool | None:
    """True when the OS reports a pending reboot; None when it cannot be determined."""
    try:
        if sys.platform.startswith("win"):
            import winreg

            for key in (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending",
                        r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired"):
                try:
                    winreg.CloseKey(winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key))
                    return True
                except OSError:
                    continue
            return False
        if sys.platform.startswith("linux"):
            return os.path.exists("/var/run/reboot-required")
    except Exception:  # noqa: BLE001 - never let detection break the heartbeat
        return None
    return None


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
            "reboot_required": reboot_required(),
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
    next_inventory = 0.0
    while True:
        try:
            ok = heartbeat(client, device_id)
            if not ok:
                log.warning("heartbeat non-200 (device may not exist)")
            if ok and time.monotonic() >= next_inventory:
                try:
                    response = client.post(f"/v1/devices/{device_id}/inventory", json=detailed_inventory(), timeout=45)
                    response.raise_for_status()
                    next_inventory = time.monotonic() + 3600
                    log.info("inventory uploaded device=%s", device_id)
                except Exception as exc:
                    next_inventory = time.monotonic() + 300
                    log.warning("inventory upload failed: %s", exc)
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
