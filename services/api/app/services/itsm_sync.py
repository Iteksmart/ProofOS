"""Two-way bridge between iTechSmart ITSM (system of record for linked tickets) and ProofOS tickets.

- sync():  ITSM -> ProofOS. Imports new ITSM tickets as ProofOS tickets and mirrors status/resolution
           changes; every import/update emits a ProofOS proof receipt (What/When/Where/Why/Who).
- push():  ProofOS -> ITSM. Creates the ITSM ticket (needs ITECHSMART_ITSM_TOKEN = suite SERVICE_TOKEN),
           records the link so a later sync does not duplicate it. Honest 503 when the token is unset.
"""
from __future__ import annotations

import datetime as dt

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.proof import emit
from app.core.security import actor_of
from app.models.models import ItsmLink, Ticket

settings = get_settings()

STATUS_IN = {"open": "open", "investigating": "in_progress", "resolved": "resolved", "closed": "closed"}
PRIORITY_IN = {"P1": "urgent", "P2": "high", "P3": "normal", "P4": "low"}
PRIORITY_OUT = {"urgent": ("P1", "critical"), "high": ("P2", "warning"), "normal": ("P3", "info"), "low": ("P4", "info")}


class ItsmError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def _base() -> str:
    return settings.itechsmart_itsm_url.rstrip("/")


def _parse(ts: str | None):
    if not ts:
        return None
    try:
        return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _fetch() -> list[dict]:
    try:
        r = httpx.get(f"{_base()}/api/v1/tickets", timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:  # noqa: BLE001
        raise ItsmError(502, f"ITSM unreachable: {e}")
    if not isinstance(data, list):
        raise ItsmError(502, "ITSM returned an unexpected payload")
    return data


def sync(db: Session, user) -> dict:
    org = user.org_id
    created = updated = unchanged = 0
    for t in _fetch():
        iid = t.get("id")
        if not iid:
            continue
        link = db.query(ItsmLink).filter(ItsmLink.org_id == org, ItsmLink.itsm_id == iid).first()
        status = STATUS_IN.get(t.get("status"), "open")
        marker = f"[ITSM {iid}]"
        if link is None:
            body = (t.get("description") or "") + f"\n\n{marker} service={t.get('service')} source={t.get('source')}"
            if t.get("resolution"):
                body += f"\nresolution: {t['resolution']}"
            pri = PRIORITY_IN.get(t.get("priority"), "normal")
            tk = Ticket(org_id=org, title=(t.get("title") or iid)[:500], body=body, status=status, priority=pri,
                        severity=t.get("priority") or "P3", assignee=t.get("assignee") or "",
                        due_at=_parse(t.get("due_at")))
            db.add(tk)
            db.flush()
            db.add(ItsmLink(org_id=org, itsm_id=iid, ticket_id=tk.id, itsm_status=t.get("status") or "open",
                            itsm_updated_at=t.get("updated_at") or "", receipt_id=t.get("receipt_id") or ""))
            emit(db, "itsm.ticket.imported",
                 {"itsm_id": iid, "proofos_ticket": tk.id, "status": t.get("status"), "receipt_hash": t.get("receipt_hash")},
                 actor_of(user), {"org_id": org, "source": "itechsmart-itsm"}, {"reason": "ITSM -> ProofOS ticket sync"})
            created += 1
            continue
        if link.itsm_updated_at == (t.get("updated_at") or ""):
            unchanged += 1
            continue
        tk = db.query(Ticket).filter(Ticket.id == link.ticket_id, Ticket.org_id == org).first()
        if tk is not None:
            tk.status = status
            if t.get("assignee"):
                tk.assignee = t["assignee"]
            if t.get("resolution") and t["resolution"] not in (tk.body or ""):
                tk.body = (tk.body or "") + f"\nresolution: {t['resolution']}"
        link.itsm_status = t.get("status") or link.itsm_status
        link.itsm_updated_at = t.get("updated_at") or ""
        link.receipt_id = t.get("receipt_id") or link.receipt_id
        link.last_synced_at = dt.datetime.now(dt.timezone.utc)
        emit(db, "itsm.ticket.updated",
             {"itsm_id": iid, "proofos_ticket": link.ticket_id, "status": t.get("status"), "receipt_hash": t.get("receipt_hash")},
             actor_of(user), {"org_id": org, "source": "itechsmart-itsm"}, {"reason": "ITSM -> ProofOS ticket sync"})
        updated += 1
    db.commit()
    return {"created": created, "updated": updated, "unchanged": unchanged}


def push(db: Session, user, ticket_id: int) -> dict:
    if not settings.itechsmart_itsm_token:
        raise ItsmError(503, "ITECHSMART_ITSM_TOKEN not configured (suite SERVICE_TOKEN)")
    tk = db.query(Ticket).filter(Ticket.id == ticket_id, Ticket.org_id == user.org_id).first()
    if tk is None:
        raise ItsmError(404, "ticket not found")
    if db.query(ItsmLink).filter(ItsmLink.org_id == user.org_id, ItsmLink.ticket_id == tk.id).first():
        raise ItsmError(409, "ticket already linked to ITSM")
    pri, sev = PRIORITY_OUT.get(tk.priority, ("P3", "info"))
    try:
        r = httpx.post(f"{_base()}/api/v1/tickets", timeout=15,
                       headers={"Authorization": f"Bearer {settings.itechsmart_itsm_token}"},
                       json={"title": tk.title, "service": "proofos", "severity": sev, "priority": pri,
                             "description": tk.body or "", "source": "proofos", "assignee": tk.assignee or None,
                             "external_ref": f"proofos:{user.org_id}:{tk.id}"})
    except Exception as e:  # noqa: BLE001
        raise ItsmError(502, f"ITSM unreachable: {e}")
    if r.status_code >= 400:
        raise ItsmError(r.status_code if r.status_code in (401, 403, 409) else 502, f"ITSM rejected the ticket ({r.status_code})")
    it = r.json()
    db.add(ItsmLink(org_id=user.org_id, itsm_id=it["id"], ticket_id=tk.id, itsm_status=it.get("status", "open"),
                    itsm_updated_at=it.get("updated_at") or ""))
    emit(db, "itsm.ticket.pushed", {"itsm_id": it["id"], "proofos_ticket": tk.id}, actor_of(user),
         {"org_id": user.org_id, "target": "itechsmart-itsm"}, {"reason": "ProofOS -> ITSM ticket push"})
    db.commit()
    return {"itsm_id": it["id"], "proofos_ticket": tk.id}
