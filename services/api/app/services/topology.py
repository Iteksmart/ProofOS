"""Service dependency graph: nodes, edges, evidence-based health and impact."""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from app.models.models import Alert, Device, ServiceDependency, ServiceNode, TelemetryEvent

HEALTH_WINDOW = dt.timedelta(minutes=15)
_RANK = {"unknown": 0, "healthy": 1, "degraded": 2, "down": 3}


def get_or_create_node(db: Session, org_id: int, name: str) -> tuple[ServiceNode, bool]:
    name = name.strip()[:255]
    node = db.query(ServiceNode).filter(ServiceNode.org_id == org_id, ServiceNode.name == name).first()
    if node:
        return node, False
    node = ServiceNode(org_id=org_id, name=name, description="")
    db.add(node)
    db.flush()
    return node, True


def observe_edge(db: Session, org_id: int, source: str, target: str, origin: str = "trace") -> bool:
    """Record that `source` calls `target`. Returns True when the edge is new."""
    if not source or not target or source == target:
        return False
    src, _ = get_or_create_node(db, org_id, source)
    dst, _ = get_or_create_node(db, org_id, target)
    edge = db.query(ServiceDependency).filter(ServiceDependency.org_id == org_id,
        ServiceDependency.source_id == src.id, ServiceDependency.target_id == dst.id).first()
    now = dt.datetime.now(dt.timezone.utc)
    if edge:
        edge.observed_at = now
        return False
    db.add(ServiceDependency(org_id=org_id, source_id=src.id, target_id=dst.id, origin=origin, observed_at=now))
    db.flush()
    return True


def _worst(states: list[str]) -> str:
    return max(states, key=lambda s: _RANK[s]) if states else "unknown"


def node_health(db: Session, org_id: int, nodes: list[ServiceNode]) -> dict[int, dict]:
    """Health is only ever derived from evidence; no evidence means 'unknown'."""
    since = dt.datetime.now(dt.timezone.utc) - HEALTH_WINDOW
    events = db.query(TelemetryEvent.service, TelemetryEvent.severity).filter(
        TelemetryEvent.org_id == org_id, TelemetryEvent.received_at >= since).all()
    totals: dict[str, int] = {}
    errors: dict[str, int] = {}
    for service, severity in events:
        totals[service] = totals.get(service, 0) + 1
        if (severity or "").upper() in {"ERROR", "FATAL", "CRITICAL"}:
            errors[service] = errors.get(service, 0) + 1
    device_ids = [n.device_id for n in nodes if n.device_id]
    devices = {d.id: d for d in db.query(Device).filter(Device.org_id == org_id, Device.id.in_(device_ids)).all()} if device_ids else {}
    critical = set()
    if device_ids:
        critical = {a.device_id for a in db.query(Alert).filter(Alert.org_id == org_id, Alert.device_id.in_(device_ids),
            Alert.acked.is_(False), Alert.severity == "critical").all()}
    out: dict[int, dict] = {}
    for node in nodes:
        states: list[str] = []
        evidence: list[str] = []
        total = totals.get(node.name, 0)
        if total:
            rate = errors.get(node.name, 0) / total
            states.append("down" if rate >= 0.5 else "degraded" if rate >= 0.1 else "healthy")
            evidence.append(f"{errors.get(node.name, 0)} of {total} telemetry events in the last 15 min were errors")
        device = devices.get(node.device_id) if node.device_id else None
        if device:
            status = device.status or "unknown"
            states.append({"online": "healthy", "offline": "down", "stale": "degraded"}.get(status, "unknown"))
            evidence.append(f"endpoint {device.hostname} is {status}")
            if device.id in critical:
                states.append("degraded")
                evidence.append("endpoint has an unacknowledged critical alert")
        out[node.id] = {"state": _worst(states), "evidence": evidence or ["no telemetry or linked endpoint in the last 15 min"]}
    return out


def graph(db: Session, org_id: int) -> dict:
    nodes = db.query(ServiceNode).filter(ServiceNode.org_id == org_id).order_by(ServiceNode.name).all()
    edges = db.query(ServiceDependency).filter(ServiceDependency.org_id == org_id).all()
    health = node_health(db, org_id, nodes)
    return {
        "nodes": [{"id": n.id, "name": n.name, "device_id": n.device_id, "description": n.description,
            "health": health[n.id]["state"], "evidence": health[n.id]["evidence"]} for n in nodes],
        "edges": [{"id": e.id, "source_id": e.source_id, "target_id": e.target_id, "origin": e.origin,
            "observed_at": e.observed_at} for e in edges],
    }


def _walk(start: int, adjacency: dict[int, list[int]]) -> list[int]:
    seen: list[int] = []
    queue = list(adjacency.get(start, []))
    while queue:
        current = queue.pop(0)
        if current == start or current in seen:
            continue
        seen.append(current)
        queue.extend(adjacency.get(current, []))
    return seen


def probable_causes(db: Session, org_id: int, node_id: int) -> dict:
    """Rank the service and everything it depends on by how likely each is to be the origin of a failure.

    An unhealthy dependency whose own dependencies are healthy is the strongest candidate: the
    failure starts there and propagates up. Ranking uses only recorded evidence.
    """
    edges = db.query(ServiceDependency).filter(ServiceDependency.org_id == org_id).all()
    callees: dict[int, list[int]] = {}
    for edge in edges:
        callees.setdefault(edge.source_id, []).append(edge.target_id)
    depth = {node_id: 0}
    queue = [node_id]
    while queue:
        current = queue.pop(0)
        for nxt in callees.get(current, []):
            if nxt not in depth:
                depth[nxt] = depth[current] + 1
                queue.append(nxt)
    nodes = db.query(ServiceNode).filter(ServiceNode.org_id == org_id, ServiceNode.id.in_(list(depth))).all()
    health = node_health(db, org_id, nodes)
    unhealthy = {n.id for n in nodes if health[n.id]["state"] in {"degraded", "down"}}
    ranked = []
    for node in nodes:
        state = health[node.id]["state"]
        if node.id not in unhealthy:
            continue
        below = set(_walk(node.id, callees))
        origin = not (below & unhealthy)  # nothing it depends on is failing
        score = _RANK[state] * 10 + (25 if origin else 0) + depth[node.id]
        ranked.append({"id": node.id, "name": node.name, "health": state, "depth": depth[node.id], "score": score,
            "origin": origin, "evidence": health[node.id]["evidence"],
            "why": ("no failing dependency below it, so the failure most likely starts here" if origin
                else "it is failing, but something it depends on is failing too")})
    ranked.sort(key=lambda r: -r["score"])
    return {"service_id": node_id, "candidates": ranked,
        "scope": "Ranked from telemetry, endpoint status and recorded dependency edges; services without evidence are not ranked."}


def impact(db: Session, org_id: int, node_id: int) -> dict:
    """Who is affected if this service fails (dependents) and what it needs (dependencies)."""
    edges = db.query(ServiceDependency).filter(ServiceDependency.org_id == org_id).all()
    callers: dict[int, list[int]] = {}
    callees: dict[int, list[int]] = {}
    for edge in edges:
        callers.setdefault(edge.target_id, []).append(edge.source_id)
        callees.setdefault(edge.source_id, []).append(edge.target_id)
    names = {n.id: n.name for n in db.query(ServiceNode).filter(ServiceNode.org_id == org_id).all()}
    dependents = _walk(node_id, callers)
    dependencies = _walk(node_id, callees)
    return {
        "service_id": node_id,
        "dependents": [{"id": i, "name": names.get(i, "?")} for i in dependents],
        "dependencies": [{"id": i, "name": names.get(i, "?")} for i in dependencies],
        "scope": "Derived from recorded dependency edges only; unobserved dependencies are not included.",
    }
