from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.proof import emit
from app.core.security import actor_of, get_current_user
from app.models.models import Ticket, TicketComment
from app.schemas.schemas import TicketCommentCreate, TicketCreate, TicketOut, TicketUpdate

router = APIRouter()

TRANSITIONS = {
    "open": {"in_progress", "pending", "closed", "cancelled"},
    "in_progress": {"open", "pending", "resolved", "closed"},
    "pending": {"open", "in_progress", "closed", "cancelled"},
    "resolved": {"closed", "open", "in_progress"},
    "closed": {"open"},
    "cancelled": {"open"},
}

SLA_HOURS = {"urgent": 1, "high": 4, "normal": 24, "low": 72}


def _sla_due(priority: str) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=SLA_HOURS.get(priority, 24))


def _severity(priority: str, title: str, body: str) -> str:
    if priority == "urgent":
        return "P1"
    if priority == "high":
        return "P2"
    text = f"{title} {body}".lower()
    if any(k in text for k in ("breach", "outage", "down", "offline", "critical", "security")):
        return "P1"
    return "P4" if priority == "low" else "P3"


def _load(db: Session, tid: int) -> Ticket:
    t = db.query(Ticket).filter(Ticket.id == tid).first()
    if not t:
        raise HTTPException(status_code=404, detail="ticket not found")
    return t


def _scope(user, org_id: int) -> None:
    if user.org_id != org_id:
        raise HTTPException(status_code=403, detail="org scope mismatch")


@router.get("", response_model=list[TicketOut])
def list_tickets(
    org_id: int,
    status: str | None = None,
    priority: str | None = None,
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _scope(user, org_id)
    q = db.query(Ticket).filter(Ticket.org_id == org_id)
    if status:
        q = q.filter(Ticket.status == status)
    if priority:
        q = q.filter(Ticket.priority == priority)
    return q.order_by(Ticket.created_at.desc()).limit(limit).all()


@router.get("/{tid}", response_model=TicketOut)
def get_ticket(tid: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    t = _load(db, tid)
    _scope(user, t.org_id)
    return t


@router.post("", response_model=TicketOut, status_code=201)
def create_ticket(payload: TicketCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, payload.org_id)
    t = Ticket(
        org_id=payload.org_id,
        title=payload.title,
        body=payload.body or "",
        priority=payload.priority or "normal",
        severity=_severity(payload.priority or "normal", payload.title, payload.body or ""),
        device_id=payload.device_id,
        due_at=_sla_due(payload.priority or "normal"),
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    emit(
        db,
        "ticket.created",
        {"title": t.title, "id": t.id, "priority": t.priority},
        actor_of(user),
        {"org_id": t.org_id, "ticket_id": t.id},
        {"reason": "ticket opened"},
    )
    from app.services.automation_engine import evaluate

    evaluate(db, t.org_id, "ticket.opened", {"ticket_id": t.id, "priority": t.priority, "status": t.status})
    return t


@router.patch("/{tid}", response_model=TicketOut)
def update_ticket(tid: int, payload: TicketUpdate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    t = _load(db, tid)
    _scope(user, t.org_id)
    if payload.status and payload.status != t.status:
        allowed = TRANSITIONS.get(t.status, set())
        if payload.status not in allowed:
            raise HTTPException(status_code=400, detail=f"cannot move {t.status} → {payload.status}")
        t.status = payload.status
        emit(
            db,
            "ticket.status",
            {"id": t.id, "status": t.status},
            actor_of(user),
            {"org_id": t.org_id, "ticket_id": t.id},
            {"reason": "status transition"},
        )
        from app.services.automation_engine import evaluate

        evaluate(db, t.org_id, f"ticket.{t.status}", {"ticket_id": t.id, "priority": t.priority, "status": t.status})
    for field in ("title", "body", "priority", "assignee", "device_id", "due_at"):
        val = getattr(payload, field)
        if val is not None:
            setattr(t, field, val)
    t.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(t)
    return t


@router.post("/{tid}/close", response_model=TicketOut)
def close_ticket(tid: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    t = _load(db, tid)
    _scope(user, t.org_id)
    t.status = "closed"
    t.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(t)
    emit(
        db,
        "ticket.closed",
        {"id": t.id},
        actor_of(user),
        {"org_id": t.org_id, "ticket_id": t.id},
        {"reason": "resolved"},
    )
    return t


@router.get("/{tid}/comments")
def list_comments(tid: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    t = _load(db, tid)
    _scope(user, t.org_id)
    rows = db.query(TicketComment).filter(TicketComment.ticket_id == tid).all()
    return [
        {"id": r.id, "ticket_id": r.ticket_id, "author": r.author, "body": r.body, "created_at": r.created_at.isoformat() if r.created_at else None}
        for r in rows
    ]


@router.post("/{tid}/comments", status_code=201)
def add_comment(tid: int, payload: TicketCommentCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    t = _load(db, tid)
    _scope(user, t.org_id)
    c = TicketComment(
        ticket_id=tid,
        org_id=t.org_id,
        author=payload.author or user.email,
        body=payload.body,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    emit(
        db,
        "ticket.comment",
        {"ticket_id": tid, "comment_id": c.id},
        actor_of(user),
        {"org_id": t.org_id, "ticket_id": tid},
        {"reason": "comment"},
    )
    return {"id": c.id, "ticket_id": c.ticket_id, "author": c.author, "body": c.body}
