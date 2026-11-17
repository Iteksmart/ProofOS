"""Network discovery from an agent's ARP/neighbour table, and package install commands."""
from __future__ import annotations

import ipaddress
import re

DISCOVERY_SCRIPT = "network-discovery"
DISCOVERY_CMD = {
    "windows": "arp -a",
    "linux": "ip neigh show 2>/dev/null || arp -an",
    "macos": "arp -an",
}
_PACKAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+\-]{0,127}$")
_MAC = r"(?P<mac>(?:[0-9a-fA-F]{1,2}[:-]){5}[0-9a-fA-F]{1,2})"
_PATTERNS = [
    re.compile(r"^\s*(?P<ip>\d{1,3}(?:\.\d{1,3}){3})\s+" + _MAC + r"\s+(?P<kind>dynamic|static)", re.I),  # Windows arp -a
    re.compile(r"^(?P<ip>\d{1,3}(?:\.\d{1,3}){3})\s+dev\s+(?P<iface>\S+)\s+lladdr\s+" + _MAC + r"(?:\s+\S+)*\s+(?P<state>[A-Z]+)\s*$"),  # ip neigh
    re.compile(r"^\S+\s+\((?P<ip>\d{1,3}(?:\.\d{1,3}){3})\)\s+at\s+" + _MAC + r"\b"),  # arp -an
]


def os_key(os_name: str) -> str:
    os_name = (os_name or "").lower()
    return "windows" if os_name.startswith("windows") else "macos" if "mac" in os_name or "darwin" in os_name else "linux"


def parse_neighbours(text: str) -> list[dict]:
    found: dict[str, dict] = {}
    for line in text.splitlines():
        for pattern in _PATTERNS:
            m = pattern.match(line)
            if not m:
                continue
            state = (m.groupdict().get("state") or "").upper()
            if state in {"FAILED", "INCOMPLETE"}:
                break
            try:
                ip = ipaddress.ip_address(m.group("ip"))
            except ValueError:
                break
            mac = m.group("mac").lower().replace("-", ":")
            if ip.is_multicast or ip.is_unspecified or ip.is_loopback or str(ip).endswith(".255") or mac in {"ff:ff:ff:ff:ff:ff", "00:00:00:00:00:00"}:
                break
            found[str(ip)] = {"ip": str(ip), "mac": ":".join(part.zfill(2) for part in mac.split(":"))}
            break
    return sorted(found.values(), key=lambda r: tuple(int(x) for x in r["ip"].split(".")))


def valid_package(name: str) -> bool:
    return bool(_PACKAGE.match(name or ""))


def package_command(os_name: str, package: str, operation: str) -> str:
    """The package name is validated against a strict pattern before it reaches a shell."""
    if not valid_package(package):
        raise ValueError("invalid package name")
    key = os_key(os_name)
    if key == "windows":
        verb = "install" if operation == "install" else "uninstall"
        extra = " --accept-package-agreements" if operation == "install" else ""
        return f"winget {verb} --id {package} --exact --silent --accept-source-agreements{extra}"
    if key == "macos":
        return f"brew {'install' if operation == 'install' else 'uninstall'} {package}"
    if operation == "install":
        return f"sudo apt-get install -y {package} 2>/dev/null || sudo dnf install -y {package}"
    return f"sudo apt-get remove -y {package} 2>/dev/null || sudo dnf remove -y {package}"
