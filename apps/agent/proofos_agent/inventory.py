"""Hardware, OS and software inventory collected on the endpoint."""
from __future__ import annotations

import datetime as dt
import json
import os
import platform
import socket
import subprocess
import sys

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
