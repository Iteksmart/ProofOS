from __future__ import annotations

import datetime as dt
import json

from sqlalchemy.orm import Session

from app.models.models import Device, Ticket
from app.services.llm import get_llm_client


def device_risk(dev: Device) -> dict:
    """Offline heuristic risk score 0..100 (higher = riskier)."""
    score = 0
    reasons: list[str] = []
    if (dev.status or "online") != "online":
        score += 40
        reasons.append(f"status={dev.status}")
    if dev.cpu >= 90:
        score += 20
        reasons.append(f"cpu={dev.cpu}%")
    if dev.disk >= 90:
        score += 20
        reasons.append(f"disk={dev.disk}%")
    if dev.mem >= 90:
        score += 15
        reasons.append(f"mem={dev.mem}%")
    last = dev.last_seen
    if last is not None:
        now = dt.datetime.now(dt.timezone.utc)
        try:
            age = (now - last).total_seconds()
        except TypeError:
            # naive (sqlite) — assume UTC
            age = (now.replace(tzinfo=None) - last).total_seconds()
        if age > 300:
            score += 10
            reasons.append(f"stale {int(age)}s")
    score = max(0, min(100, score))
    level = "critical" if score >= 70 else "warning" if score >= 35 else "ok"
    return {"device_id": dev.id, "hostname": dev.hostname, "score": score, "level": level, "reasons": reasons}


def triage_ticket(ticket: Ticket) -> dict:
    """Suggest assignee/priority/next action. Deterministic, auditable."""
    text = f"{ticket.title} {ticket.body}".lower()
    if "offline" in text or "down" in text:
        return {"suggested_priority": "high", "suggested_action": "check device + monitor", "confidence": 0.7}
    if "password" in text or "login" in text or "access" in text:
        return {"suggested_priority": "high", "suggested_action": "verify auth + audit proof", "confidence": 0.6}
    if "disk" in text or "cpu" in text or "performance" in text:
        return {"suggested_priority": "normal", "suggested_action": "run inventory script", "confidence": 0.5}
    if ticket.priority == "urgent":
        return {"suggested_priority": "urgent", "suggested_action": "escalate + page on-call", "confidence": 0.8}
    return {"suggested_priority": ticket.priority, "suggested_action": "standard triage", "confidence": 0.4}


def _snapshot(db: Session, org_id: int) -> dict:
    """Live state handed to the LLM (and echoed back for auditability)."""
    devices = db.query(Device).filter(Device.org_id == org_id).all()
    tickets = db.query(Ticket).filter(Ticket.org_id == org_id).all()
    return {
        "devices": [
            {
                "id": d.id,
                "hostname": d.hostname,
                "os": d.os,
                "ip": d.ip,
                "status": d.status,
                "cpu": d.cpu,
                "disk": d.disk,
                "mem": d.mem,
                "last_seen": d.last_seen.isoformat() if d.last_seen else None,
            }
            for d in devices
        ],
        "tickets": [
            {"id": t.id, "title": t.title, "body": t.body, "status": t.status, "priority": t.priority}
            for t in tickets
        ],
    }


def _heuristic_answer(db: Session, org_id: int, query: str) -> dict:
    q = (query or "").lower()
    devices = db.query(Device).filter(Device.org_id == org_id).all()
    tickets = db.query(Ticket).filter(Ticket.org_id == org_id).all()
    offline = [d for d in devices if (d.status or "online") != "online"]
    open_t = [t for t in tickets if t.status == "open"]
    if "offline" in q:
        return {
            "answer": f"{len(offline)} offline device(s).",
            "devices": [{"id": d.id, "hostname": d.hostname, "status": d.status} for d in offline],
            "risk": [device_risk(d) for d in devices],
        }
    if "ticket" in q or "open" in q:
        return {
            "answer": f"{len(open_t)} open ticket(s).",
            "tickets": [{"id": t.id, "title": t.title, "status": t.status, "priority": t.priority} for t in open_t],
            "triage": [triage_ticket(t) for t in open_t[:10]],
        }
    if "risk" in q or "health" in q:
        return {"answer": "Device risk ranking.", "risk": [device_risk(d) for d in devices]}
    return {
        "answer": "Summary across devices and tickets.",
        "devices": len(devices),
        "offline": len(offline),
        "open_tickets": len(open_t),
        "risk_top": sorted([device_risk(d) for d in devices], key=lambda x: x["score"], reverse=True)[:5],
    }


def answer_query(db: Session, org_id: int, query: str) -> dict:
    """Copilot answer. Uses the configured LLM backend, else the heuristic."""
    heuristic = _heuristic_answer(db, org_id, query)
    client = get_llm_client()
    if client is None or not client.is_configured():
        return {**heuristic, "engine": "heuristic"}
    context = _snapshot(db, org_id)
    try:
        text = client.chat(
            [
                {
                    "role": "user",
                    "content": (
                        f"Query: {query}\n\n"
                        f"Live state (JSON):\n{json.dumps(context, default=str)}"
                    ),
                }
            ]
        )
        return {"answer": text, **client.identity(), "context": context}
    except Exception as e:  # noqa: BLE001 - fall back rather than fail the copilot
        return {**heuristic, "engine": "heuristic", "fallback_reason": f"{client.provider} unavailable: {e}"}


def _heuristic_summarise(db: Session, org_id: int, scope: str = "open") -> dict:
    devices = db.query(Device).filter(Device.org_id == org_id).all()
    tickets = db.query(Ticket).filter(Ticket.org_id == org_id)
    if scope == "open":
        tickets = tickets.filter(Ticket.status == "open")
    tickets = tickets.all()
    offline = [d for d in devices if (d.status or "online") != "online"]
    return {
        "scope": scope,
        "devices_total": len(devices),
        "devices_offline": len(offline),
        "tickets": len(tickets),
        "offline_hostnames": [d.hostname for d in offline],
        "ticket_titles": [t.title for t in tickets[:20]],
        "risk_top": sorted([device_risk(d) for d in devices], key=lambda x: x["score"], reverse=True)[:5],
    }


def summarise(db: Session, org_id: int, scope: str = "open") -> dict:
    """Copilot summary. Uses the configured LLM backend, else the heuristic."""
    heuristic = _heuristic_summarise(db, org_id, scope)
    client = get_llm_client()
    if client is None or not client.is_configured():
        return {**heuristic, "engine": "heuristic"}
    context = _snapshot(db, org_id)
    try:
        text = client.chat(
            [
                {
                    "role": "user",
                    "content": (
                        f"Summarise the current state (scope={scope}). "
                        f"Live state (JSON):\n{json.dumps(context, default=str)}"
                    ),
                }
            ]
        )
        return {"summary": text, "scope": scope, **client.identity(), "context": context}
    except Exception as e:  # noqa: BLE001
        return {**heuristic, "engine": "heuristic", "fallback_reason": f"{client.provider} unavailable: {e}"}


def propose_action(db: Session, org_id: int, query: str) -> dict:
    """Propose a remediation command for a device. Deterministic; never auto-executes.

    Returns {action, device_id, hostname, command, reason}. device_id is None when
    no action matches — the caller must surface the proposal for human approval.
    """
    q = (query or "").lower()
    devices = db.query(Device).filter(Device.org_id == org_id).all()
    if not devices:
        return {"reason": "No devices registered to act on.", "device_id": None, "command": ""}

    offline = [d for d in devices if (d.status or "online") != "online"]
    risky = sorted(devices, key=lambda d: max(d.cpu or 0, d.disk or 0, d.mem or 0), reverse=True)[0]
    win = lambda d: (d.os or "").lower().startswith("windows")

    if any(k in q for k in ("offline", "down", "unreachable", "connectivity")):
        target = offline[0] if offline else devices[0]
        cmd = "ping -n 4 8.8.8.8" if win(target) else "ping -c 4 8.8.8.8"
        return {"action": "check connectivity", "device_id": target.id, "hostname": target.hostname, "command": cmd,
                "reason": f"Check connectivity on {target.hostname}"}
    if any(k in q for k in ("disk", "cleanup", "storage", "full")):
        cmd = "wmic logicaldisk get size,freespace,caption" if win(risky) else "df -h"
        return {"action": "disk cleanup", "device_id": risky.id, "hostname": risky.hostname, "command": cmd,
                "reason": f"Inspect disk usage on {risky.hostname} (disk {risky.disk}%)"}
    if any(k in q for k in ("cpu", "memory", "mem", "performance", "slow")):
        cmd = "tasklist /v" if win(risky) else "top -bn1 | head -20"
        return {"action": "performance check", "device_id": risky.id, "hostname": risky.hostname, "command": cmd,
                "reason": f"Inspect processes on {risky.hostname} (cpu {risky.cpu}%, mem {risky.mem}%)"}
    if any(k in q for k in ("upgrade", "update", "patch")):
        target = devices[0]
        cmd = 'powershell -c "Get-WindowsUpdate -Install -AcceptAll"' if win(target) else "sudo apt-get update -y && sudo apt-get upgrade -y"
        return {"action": "apply updates", "device_id": target.id, "hostname": target.hostname, "command": cmd,
                "reason": f"Apply updates on {target.hostname}"}
    return {"reason": "No specific remediation matched — refine the request (e.g. 'disk cleanup', 'offline devices').",
            "device_id": None, "command": ""}
