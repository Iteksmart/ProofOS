"""Turn package-manager listings returned by the agent into patch records."""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.models.models import Patch

SCAN_PREFIX = "patch-scan"
_APT = re.compile(r"^(?P<name>[a-z0-9][a-z0-9+.\-]*)/(?P<repo>\S+)\s+(?P<available>\S+)\s+\S+\s+\[upgradable from:\s*(?P<current>[^\]]+)\]")
_YUM = re.compile(r"^(?P<name>[A-Za-z0-9][\w+.\-]*)\.(?P<arch>x86_64|noarch|i686|aarch64|ppc64le|s390x)\s+(?P<available>\S+)\s+(?P<repo>\S+)\s*$")


def parse_apt(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        m = _APT.match(line.strip())
        if m:
            security = "security" in m.group("repo")
            out.append({"name": m.group("name"), "current_version": m.group("current").strip(), "available_version": m.group("available"),
                "category": "security" if security else "os", "severity": "important" if security else "moderate"})
    return out


def parse_yum(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        m = _YUM.match(line.strip())
        if m:
            security = "security" in m.group("repo").lower()
            out.append({"name": m.group("name"), "current_version": "", "available_version": m.group("available"),
                "category": "security" if security else "os", "severity": "important" if security else "moderate"})
    return out


def parse_winget(text: str) -> list[dict]:
    """winget prints a fixed-width table; column starts come from the header row."""
    lines = [re.sub(r"[\r\x08]|\x1b\[[0-9;]*[A-Za-z]", "", l) for l in text.splitlines()]
    header_index = next((i for i, l in enumerate(lines) if re.search(r"\bName\s+Id\s+Version\s+Available\b", l)), None)
    if header_index is None:
        return []
    header = lines[header_index]
    header = header[header.index("Name"):]
    offset = lines[header_index].index("Name")
    cols = {key: header.index(key) for key in ("Name", "Id", "Version", "Available")}
    source = header.find("Source")
    out = []
    for raw in lines[header_index + 1:]:
        line = raw[offset:] if len(raw) > offset else raw
        if not line.strip() or set(line.strip()) <= {"-"} or re.match(r"^\d+ upgrades? available", line.strip()):
            continue
        if len(line) < cols["Available"]:
            continue
        name = line[: cols["Id"]].strip()
        package_id = line[cols["Id"]: cols["Version"]].strip()
        current = line[cols["Version"]: cols["Available"]].strip()
        available = (line[cols["Available"]: source] if source > 0 else line[cols["Available"]:]).strip()
        if name and available and package_id:
            out.append({"name": f"{name} [{package_id}]", "current_version": current, "available_version": available.split()[0],
                "category": "third_party", "severity": "moderate"})
    return out


_SEVERITY = {"critical": "critical", "important": "important", "moderate": "moderate", "low": "low"}


def parse_windows_update(text: str) -> list[dict]:
    """Lines written by the scan script: WU|KB<id>|<MsrcSeverity>|<categories>|<title>."""
    out = []
    for line in text.splitlines():
        parts = line.strip().split("|", 4)
        if len(parts) != 5 or parts[0] != "WU":
            continue
        kb, severity, categories, title = parts[1], parts[2].strip().lower(), parts[3].lower(), parts[4].strip()
        security = "security" in categories or "critical updates" in categories
        out.append({"name": f"{title} ({kb})" if kb not in ("KB", "") and kb not in title else title,
            "current_version": "", "available_version": kb if kb != "KB" else "",
            "category": "security" if security else "os", "severity": _SEVERITY.get(severity, "important" if security else "moderate")})
    return out


def parse(output: str) -> list[dict]:
    rows = parse_windows_update(output)
    for parser in (parse_apt, parse_winget, parse_yum):
        found = parser(output)
        if found:
            return rows + found
    return rows


def apply(db: Session, org_id: int, device_id: int, rows: list[dict]) -> dict:
    """Create new patch records and refresh versions on open ones; never touches installed history."""
    created = updated = 0
    open_by_name = {p.name: p for p in db.query(Patch).filter(Patch.org_id == org_id, Patch.device_id == device_id,
        Patch.status.in_(["pending", "failed", "deploying"])).all()}
    for row in rows:
        existing = open_by_name.get(row["name"])
        if existing:
            if existing.available_version != row["available_version"] and existing.status != "deploying":
                existing.available_version = row["available_version"]
                existing.current_version = row["current_version"] or existing.current_version
                updated += 1
            continue
        patch = Patch(org_id=org_id, device_id=device_id, **row)
        db.add(patch)
        open_by_name[row["name"]] = patch
        created += 1
    return {"found": len(rows), "created": created, "updated": updated}
