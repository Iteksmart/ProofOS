"""Match installed Linux packages against OSV (https://osv.dev) advisories."""
from __future__ import annotations

import datetime as dt
import json
import re

import httpx
from sqlalchemy.orm import Session

from app.models.models import Device, DeviceInventory, VulnerabilityFinding

OSV = "https://api.osv.dev/v1"
SEVERITIES = ["critical", "high", "medium", "low", "unknown"]
_RANK = {s: i for i, s in enumerate(SEVERITIES)}
_TEXT = {"critical": "critical", "high": "high", "important": "high", "medium": "medium", "moderate": "medium",
         "low": "low", "negligible": "low", "unimportant": "low", "not yet assigned": "unknown"}


def ecosystem(os_release: dict) -> str | None:
    """OSV ecosystem names for distributions whose advisories OSV publishes."""
    distro, version = (os_release.get("id") or "").lower(), os_release.get("version_id") or ""
    if not version:
        return None
    if distro == "ubuntu" and re.match(r"^\d{2}\.\d{2}$", version):
        year, month = version.split(".")
        return f"Ubuntu:{version}:LTS" if month == "04" and int(year) % 2 == 0 else f"Ubuntu:{version}"
    if distro == "debian":
        return f"Debian:{version.split('.')[0]}"
    if distro == "alpine":
        return "Alpine:v" + ".".join(version.split(".")[:2])
    if distro == "rocky":
        return f"Rocky Linux:{version.split('.')[0]}"
    if distro == "almalinux":
        return f"AlmaLinux:{version.split('.')[0]}"
    return None


def packages(payload: dict) -> list[tuple[str, str]]:
    """(name, version) pairs as OSV indexes them: Debian/Ubuntu by source package."""
    seen: dict[str, str] = {}
    for item in payload.get("software") or []:
        name = item.get("source") or item.get("name") or ""
        version = item.get("source_version") or item.get("version") or ""
        if name and version:
            seen.setdefault(name, version)
    return sorted(seen.items())


_CVSS3 = {"AV": {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.2}, "AC": {"L": 0.77, "H": 0.44}, "UI": {"N": 0.85, "R": 0.62},
          "C": {"H": 0.56, "L": 0.22, "N": 0.0}}


def _roundup(value: float) -> float:
    whole = round(value * 100000)
    return whole / 100000.0 if whole % 10000 == 0 else (whole // 10000 + 1) / 10.0


def cvss3_score(vector: str) -> float | None:
    """Base score of a CVSS v3.x vector (FIRST specification, section 7.1)."""
    try:
        m = dict(part.split(":", 1) for part in vector.split("/")[1:])
        changed = m["S"] == "C"
        pr = {"N": 0.85, "L": 0.68 if changed else 0.62, "H": 0.5 if changed else 0.27}[m["PR"]]
        iss = 1 - (1 - _CVSS3["C"][m["C"]]) * (1 - _CVSS3["C"][m["I"]]) * (1 - _CVSS3["C"][m["A"]])
        impact = 7.52 * (iss - 0.029) - 3.25 * (iss - 0.02) ** 15 if changed else 6.42 * iss
        exploit = 8.22 * _CVSS3["AV"][m["AV"]] * _CVSS3["AC"][m["AC"]] * pr * _CVSS3["UI"][m["UI"]]
    except (KeyError, ValueError):
        return None
    if impact <= 0:
        return 0.0
    return _roundup(min(1.08 * (impact + exploit), 10) if changed else min(impact + exploit, 10))


def _band(score: float) -> str:
    return "critical" if score >= 9 else "high" if score >= 7 else "medium" if score >= 4 else "low"


def _severity(vuln: dict, package: str) -> str:
    candidates = []
    scores = []
    for entry in vuln.get("severity") or []:
        kind, value = str(entry.get("type", "")), str(entry.get("score", ""))
        if kind.startswith("CVSS_V3"):
            score = cvss3_score(value)
            if score is not None:
                scores.append(score)
        elif value.lower() in _TEXT and _TEXT[value.lower()] != "unknown":
            candidates.append(_TEXT[value.lower()])  # the distribution's own rating wins when present
    if candidates:
        return min(candidates, key=lambda s: _RANK[s])
    for affected in vuln.get("affected") or []:
        if (affected.get("package") or {}).get("name") not in (package, None):
            continue
        for block in (affected.get("ecosystem_specific") or {}, affected.get("database_specific") or {}):
            for key in ("severity", "urgency"):
                value = str(block.get(key, "")).lower()
                if value in _TEXT:
                    candidates.append(_TEXT[value])
    value = str((vuln.get("database_specific") or {}).get("severity", "")).lower()
    if value in _TEXT:
        candidates.append(_TEXT[value])
    candidates = [c for c in candidates if c != "unknown"]
    if candidates:
        return min(candidates, key=lambda s: _RANK[s])
    return _band(max(scores)) if scores else "unknown"


def _fixed(vuln: dict, package: str, eco: str) -> str:
    for affected in vuln.get("affected") or []:
        pkg = affected.get("package") or {}
        if pkg.get("name") != package or pkg.get("ecosystem") != eco:
            continue
        for rng in affected.get("ranges") or []:
            for event in rng.get("events") or []:
                if "fixed" in event:
                    return str(event["fixed"])[:255]
    return ""


def query(eco: str, pkgs: list[tuple[str, str]], transport: httpx.BaseTransport | None = None) -> dict[tuple[str, str], list[str]]:
    hits: dict[tuple[str, str], list[str]] = {}
    with httpx.Client(timeout=30, transport=transport) as client:
        for start in range(0, len(pkgs), 1000):
            chunk = pkgs[start:start + 1000]
            body = {"queries": [{"package": {"name": n, "ecosystem": eco}, "version": v} for n, v in chunk]}
            r = client.post(f"{OSV}/querybatch", json=body)
            r.raise_for_status()
            for (name, version), result in zip(chunk, r.json().get("results") or []):
                ids = [v["id"] for v in (result or {}).get("vulns") or [] if v.get("id")]
                if ids:
                    hits[(name, version)] = ids
    return hits


def details(ids: set[str], transport: httpx.BaseTransport | None = None, limit: int = 2000) -> dict[str, dict]:
    out: dict[str, dict] = {}
    with httpx.Client(timeout=30, transport=transport) as client:
        for vuln_id in sorted(ids)[:limit]:
            r = client.get(f"{OSV}/vulns/{vuln_id}")
            if r.status_code == 200:
                out[vuln_id] = r.json()
    return out


def scan(db: Session, org_id: int, transport: httpx.BaseTransport | None = None) -> dict:
    """Refresh findings for every endpoint with a usable inventory. Findings that disappear are resolved."""
    now = dt.datetime.now(dt.timezone.utc)
    devices = {d.id: d for d in db.query(Device).filter(Device.org_id == org_id).all()}
    covered, uncovered, per_device = [], [], {}
    for snap in db.query(DeviceInventory).filter(DeviceInventory.org_id == org_id).all():
        payload = json.loads(snap.payload or "{}")
        eco = ecosystem(payload.get("os_release") or {})
        pkgs = packages(payload)
        if not eco or not pkgs:
            uncovered.append(snap.device_id)
            continue
        covered.append(snap.device_id)
        per_device[snap.device_id] = (eco, pkgs)
    by_eco: dict[str, set[tuple[str, str]]] = {}
    for eco, pkgs in per_device.values():
        by_eco.setdefault(eco, set()).update(pkgs)
    hits = {eco: query(eco, sorted(pkgs), transport) for eco, pkgs in by_eco.items()}
    info = details({i for eco_hits in hits.values() for ids in eco_hits.values() for i in ids}, transport)
    opened = 0
    for device_id, (eco, pkgs) in per_device.items():
        current = set()
        for name, version in pkgs:
            for vuln_id in hits[eco].get((name, version), []):
                current.add((vuln_id, name))
                vuln = info.get(vuln_id, {})
                row = db.query(VulnerabilityFinding).filter(VulnerabilityFinding.device_id == device_id,
                    VulnerabilityFinding.vuln_id == vuln_id, VulnerabilityFinding.package == name).first()
                if not row:
                    row = VulnerabilityFinding(org_id=org_id, device_id=device_id, package=name, vuln_id=vuln_id, first_seen=now)
                    db.add(row)
                    opened += 1
                row.version, row.ecosystem, row.status, row.last_seen = version, eco, "open", now
                row.summary = (vuln.get("summary") or vuln.get("details") or "")[:2000]
                row.aliases = json.dumps([a for a in vuln.get("aliases") or [] if isinstance(a, str)][:20])
                row.severity = _severity(vuln, name)
                row.fixed_version = _fixed(vuln, name, eco)
        for row in db.query(VulnerabilityFinding).filter(VulnerabilityFinding.device_id == device_id, VulnerabilityFinding.status == "open").all():
            if (row.vuln_id, row.package) not in current:
                row.status, row.last_seen = "resolved", now
    db.commit()
    return {"devices_covered": len(covered), "devices_not_covered": [devices[i].hostname for i in uncovered if i in devices],
        "new_findings": opened, "scanned_at": now.isoformat()}
