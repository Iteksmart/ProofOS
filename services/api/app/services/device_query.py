"""Turn a plain-English endpoint description into explicit, inspectable filters.

Deterministic on purpose: every recognised phrase becomes a visible filter, and
anything not understood is reported back instead of being guessed at.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models.models import Alert, Device, Patch

_NUM = r"(\d{1,3}(?:\.\d+)?)"
_METRICS = {"cpu": "cpu", "processor": "cpu", "disk": "disk", "storage": "disk", "memory": "mem", "mem": "mem", "ram": "mem"}
_METRIC_LABEL = {"cpu": "CPU", "disk": "Disk", "mem": "Memory"}
_TYPES = [
    (r"\b(servers?)\b", "server"),
    (r"\b(workstations?|laptops?|desktops?|pcs?)\b", "workstation"),
    (r"\b(switch(?:es)?)\b", "switch"),
    (r"\b(access[ -]points?|aps)\b", "access_point"),
    (r"\b(gateways?|routers?|firewalls?)\b", "gateway"),
    (r"\b(nodes?)\b", "node"),
]
_OS = [(r"\b(windows|win)\b", "windows"), (r"\b(linux)\b", "linux"), (r"\b(ubuntu)\b", "ubuntu"),
       (r"\b(macos|mac os|macs?|osx)\b", "macos"), (r"\b(cisco)\b", "cisco")]
_STOP = {"show", "me", "all", "the", "list", "find", "devices", "device", "endpoints", "endpoint", "machines", "machine",
         "with", "that", "are", "is", "which", "have", "has", "and", "a", "an", "of", "in", "on", "running", "my", "any",
         "for", "to", "or", "than", "where", "whose", "please", "get", "only"}


@dataclass
class DeviceFilter:
    statuses: set[str] = field(default_factory=set)
    os: list[str] = field(default_factory=list)
    types: set[str] = field(default_factory=set)
    alerts: str | None = None          # "any" | "critical"
    patches: str | None = None         # "any" | "critical"
    metrics: list[tuple[str, str, float]] = field(default_factory=list)
    no_agent: bool = False
    unseen_hours: float | None = None
    hostname: str | None = None
    understood: list[str] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)


def parse(text: str) -> DeviceFilter:
    f = DeviceFilter()
    q = " " + text.lower().strip() + " "

    def take(pattern: str) -> re.Match | None:
        nonlocal q
        match = re.search(pattern, q)
        if match:
            q = q[: match.start()] + " " + q[match.end():]
        return match

    named = take(r"\b(?:named|called|hostname|host)\s+[\"']?([a-z0-9][a-z0-9._-]*)[\"']?")
    quoted = None if named else take(r"[\"']([^\"']{2,60})[\"']")
    if named or quoted:
        f.hostname = (named or quoted).group(1)
        f.understood.append(f"Hostname contains “{f.hostname}”")

    # "high cpu", "cpu over 80", "disk usage above 90%", "memory >= 75"
    while (m := take(rf"\b(cpu|processor|disk|storage|memory|mem|ram)\s*(?:usage|use|utili[sz]ation|load)?\s*(>=|<=|>|<|over|above|more than|greater than|under|below|less than)\s*{_NUM}\s*%?")):
        metric, op, value = _METRICS[m.group(1)], m.group(2), float(m.group(3))
        op = ">" if op in {">", "over", "above", "more than", "greater than"} else "<" if op in {"<", "under", "below", "less than"} else op
        f.metrics.append((metric, op, value))
        f.understood.append(f"{_METRIC_LABEL[metric]} {op} {value:g}%")
    while (m := take(r"\b(high|heavy|elevated)\s+(cpu|processor|disk|storage|memory|mem|ram)(?:\s+(?:usage|use|load|utili[sz]ation))?\b")):
        metric = _METRICS[m.group(2)]
        threshold = 80.0 if metric == "cpu" else 85.0
        f.metrics.append((metric, ">=", threshold))
        f.understood.append(f"{_METRIC_LABEL[metric]} ≥ {threshold:g}%")
    if take(r"\b(low|full|running out of)\s+(disk|storage|space)(?:\s+space)?\b"):
        f.metrics.append(("disk", ">=", 90.0))
        f.understood.append("Disk ≥ 90% used")

    if m := take(r"\b(?:not seen|unseen|not checked in|no heartbeat|silent)\s+(?:for|in|since)?\s*(\d{1,4})\s*(minutes?|mins?|hours?|hrs?|days?)\b"):
        amount, unit = float(m.group(1)), m.group(2)
        f.unseen_hours = amount / 60 if unit.startswith("m") else amount * 24 if unit.startswith("d") else amount
        f.understood.append(f"Not seen for {m.group(1)} {unit}")

    if take(r"\b(?:without|no|missing)\s+(?:an?\s+)?agents?\b|\bunmanaged\b"):
        f.no_agent = True
        f.understood.append("No agent installed")

    if take(r"\b(?:critical|urgent|severe)\s+(?:unacknowledged\s+|open\s+)?alerts?\b"):
        f.alerts = "critical"
        f.understood.append("Open critical alerts")
    elif take(r"\b(?:open\s+|unacknowledged\s+|active\s+)?alerts?\b|\balerting\b"):
        f.alerts = "any"
        f.understood.append("Any open alert")

    if take(r"\bcritical\s+(?:missing\s+|pending\s+)?(?:patch(?:es)?|updates?)\b"):
        f.patches = "critical"
        f.understood.append("Critical patches pending")
    elif take(r"\b(?:missing|pending|outstanding|failed)\s+(?:patch(?:es)?|updates?)\b|\b(?:needs?|needing|requires?)\s+(?:patching|updates?)\b|\bunpatched\b|\b(?:patch(?:es)?|updates?)\s+(?:pending|missing|available)\b"):
        f.patches = "any"
        f.understood.append("Patches pending or failed")

    if take(r"\b(?:offline|down|unreachable|disconnected)\b"):
        f.statuses.add("offline")
    if take(r"\bstale\b"):
        f.statuses.add("stale")
    if take(r"\b(?:not online|unhealthy|problem(?:atic)?|need(?:s|ing)? attention)\b"):
        f.statuses.update({"offline", "stale"})
    if take(r"\b(?:online|up|healthy|connected)\b"):
        f.statuses.add("online")
    if f.statuses:
        f.understood.append("Status: " + " or ".join(sorted(f.statuses)))

    for pattern, value in _OS:
        if take(pattern):
            f.os.append(value)
    if f.os:
        f.understood.append("OS: " + " or ".join(f.os))
    for pattern, value in _TYPES:
        if take(pattern):
            f.types.add(value)
    if f.types:
        f.understood.append("Type: " + " or ".join(sorted(t.replace("_", " ") for t in f.types)))

    for word in re.findall(r"[a-z0-9][a-z0-9._%-]*", q):
        if word not in _STOP and not word.isdigit():
            f.ignored.append(word)
    return f


def _cmp(value: float, op: str, target: float) -> bool:
    return {">": value > target, "<": value < target, ">=": value >= target, "<=": value <= target}[op]


def apply(db: Session, org_id: int, f: DeviceFilter) -> list[Device]:
    devices = db.query(Device).filter(Device.org_id == org_id).order_by(Device.hostname).all()
    alerts: dict[int, set[str]] = {}
    if f.alerts:
        for device_id, severity in db.query(Alert.device_id, Alert.severity).filter(
                Alert.org_id == org_id, Alert.acked.is_(False), Alert.device_id.isnot(None)).all():
            alerts.setdefault(device_id, set()).add(severity)
    patches: dict[int, set[str]] = {}
    if f.patches:
        for device_id, severity in db.query(Patch.device_id, Patch.severity).filter(
                Patch.org_id == org_id, Patch.status.in_(["pending", "failed"])).all():
            patches.setdefault(device_id, set()).add(severity)
    now = dt.datetime.now(dt.timezone.utc)

    def keep(d: Device) -> bool:
        if f.statuses and (d.status or "unknown") not in f.statuses:
            return False
        if f.os and not any(o in (d.os or "").lower() or (o == "macos" and "mac" in (d.os or "").lower()) for o in f.os):
            return False
        if f.types and (d.device_type or "workstation") not in f.types:
            return False
        if f.hostname and f.hostname not in (d.hostname or "").lower():
            return False
        if f.no_agent and d.agent_version:
            return False
        if f.alerts == "any" and d.id not in alerts:
            return False
        if f.alerts == "critical" and "critical" not in alerts.get(d.id, set()):
            return False
        if f.patches == "any" and d.id not in patches:
            return False
        if f.patches == "critical" and "critical" not in patches.get(d.id, set()):
            return False
        for metric, op, target in f.metrics:
            if not _cmp(float(getattr(d, metric) or 0), op, target):
                return False
        if f.unseen_hours is not None:
            seen = d.last_seen
            if seen is not None and seen.tzinfo is None:
                seen = seen.replace(tzinfo=dt.timezone.utc)
            if seen is not None and (now - seen).total_seconds() < f.unseen_hours * 3600:
                return False
        return True

    return [d for d in devices if keep(d)]
