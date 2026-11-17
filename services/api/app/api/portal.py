"""Customer portal: revocable, expiring links that let a client contact follow their tickets and invoices."""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.proof import emit
from app.core.security import SlidingWindowLimiter, actor_of, get_current_user
from app.models.models import Customer, Invoice, PortalLink, Ticket, TicketComment

router = APIRouter()
public_limiter = SlidingWindowLimiter(60, 60)
STAFF = {"admin", "manager", "technician"}


class LinkIn(BaseModel):
    customer_id: int
    contact_email: str = Field(min_length=3, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    days: int = Field(default=30, ge=1, le=365)


class PortalTicketIn(BaseModel):
    title: str = Field(min_length=3, max_length=500)
    body: str = Field(default="", max_length=20000)
    priority: str = Field(default="normal", pattern="^(low|normal|high|urgent)$")


class PortalCommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=20000)


def _aware(value: dt.datetime) -> dt.datetime:
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


def _link_out(row: PortalLink) -> dict:
    expired = _aware(row.expires_at) <= dt.datetime.now(dt.timezone.utc)
    return {"id": row.id, "customer_id": row.customer_id, "contact_email": row.contact_email, "expires_at": _aware(row.expires_at),
        "revoked": row.revoked, "active": not row.revoked and not expired, "created_at": row.created_at}


@router.post("/links", status_code=201)
def create_link(payload: LinkIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user.role not in STAFF:
        raise HTTPException(status_code=403, detail="staff only")
    customer = db.query(Customer).filter(Customer.id == payload.customer_id, Customer.org_id == user.org_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="customer not found")
    token = secrets.token_urlsafe(32)
    row = PortalLink(org_id=user.org_id, customer_id=customer.id, contact_email=payload.contact_email.lower(),
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=payload.days))
    db.add(row)
    db.commit()
    emit(db, "portal.link.created", {"id": row.id, "customer_id": customer.id, "contact_email": row.contact_email, "days": payload.days},
        actor_of(user), {"org_id": user.org_id}, {"reason": "grant customer portal access"})
    # The token sits in the URL fragment, which browsers never send to servers or put in referrers.
    return {**_link_out(row), "token": token, "path": f"/portal#{token}"}


@router.get("/links")
def list_links(customer_id: int | None = None, db: Session = Depends(get_db), user=Depends(get_current_user)):
    q = db.query(PortalLink).filter(PortalLink.org_id == user.org_id)
    if customer_id:
        q = q.filter(PortalLink.customer_id == customer_id)
    return [_link_out(r) for r in q.order_by(PortalLink.id.desc()).limit(200).all()]


@router.post("/links/{link_id}/revoke")
def revoke_link(link_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user.role not in STAFF:
        raise HTTPException(status_code=403, detail="staff only")
    row = db.query(PortalLink).filter(PortalLink.id == link_id, PortalLink.org_id == user.org_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="portal link not found")
    row.revoked = True
    db.commit()
    emit(db, "portal.link.revoked", {"id": row.id}, actor_of(user), {"org_id": user.org_id}, {"reason": "revoke customer portal access"})
    return _link_out(row)


def portal_session(request: Request, x_portal_token: str = Header(default="", max_length=128), db: Session = Depends(get_db)) -> PortalLink:
    client = request.client.host if request.client else "?"
    if not public_limiter.allow(client):
        raise HTTPException(status_code=429, detail="too many requests")
    digest = hashlib.sha256(x_portal_token.encode()).hexdigest()
    row = db.query(PortalLink).filter(PortalLink.token_hash == digest).first() if x_portal_token else None
    if not row or not hmac.compare_digest(row.token_hash, digest) or row.revoked or _aware(row.expires_at) <= dt.datetime.now(dt.timezone.utc):
        raise HTTPException(status_code=401, detail="this portal link is invalid, expired or revoked")
    return row


def _actor(link: PortalLink) -> dict:
    return {"actor_id": f"portal:{link.id}:{link.contact_email}", "actor_type": "customer"}


def _ticket_out(t: Ticket) -> dict:
    return {"id": t.id, "title": t.title, "body": t.body, "status": t.status, "priority": t.priority,
        "due_at": t.due_at, "created_at": t.created_at, "updated_at": t.updated_at}


def _own_ticket(db: Session, link: PortalLink, ticket_id: int) -> Ticket:
    t = db.query(Ticket).filter(Ticket.id == ticket_id, Ticket.org_id == link.org_id, Ticket.customer_id == link.customer_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="ticket not found")
    return t


@router.get("/me")
def me(link: PortalLink = Depends(portal_session), db: Session = Depends(get_db)):
    customer = db.get(Customer, link.customer_id)
    tickets = db.query(Ticket).filter(Ticket.org_id == link.org_id, Ticket.customer_id == link.customer_id).order_by(Ticket.id.desc()).limit(200).all()
    invoices = db.query(Invoice).filter(Invoice.org_id == link.org_id, Invoice.customer_id == link.customer_id).order_by(Invoice.period.desc()).limit(36).all()
    return {"customer": {"id": customer.id, "name": customer.name}, "contact_email": link.contact_email, "expires_at": _aware(link.expires_at),
        "tickets": [_ticket_out(t) for t in tickets],
        "invoices": [{"id": i.id, "period": i.period, "total": i.total, "lines": json.loads(i.lines or "[]"), "proof_id": i.proof_id,
            "created_at": i.created_at} for i in invoices]}


@router.get("/tickets/{ticket_id}")
def ticket(ticket_id: int, link: PortalLink = Depends(portal_session), db: Session = Depends(get_db)):
    t = _own_ticket(db, link, ticket_id)
    comments = db.query(TicketComment).filter(TicketComment.ticket_id == t.id, TicketComment.public.is_(True)).order_by(TicketComment.id).all()
    return {**_ticket_out(t), "comments": [{"id": c.id, "author": c.author, "body": c.body, "created_at": c.created_at} for c in comments]}


@router.post("/tickets", status_code=201)
def open_ticket(payload: PortalTicketIn, link: PortalLink = Depends(portal_session), db: Session = Depends(get_db)):
    from app.api.tickets import _severity, _sla_due

    t = Ticket(org_id=link.org_id, customer_id=link.customer_id, requester_email=link.contact_email, title=payload.title,
        body=payload.body, priority=payload.priority, severity=_severity(payload.priority, payload.title, payload.body),
        due_at=_sla_due(payload.priority))
    db.add(t)
    db.commit()
    emit(db, "ticket.created", {"title": t.title, "id": t.id, "priority": t.priority, "via": "portal"}, _actor(link),
        {"org_id": link.org_id, "ticket_id": t.id}, {"reason": "customer opened ticket in portal"})
    from app.services.automation_engine import evaluate

    evaluate(db, t.org_id, "ticket.opened", {"ticket_id": t.id, "priority": t.priority, "status": t.status})
    return _ticket_out(t)


@router.post("/tickets/{ticket_id}/comments", status_code=201)
def comment(ticket_id: int, payload: PortalCommentIn, link: PortalLink = Depends(portal_session), db: Session = Depends(get_db)):
    t = _own_ticket(db, link, ticket_id)
    c = TicketComment(ticket_id=t.id, org_id=link.org_id, author=link.contact_email, body=payload.body, public=True)
    db.add(c)
    if t.status in {"resolved", "pending"}:
        t.status = "open"
    db.commit()
    emit(db, "ticket.comment", {"ticket_id": t.id, "comment_id": c.id, "public": True, "via": "portal"}, _actor(link),
        {"org_id": link.org_id, "ticket_id": t.id}, {"reason": "customer reply in portal"})
    return {"id": c.id, "author": c.author, "body": c.body, "created_at": c.created_at}
